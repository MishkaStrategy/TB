"""Controlled lifecycle operations for the shared Bitunix stream."""

from __future__ import annotations

import asyncio

from alerts.fvg_stream import BitunixFvgStream


async def restart_fvg_stream(application) -> None:
    """Replace the shared stream task without restarting the Telegram bot."""
    import alerts.scheduler as scheduler

    service = scheduler.get_fvg_service()
    if scheduler._FVG_STREAM is not None:
        scheduler._FVG_STREAM.stop()
    if scheduler._FVG_TASK is not None:
        scheduler._FVG_TASK.cancel()
        await asyncio.gather(scheduler._FVG_TASK, return_exceptions=True)

    scheduler._FVG_STREAM = BitunixFvgStream(service)
    scheduler._FVG_TASK = asyncio.create_task(
        scheduler._FVG_STREAM.run(application.bot),
        name="bitunix-fvg-stream",
    )
    service.event_store.increment_health("admin_ws_restarts")
