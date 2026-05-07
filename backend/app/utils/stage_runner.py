import asyncio
import logging
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Application
from app.schemas import ApplicationResponse
from app.utils.ws_manager import manager

logger = logging.getLogger(__name__)

STAGE_DURATIONS_S: dict[int, float] = {
    2: 5.0,
    3: 6.0,
    4: 4.0,
    5: 4.0,
    6: 3.0,
    7: 4.0,
    8: 2.0,
}

INTER_STAGE_GAP_S = 0.6
INITIAL_DELAY_S = 1.5

_BG_TASKS: set[asyncio.Task] = set()


def schedule(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


async def _set_and_broadcast(app_id: uuid.UUID, *, current_stage: int, status: str) -> None:
    async with SessionLocal() as db:
        result = await db.execute(select(Application).where(Application.id == app_id))
        app = result.scalar_one_or_none()
        if app is None:
            return
        app.current_stage = current_stage
        app.status = status
        await db.commit()
        await db.refresh(app, ["documents"])
        payload = ApplicationResponse.model_validate(app).model_dump(mode="json")

    await manager.broadcast(str(app_id), {"type": "application_update", "application": payload})


async def run_stages(app_id: uuid.UUID) -> None:
    """Simulate stages 2..8 progressing automatically with delays.

    Stage 9 (Exception Router) is intentionally left untouched in the happy path —
    it only activates when an earlier stage fails.
    """
    try:
        await asyncio.sleep(INITIAL_DELAY_S)
        for stage in (2, 3, 4, 5, 6, 7, 8):
            await _set_and_broadcast(app_id, current_stage=stage, status=f"stage_{stage}_running")
            await asyncio.sleep(STAGE_DURATIONS_S.get(stage, 4.0))
            await _set_and_broadcast(
                app_id, current_stage=stage + 1, status=f"stage_{stage}_complete"
            )
            await asyncio.sleep(INTER_STAGE_GAP_S)
        # All happy-path stages done. Park current_stage at 9 with status=completed —
        # the frontend treats stage 9 as skipped when status === "completed".
        await _set_and_broadcast(app_id, current_stage=9, status="completed")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("stage runner failed for application %s", app_id)
