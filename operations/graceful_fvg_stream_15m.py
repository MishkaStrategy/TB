"""Graceful shutdown wrapper for strict 15-minute FVG streaming."""

from operations.graceful_fvg_stream import GracefulBitunixFvgStream


class FifteenMinuteGracefulBitunixFvgStream(GracefulBitunixFvgStream):
    """Keep graceful draining while subscribing only to Bitunix 15m klines."""

    @staticmethod
    def _channels_for(symbol: str) -> tuple[str, ...]:
        del symbol
        return ("market_kline_15min",)


__all__ = ["FifteenMinuteGracefulBitunixFvgStream"]
