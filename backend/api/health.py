from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    from scheduler import scheduler
    return {
        "status": "alive",
        "scheduler_running": scheduler._running,
        "scheduler_agents": len(scheduler._registered),
        "scheduler_queue": len(scheduler._queue),
    }
