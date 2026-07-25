import requests


class BitunixClient:

    BASE_URL = "https://fapi.bitunix.com"
    REQUEST_TIMEOUT_SECONDS = 15
    INTERVAL_MILLISECONDS = {
        "1m": 60_000,
        "3m": 180_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
        "1d": 86_400_000,
        "1w": 604_800_000,
    }

    def __init__(self, session=None):
        self.session = session or requests


    def get_candles(
        self,
        symbol="BTCUSDT",
        interval="15m",
        limit=100,
        start_time=None,
        end_time=None,
    ):

        url = f"{self.BASE_URL}/api/v1/futures/market/kline"

        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }

        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)

        response = self.session.get(
            url,
            params=params,
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )

        response.raise_for_status()

        return response.json()

    def get_ticker(self, symbol="BTCUSDT"):
        response = self.session.get(
            f"{self.BASE_URL}/api/v1/futures/market/tickers",
            params={"symbols": symbol},
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        tickers = data.get("data", [])

        if not tickers:
            raise ValueError(f"No ticker returned for {symbol}")

        return tickers[0]

    def get_all_tickers(self):
        """Return 24-hour ticker data for all futures instruments."""
        response = self.session.get(
            f"{self.BASE_URL}/api/v1/futures/market/tickers",
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        tickers = response.json().get("data", [])
        if not isinstance(tickers, list):
            raise ValueError("Unexpected tickers format from Bitunix")
        return tickers

    def get_trading_pairs(self, symbols=None):
        """Return public futures instruments; no API credentials are required."""
        params = {}
        if symbols:
            params["symbols"] = ",".join(symbols) if not isinstance(symbols, str) else symbols
        response = self.session.get(
            f"{self.BASE_URL}/api/v1/futures/market/trading_pairs",
            params=params,
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json().get("data", [])

    def is_open_symbol(self, symbol):
        return any(
            item.get("symbol") == symbol.upper()
            and item.get("symbolStatus") == "OPEN"
            for item in self.get_trading_pairs([symbol.upper()])
        )

    def get_funding_rate(self, symbol):
        response = self.session.get(
            f"{self.BASE_URL}/api/v1/futures/market/funding_rate",
            params={"symbol": symbol},
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        rates = response.json().get("data")

        if isinstance(rates, dict):
            return rates
        if isinstance(rates, list) and rates:
            return rates[0]

        if not rates:
            raise ValueError(f"No funding rate returned for {symbol}")

        raise ValueError(f"Unexpected funding rate format for {symbol}")

    def get_all_funding_rates(self):
        """Return current funding rates for all available futures instruments."""
        response = self.session.get(
            f"{self.BASE_URL}/api/v1/futures/market/funding_rate/batch",
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        rates = response.json().get("data", [])
        if isinstance(rates, dict):
            return [rates]
        if isinstance(rates, list):
            return rates
        raise ValueError("Unexpected funding rates format from Bitunix")

    def get_historical_candles(
        self,
        symbol,
        interval,
        start_time,
        end_time,
        limit=200,
    ):
        """Download a complete, de-duplicated candle range in chronological order."""
        if interval not in self.INTERVAL_MILLISECONDS:
            raise ValueError(f"Unsupported interval: {interval}")
        if start_time >= end_time:
            raise ValueError("start_time must be earlier than end_time")
        limit = min(int(limit), 200)

        candles_by_time = {}
        cursor = int(end_time)

        while cursor > start_time:
            response = self.get_candles(
                symbol=symbol,
                interval=interval,
                limit=limit,
                end_time=cursor,
            )
            batch = response.get("data", [])

            if not batch:
                break

            oldest_time = min(int(candle["time"]) for candle in batch)
            for candle in batch:
                candle_time = int(candle["time"])
                if start_time <= candle_time <= end_time:
                    candles_by_time[candle_time] = candle

            if oldest_time >= cursor:
                raise RuntimeError("Bitunix returned a non-progressing candle page")

            cursor = oldest_time - 1

        return [
            candles_by_time[candle_time]
            for candle_time in sorted(candles_by_time)
        ]
