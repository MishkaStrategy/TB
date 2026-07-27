"""Bridge the existing FVG scheduler to the multi-exchange funding service."""

from alerts import scheduler as base
from alerts.multi_funding_alerts import MultiFundingAlertService
from handlers.multi_funding import CACHE_KEY

_FUNDING_SERVICE = None


def get_funding_service():
    global _FUNDING_SERVICE
    if _FUNDING_SERVICE is None:
        _FUNDING_SERVICE = MultiFundingAlertService()
    return _FUNDING_SERVICE


async def run_funding_alerts(context):
    rates = await get_funding_service().run(context.bot)
    if rates is not None:
        context.bot_data[CACHE_KEY] = rates


def schedule_fvg_alerts(application):
    base.run_funding_alerts = run_funding_alerts
    base.get_funding_service = get_funding_service
    return base.schedule_fvg_alerts(application)


start_fvg_stream = base.start_fvg_stream
stop_fvg_stream = base.stop_fvg_stream
