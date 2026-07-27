"""Public funding-rate adapters normalized to percentage-point units."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Iterable

import requests

from exchanges.bitunix import BitunixClient


EXCHANGE_ORDER = ("bitunix", "binance", "bybit", "bitget", "gate")
EXCHANGE_LABELS = {
    "bitunix": "Bitunix",
    "binance": "Binance",
    "bybit": "Bybit",
    "bitget": "Bitget",
    "gate": "Gate",
}
DEFAULT_EXCHANGE = "bitunix"
REQUEST_TIMEOUT_SECONDS = 15


def normalize_exchange(value: str | None) -> str:
    exchange = str(value or DEFAULT_EXCHANGE).strip().lower()
    if exchange not in EXCHANGE_LABELS:
        raise ValueError(f"Unsupported funding exchange: {exchange}")
    return exchange


def normalize_exchanges(values: Iterable[str] | str | None) -> tuple[str, ...]:
    if values is None:
        values = (DEFAULT_EXCHANGE,)
    elif isinstance(values, str):
        values = values.split(",")
    selected = {normalize_exchange(value) for value in values if str(value).strip()}
    ordered = tuple(exchange for exchange in EXCHANGE_ORDER if exchange in selected)
    if not ordered:
        raise ValueError("Нужно выбрать хотя бы одну биржу.")
    return ordered


def exchange_label(exchange: str) -> str:
    return EXCHANGE_LABELS[normalize_exchange(exchange)]


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _percent_from_ratio(value) -> Decimal | None:
    parsed = _decimal(value)
    return parsed * 100 if parsed is not None else None


def _text(value: Decimal | None) -> str | None:
    return str(value.normalize()) if value is not None else None


def _record(exchange, symbol, funding_rate, price_change_24h=None):
    if not symbol or funding_rate is None:
        return None
    return {
        "exchange": normalize_exchange(exchange),
        "symbol": str(symbol).upper().replace("_", ""),
        "fundingRate": _text(funding_rate),
        "priceChange24h": _text(price_change_24h),
    }


class PublicFundingClient:
    """Fetch current USDT perpetual funding from public exchange endpoints."""

    BINANCE_BASE_URL = "https://fapi.binance.com"
    BYBIT_BASE_URL = "https://api.bybit.com"
    BITGET_BASE_URL = "https://api.bitget.com"
    GATE_BASE_URL = "https://api.gateio.ws/api/v4"

    def __init__(self, session=None, bitunix_client=None):
        self.session = session or requests
        self.bitunix = bitunix_client or BitunixClient(session=session)

    def _get_json(self, url: str, *, params: dict | None = None):
        response = self.session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def load(self, exchange: str) -> list[dict]:
        exchange = normalize_exchange(exchange)
        return getattr(self, f"_load_{exchange}")()

    def _load_bitunix(self):
        rates = self.bitunix.get_all_funding_rates()
        tickers = {
            item.get("symbol"): item
            for item in self.bitunix.get_all_tickers()
            if isinstance(item, dict) and item.get("symbol")
        }
        normalized = []
        for item in rates:
            if not isinstance(item, dict):
                continue
            ticker = tickers.get(item.get("symbol"), {})
            last_price = _decimal(ticker.get("lastPrice", ticker.get("last")))
            open_price = _decimal(ticker.get("open"))
            change = None
            if last_price is not None and open_price not in (None, Decimal("0")):
                change = (last_price / open_price - 1) * 100
            record = _record(
                "bitunix",
                item.get("symbol"),
                _decimal(item.get("fundingRate", item.get("funding_rate"))),
                change,
            )
            if record:
                normalized.append(record)
        return normalized

    def _load_binance(self):
        premium = self._get_json(f"{self.BINANCE_BASE_URL}/fapi/v1/premiumIndex")
        tickers = self._get_json(f"{self.BINANCE_BASE_URL}/fapi/v1/ticker/24hr")
        changes = {
            item.get("symbol"): _decimal(item.get("priceChangePercent"))
            for item in tickers
            if isinstance(item, dict) and item.get("symbol")
        }
        normalized = []
        for item in premium:
            if not isinstance(item, dict):
                continue
            symbol = item.get("symbol")
            if not str(symbol or "").endswith("USDT"):
                continue
            record = _record(
                "binance",
                symbol,
                _percent_from_ratio(item.get("lastFundingRate")),
                changes.get(symbol),
            )
            if record:
                normalized.append(record)
        return normalized

    def _load_bybit(self):
        payload = self._get_json(
            f"{self.BYBIT_BASE_URL}/v5/market/tickers",
            params={"category": "linear"},
        )
        if str(payload.get("retCode", "0")) != "0":
            raise ValueError(f"Bybit funding error: {payload.get('retMsg', 'unknown')}")
        normalized = []
        for item in payload.get("result", {}).get("list", []):
            if not isinstance(item, dict):
                continue
            symbol = item.get("symbol")
            if not str(symbol or "").endswith("USDT"):
                continue
            record = _record(
                "bybit",
                symbol,
                _percent_from_ratio(item.get("fundingRate")),
                _percent_from_ratio(item.get("price24hPcnt")),
            )
            if record:
                normalized.append(record)
        return normalized

    def _load_bitget(self):
        rates_payload = self._get_json(
            f"{self.BITGET_BASE_URL}/api/v2/mix/market/current-fund-rate",
            params={"productType": "usdt-futures"},
        )
        tickers_payload = self._get_json(
            f"{self.BITGET_BASE_URL}/api/v2/mix/market/tickers",
            params={"productType": "usdt-futures"},
        )
        if rates_payload.get("code") != "00000":
            raise ValueError(f"Bitget funding error: {rates_payload.get('msg', 'unknown')}")
        if tickers_payload.get("code") != "00000":
            raise ValueError(f"Bitget ticker error: {tickers_payload.get('msg', 'unknown')}")
        changes = {
            item.get("symbol"): _percent_from_ratio(item.get("change24h"))
            for item in tickers_payload.get("data", [])
            if isinstance(item, dict) and item.get("symbol")
        }
        normalized = []
        for item in rates_payload.get("data", []):
            if not isinstance(item, dict):
                continue
            symbol = item.get("symbol")
            if not str(symbol or "").endswith("USDT"):
                continue
            record = _record(
                "bitget",
                symbol,
                _percent_from_ratio(item.get("fundingRate")),
                changes.get(symbol),
            )
            if record:
                normalized.append(record)
        return normalized

    def _load_gate(self):
        items = self._get_json(f"{self.GATE_BASE_URL}/futures/usdt/tickers")
        normalized = []
        for item in items:
            if not isinstance(item, dict):
                continue
            symbol = item.get("contract")
            if not str(symbol or "").endswith("_USDT"):
                continue
            record = _record(
                "gate",
                symbol,
                _percent_from_ratio(item.get("funding_rate")),
                _decimal(item.get("change_percentage")),
            )
            if record:
                normalized.append(record)
        return normalized
