"""Bridge the existing FVG scheduler to multi-exchange funding and Outbox V2."""

from alerts import scheduler as base
from alerts.multi_funding_alerts import MultiFundingAlertService
from config import OUTBOX_RETRY_POLICY_ENABLED
from handlers.multi_funding import CACHE_KEY


_FUNDING_SERVICE = None
_BASE_GET_FVG_SERVICE = base.get_fvg_service


def get_funding_service():
    global _FUNDING_SERVICE
    if _FUNDING_SERVICE is None:
        _FUNDING_SERVICE = MultiFundingAlertService()
    return _FUNDING_SERVICE


def get_fvg_service():
    if not OUTBOX_RETRY_POLICY_ENABLED:
        return _BASE_GET_FVG_SERVICE()
    if base._FVG_SERVICE is None:
        from alerts.fvg_service_v2 import OutboxV2FvgAlertService

        base._FVG_SERVICE = OutboxV2FvgAlertService()
    return base._FVG_SERVICE


async def run_funding_alerts(context):
    rates = await get_funding_service().run(context.bot)
    if rates is not None:
        context.bot_data[CACHE_KEY] = rates


def schedule_fvg_alerts(application):
    base.run_funding_alerts = run_funding_alerts
    base.get_funding_service = get_funding_service
    base.get_fvg_service = get_fvg_service
    return base.schedule_fvg_alerts(application)


start_fvg_stream = base.start_fvg_stream
stop_fvg_stream = base.stop_fvg_stream
