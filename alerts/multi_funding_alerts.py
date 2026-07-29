"""Multi-exchange funding notifications on a shared quarter-hour snapshot."""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal, InvalidOperation
from html import escape

from alerts.funding_quarter_hour import FundingAlertStore
from alerts.funding_alerts import parse_threshold, utc_now
from alerts.funding_exchange_store import FundingExchangeStore
from alerts.funding_snapshot_store import FundingSnapshotStore
from alerts.telegram_errors import TelegramErrorKind, classify_telegram_error
from config import DELIVERY_STATUS_TRACKING_ENABLED, USER_BLOCK_STATUS_ENABLED
from database.telegram_delivery import TelegramDeliveryRegistry
from exchanges.funding import EXCHANGE_LABELS, exchange_label, normalize_exchange

LOGGER = logging.getLogger(__name__)


def _rate(item: dict) -> Decimal | None:
    for key in ("fundingRate", "funding_rate", "rate"):
        try:
            value = Decimal(str(item.get(key)))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if value.is_finite():
            return value
    return None


def matching_crossings(snapshot, settings, exchanges):
    threshold = parse_threshold(settings["threshold"])
    selected = set(exchanges)
    matches = {}
    for exchange, rates in snapshot.items():
        try:
            exchange = normalize_exchange(exchange)
        except ValueError:
            continue
        if exchange not in selected or not isinstance(rates, list):
            continue
        for item in rates:
            if not isinstance(item, dict) or not item.get("symbol"):
                continue
            rate = _rate(item)
            if rate is None:
                continue
            direction = None
            if settings["notify_positive"] and rate >= threshold:
                direction = "positive"
            elif settings["notify_negative"] and rate <= -threshold:
                direction = "negative"
            if direction:
                matches[(exchange, str(item["symbol"]), direction)] = rate
    return matches


def format_alert(settings, exchanges, crossings):
    threshold = parse_threshold(settings["threshold"])
    direction = (
        "положительный и отрицательный"
        if settings["notify_positive"] and settings["notify_negative"]
        else "положительный" if settings["notify_positive"] else "отрицательный"
    )
    selected_text = ", ".join(EXCHANGE_LABELS[value] for value in exchanges)
    header = (
        "🔔 <b>Фандинг пересёк заданный порог</b>\n"
        f"Порог: {threshold}%\n"
        f"Направление: {direction}\n"
        f"Биржи: {escape(selected_text)}\n\n"
    )
    lines = []
    for (exchange, symbol, rate_direction), rate in sorted(
        crossings.items(), key=lambda item: abs(item[1]), reverse=True
    ):
        icon = "🟢" if rate_direction == "positive" else "🔴"
        sign = "+" if rate > 0 else ""
        lines.append(
            f"{icon} <b>{escape(exchange_label(exchange))}</b> "
            f"<code>{escape(symbol[:24])}</code>: {sign}{rate:.4f}%"
        )
    messages, current = [], header
    for line in lines:
        if len(current) + len(line) + 1 > 3800:
            messages.append(current.rstrip())
            current = "🔔 <b>Продолжение уведомления о фандинге</b>\n\n"
        current += line + "\n"
    if current.strip():
        messages.append(current.rstrip())
    return messages


