"""Strict 15-minute Bitunix FVG stream policy."""

from alerts.fvg_stream import BitunixFvgStream


class FifteenMinuteBitunixFvgStream(BitunixFvgStream):
    """Subscribe to one closed-candle source for every FVG instrument."""

    @staticmethod
    def _channels_for(symbol: str) -> tuple[str, ...]:
        del symbol
        return ("market_kline_15min",)


__all__ = ["FifteenMinuteBitunixFvgStream"]
