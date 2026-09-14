from fastapi import APIRouter

from app.observability.metrics import metrics

router = APIRouter(tags=["observability"])


@router.get("/metrics")
async def get_metrics() -> dict[str, object]:
    return metrics.snapshot()