class MultiFundingAlertService:
    def __init__(
        self,
        settings_store=None,
        exchange_store=None,
        snapshot_store=None,
        loader=None,
        delivery_registry=None,
    ):
        self.settings_store = settings_store or FundingAlertStore()
        path = getattr(self.settings_store, "path", None)
        self.exchange_store = exchange_store or FundingExchangeStore(path)
        self.snapshot_store = snapshot_store or FundingSnapshotStore(path)
        self.loader = loader
        self.delivery_registry = delivery_registry
        if self.delivery_registry is None and (
            DELIVERY_STATUS_TRACKING_ENABLED or USER_BLOCK_STATUS_ENABLED
        ):
            self.delivery_registry = TelegramDeliveryRegistry()

    async def _load(self):
        if self.loader is not None:
            return await self.loader()
        from handlers.multi_funding import load_funding_snapshot
        return await load_funding_snapshot()

    async def _consume_without_delivery(
        self,
        chat_id,
        current,
        current_time,
    ) -> None:
        """Advance state without creating a backlog for a permanently unavailable chat."""
        await asyncio.to_thread(
            self.exchange_store.replace_crossings,
            chat_id,
            current,
            now=current_time,
        )
        await asyncio.to_thread(
            self.settings_store.advance,
            chat_id,
            current_time,
        )

    async def run(self, bot, *, now=None):
        current_time = now or utc_now()
        await asyncio.to_thread(self.settings_store.cleanup, current_time)
        await asyncio.to_thread(self.exchange_store.cleanup, now=current_time)
        try:
            snapshot = await self._load()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Quarter-hour multi-exchange funding refresh failed")
            return None
        if not isinstance(snapshot, dict) or not snapshot:
            LOGGER.error("No exchange returned a funding snapshot")
            return None

        try:
            await asyncio.to_thread(
                self.snapshot_store.save,
                snapshot,
                captured_at=current_time,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Failed to persist bounded funding snapshot history")

        available = {
            key
            for key, value in snapshot.items()
            if key in EXCHANGE_LABELS and isinstance(value, list)
        }
        due_users = await asyncio.to_thread(
            self.settings_store.due_users,
            current_time,
        )
        for settings in due_users:
            chat_id = settings["chat_id"]
            selected = await asyncio.to_thread(
                self.exchange_store.selected,
                chat_id,
            )
            working = set(selected) & available
            if not working:
                LOGGER.warning(
                    "No selected funding exchange available for chat_id=%s",
                    chat_id,
                )
                continue
            try:
                current = matching_crossings(snapshot, settings, selected)
                previous = await asyncio.to_thread(
                    self.exchange_store.crossing_values,
                    chat_id,
                )
                unavailable = set(selected) - available
                for key, value in previous.items():
                    if key[0] in unavailable:
                        current[key] = value
                fresh = {
                    key: value
                    for key, value in current.items()
                    if key not in previous and key[0] in working
                }

                if self.delivery_registry is not None:
                    if not await asyncio.to_thread(
                        self.delivery_registry.can_deliver,
                        chat_id,
                    ):
                        LOGGER.info(
                            "Funding delivery suppressed for unavailable chat_id=%s",
                            chat_id,
                        )
                        await self._consume_without_delivery(
                            chat_id,
                            current,
                            current_time,
                        )
                        continue

                    delivery_failed = False
                    for text in format_alert(settings, selected, fresh) if fresh else ():
                        try:
                            await bot.send_message(
                                chat_id=chat_id,
                                text=text,
                                parse_mode="HTML",
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as error:
                            decision = classify_telegram_error(error)
                            log = getattr(LOGGER, decision.log_level, LOGGER.warning)
                            log(
                                "Funding delivery failed chat_id=%s code=%s: %s",
                                chat_id,
                                decision.code,
                                error,
                            )
                            if decision.kind is TelegramErrorKind.IGNORABLE:
                                await asyncio.to_thread(
                                    self.delivery_registry.record_success,
                                    chat_id,
                                )
                                continue
                            await asyncio.to_thread(
                                self.delivery_registry.record_failure,
                                chat_id,
                                decision,
                                error,
                            )
                            if decision.retryable:
                                delivery_failed = True
                                break
                            await self._consume_without_delivery(
                                chat_id,
                                current,
                                current_time,
                            )
                            delivery_failed = True
                            break
                        else:
                            await asyncio.to_thread(
                                self.delivery_registry.record_success,
                                chat_id,
                            )
                    if delivery_failed:
                        continue
                else:
                    for text in format_alert(settings, selected, fresh) if fresh else ():
                        await bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            parse_mode="HTML",
                        )

                await asyncio.to_thread(
                    self.exchange_store.replace_crossings,
                    chat_id,
                    current,
                    now=current_time,
                )
                await asyncio.to_thread(
                    self.settings_store.advance,
                    chat_id,
                    current_time,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "Funding notification failed for chat_id=%s",
                    chat_id,
                )
        return snapshot
