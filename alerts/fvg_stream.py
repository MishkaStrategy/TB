"""One shared reconnecting Bitunix public WebSocket for all active symbols."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from datetime import datetime, timezone

import aiohttp
import certifi

from config import FVG_DELIVERY_QUEUE_SIZE, MAX_ACTIVE_SYMBOLS
from exchanges.fvg_candles import is_bitcoin_symbol


logger = logging.getLogger(__name__)
UTC = timezone.utc
DEFAULT_KLINE_STALE_SECONDS = 120.0


class BitunixFvgStream:
    URL = "wss://fapi.bitunix.com/public/"

    def __init__(
        self,
        service,
        reconnect_min=1,
        reconnect_max=60,
        kline_stale_seconds=DEFAULT_KLINE_STALE_SECONDS,
    ):
        self.service = service
        self.reconnect_min = reconnect_min
        self.reconnect_max = reconnect_max
        self.kline_stale_seconds = float(kline_stale_seconds)
        if self.kline_stale_seconds <= 0:
            raise ValueError("kline_stale_seconds must be greater than zero")
        self._stopping = False
        self._delivery_queue = asyncio.Queue(maxsize=FVG_DELIVERY_QUEUE_SIZE)
        self._pending_event_ids: set[str] = set()

    def _active_symbols(self) -> list[str]:
        symbols = sorted(self.service.settings.active_symbols())
        if len(symbols) > MAX_ACTIVE_SYMBOLS:
            logger.error(
                "Active symbol limit exceeded: configured=%s allowed=%s",
                len(symbols),
                MAX_ACTIVE_SYMBOLS,
            )
        return symbols[:MAX_ACTIVE_SYMBOLS]

    @staticmethod
    def _channels_for(symbol: str) -> tuple[str, ...]:
        if is_bitcoin_symbol(symbol):
            return ("market_kline_1min", "market_kline_15min")
        return ("market_kline_15min",)

    def _raise_if_kline_stale(
        self,
        last_kline_at: float,
        *,
        now: float | None = None,
    ) -> None:
        """Force reconnect when a live socket stops delivering market candles."""
        current = time.monotonic() if now is None else float(now)
        age = max(0.0, current - float(last_kline_at))
        if age >= self.kline_stale_seconds:
            raise ConnectionError(
                "Bitunix WebSocket stale: no kline messages for "
                f"{int(age)} seconds"
            )

    def _check_kline_watchdog(
        self,
        last_kline_at: float,
        *,
        now: float | None = None,
    ) -> None:
        """Record and surface stale-stream reconnects on every receive loop."""
        try:
            self._raise_if_kline_stale(last_kline_at, now=now)
        except ConnectionError:
            self.service.event_store.increment_health("stale_ws_reconnects")
            raise

    async def run(self, bot) -> None:
        delivery_worker = asyncio.create_task(
            self._deliver_worker(bot),
            name="fvg-delivery-worker",
        )
        try:
            await self._run_market()
        finally:
            delivery_worker.cancel()
            await asyncio.gather(delivery_worker, return_exceptions=True)

    async def _deliver_worker(self, bot) -> None:
        while True:
            events = await self._delivery_queue.get()
            event_ids = {event.event_id for event in events}
            try:
                await self.service.deliver(bot, events)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.exception("Unexpected FVG delivery worker failure")
                self.service.event_store.update_health(last_error=str(error))
                self.service.event_store.increment_health("delivery_worker_failures")
            finally:
                self._pending_event_ids.difference_update(event_ids)
                self._delivery_queue.task_done()

    @staticmethod
    async def _ping(ws) -> None:
        while True:
            await ws.send_json({"op": "ping", "ping": int(time.time())})
            await asyncio.sleep(3)

    def _enqueue(self, events) -> None:
        new_events = [
            event
            for event in events
            if event.event_id not in self._pending_event_ids
        ]
        if not new_events:
            return

        event_ids = {event.event_id for event in new_events}
        self._pending_event_ids.update(event_ids)
        try:
            self._delivery_queue.put_nowait(new_events)
        except asyncio.QueueFull:
            self._pending_event_ids.difference_update(event_ids)
            logger.error(
                "FVG delivery queue is full; dropped %s event(s)",
                len(new_events),
            )
            self.service.event_store.increment_health(
                "delivery_queue_drops",
                len(new_events),
            )

    async def _recover_symbol(self, symbol: str, now: datetime | None = None) -> None:
        try:
            events = await asyncio.to_thread(self.service.recover, symbol, now)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Bitunix recovery failed for %s: %s", symbol, error)
            self.service.event_store.update_health(last_error=str(error))
            self.service.event_store.increment_health("recovery_failures")
        else:
            self._enqueue(events)

    @staticmethod
    def _track_task(tasks: set[asyncio.Task], coroutine, name: str) -> asyncio.Task:
        task = asyncio.create_task(coroutine, name=name)
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return task

    async def _run_market(self) -> None:
        delay = self.reconnect_min
        while not self._stopping:
            symbols = self._active_symbols()
            if not symbols:
                await asyncio.sleep(5)
                continue
            try:
                timeout = aiohttp.ClientTimeout(total=None, sock_read=45)
                ssl_context = ssl.create_default_context(cafile=certifi.where())
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.ws_connect(
                        self.URL,
                        ssl=ssl_context,
                    ) as ws:
                        args = [
                            {"symbol": symbol, "ch": channel}
                            for symbol in symbols
                            for channel in self._channels_for(symbol)
                        ]
                        await ws.send_json({"op": "subscribe", "args": args})
                        now = datetime.now(UTC)
                        last_kline_at = time.monotonic()
                        self.service.event_store.update_health(
                            ws_connected=True,
                            subscribed_symbols=symbols,
                            last_reconnect=now.isoformat(),
                            last_error=None,
                        )
                        delay = self.reconnect_min
                        subscribed = set(symbols)
                        connection_tasks: set[asyncio.Task] = set()
                        ping_task = self._track_task(
                            connection_tasks,
                            self._ping(ws),
                            "bitunix-ping",
                        )
                        for symbol in symbols:
                            self._track_task(
                                connection_tasks,
                                self._recover_symbol(symbol, now),
                                f"bitunix-recover-{symbol}",
                            )
                        try:
                            while not self._stopping:
                                # Check before every receive, not only after a timeout.
                                # Frequent pong/ack/control messages must not conceal a
                                # market stream that has stopped producing candles.
                                self._check_kline_watchdog(last_kline_at)

                                current = set(self._active_symbols())
                                removed = subscribed - current
                                added = current - subscribed
                                if removed:
                                    await ws.send_json({
                                        "op": "unsubscribe",
                                        "args": [
                                            {"symbol": symbol, "ch": channel}
                                            for symbol in sorted(removed)
                                            for channel in self._channels_for(symbol)
                                        ],
                                    })
                                if added:
                                    await ws.send_json({
                                        "op": "subscribe",
                                        "args": [
                                            {"symbol": symbol, "ch": channel}
                                            for symbol in sorted(added)
                                            for channel in self._channels_for(symbol)
                                        ],
                                    })
                                    for symbol in sorted(added):
                                        self._track_task(
                                            connection_tasks,
                                            self._recover_symbol(symbol),
                                            f"bitunix-recover-{symbol}",
                                        )
                                if removed or added:
                                    subscribed = current
                                    self.service.event_store.update_health(
                                        subscribed_symbols=sorted(subscribed)
                                    )
                                try:
                                    message = await ws.receive(timeout=5)
                                except asyncio.TimeoutError:
                                    continue
                                if message.type in {
                                    aiohttp.WSMsgType.CLOSE,
                                    aiohttp.WSMsgType.CLOSED,
                                    aiohttp.WSMsgType.CLOSING,
                                    aiohttp.WSMsgType.ERROR,
                                }:
                                    raise ConnectionError("Bitunix WebSocket closed")
                                if message.type != aiohttp.WSMsgType.TEXT:
                                    continue
                                try:
                                    payload = json.loads(message.data)
                                except (json.JSONDecodeError, TypeError) as error:
                                    logger.warning(
                                        "Invalid Bitunix WebSocket JSON: %s",
                                        error,
                                    )
                                    self.service.event_store.increment_health(
                                        "invalid_messages"
                                    )
                                    continue
                                if (
                                    payload.get("ch", "").startswith("market_kline_")
                                    and payload.get("data")
                                ):
                                    try:
                                        events = self.service.ingest_ws(payload)
                                    except (ValueError, KeyError, TypeError) as error:
                                        logger.warning(
                                            "Invalid Bitunix FVG WebSocket candle: %s",
                                            error,
                                        )
                                        self.service.event_store.increment_health(
                                            "invalid_candles"
                                        )
                                    else:
                                        last_kline_at = time.monotonic()
                                        self._enqueue(events)
                        finally:
                            ping_task.cancel()
                            for task in tuple(connection_tasks):
                                task.cancel()
                            await asyncio.gather(
                                *connection_tasks,
                                return_exceptions=True,
                            )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("Bitunix FVG WebSocket disconnected: %s", error)
                self.service.event_store.update_health(
                    ws_connected=False,
                    last_error=str(error),
                )
                self.service.event_store.increment_health("reconnects")
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_max)

    def stop(self) -> None:
        self._stopping = True
