"""Background worker loop (ROLE=worker). Real job processing lands in Step 8.

For Step 1 this only proves the ROLE switch works end-to-end: the worker
container logs a heartbeat instead of serving business routes.
"""
import asyncio
import logging

logger = logging.getLogger("app.jobs.worker")

HEARTBEAT_INTERVAL_SECONDS = 30


async def run_worker_loop() -> None:
    logger.info("worker loop started")
    try:
        while True:
            logger.info("worker heartbeat")
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("worker loop stopped")
        raise
