"""Graceful Bitunix stream wrapper with stop-accepting and queue drain."""

from __future__ import annotations

import asyncio
import logging

from alerts.fvg_stream import BitunixFvgStream


LOGGER = logging.getLogger(__name__)


class GracefulBitunixFvgStream(BitunixFvgStream):
    """Keep the delivery worker alive while shutdown drains queued events."""

    def __init__(self, service):
        super().__init__(service)
        self._accepting_events = True
        self._graceful_shutdown_requested = False
        self._delivery_worker_task = None

    @property
    def accepting_events(self) -> bool:
        return self._accepting_events

    @property
    def pending_delivery_count(self) -> int:
        return int(self._delivery_queue.qsize())

    def stop_accepting(self) -> None:
        self._accepting_events = False
        self._graceful_shutdown_requested = True
        self.stop()

    def _enqueue(self, events) -> None:
        if not self._accepting_events:
            if events:
                self.service.event_store.increment_health(
                    "delivery_events_rejected_during_shutdown",
                    len(events),
                )
            return
        super()._enqueue(events)

    async def _deliver_until_drained(self, bot) -> None:
        """Exit after shutdown is requested and all accepted queue work is done."""
        while True:
            if self._graceful_shutdown_requested and self._delivery_queue.empty():
                return
            try:
                events = await asyncio.wait_for(
                    self._delivery_queue.get(),
                    timeout=0.1,
                )
            except asyncio.TimeoutError:
                continue

            event_ids = {event.event_id for event in events}
            try:
                await self.service.deliver(bot, events)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                LOGGER.exception("Unexpected FVG delivery worker failure")
                self.service.event_store.update_health(last_error=str(error))
                self.service.event_store.increment_health("delivery_worker_failures")
            finally:
                self._pending_event_ids.difference_update(event_ids)
                self._delivery_queue.task_done()

    async def run(self, bot) -> None:
        delivery_worker = asyncio.create_task(
            self._deliver_until_drained(bot),
            name="fvg-delivery-worker",
        )
        self._delivery_worker_task = delivery_worker
        force_cancelled = False
        try:
            await self._run_market()
        except asyncio.CancelledError:
            force_cancelled = True
            raise
        finally:
            if force_cancelled or not self._graceful_shutdown_requested:
                if not delivery_worker.done():
                    delivery_worker.cancel()
                await asyncio.gather(delivery_worker, return_exceptions=True)
            elif not delivery_worker.done():
                await delivery_worker
            self._delivery_worker_task = None

    async def drain(self, *, timeout_seconds: float) -> dict:
        timeout_seconds = max(0.01, float(timeout_seconds))
        pending_before = self.pending_delivery_count
        try:
            await asyncio.wait_for(
                self._delivery_queue.join(),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {
                "drained": False,
                "pending_before": pending_before,
                "pending_after": self.pending_delivery_count,
                "timeout": True,
            }
        return {
            "drained": True,
            "pending_before": pending_before,
            "pending_after": self.pending_delivery_count,
            "timeout": False,
        }
