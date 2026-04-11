"""
API route registration.

[INPUT]: 依赖各子路由模块、scheduler、cradle
[OUTPUT]: create_app() 工厂函数（含 lifespan 管理）
[POS]: API 入口，注册所有路由 + 调度器生命周期
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .conceive import router as conceive_router
from .species import router as species_router
from .health import router as health_router
from .translate import router as translate_router
from .cradle import router as cradle_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动调度器，注册所有摇篮中的宝宝；关闭时停止调度器。"""
    from scheduler import scheduler
    from cradle import list_cradle_babies

    # 注册所有已存在的摇篮宝宝
    for baby in list_cradle_babies():
        await scheduler.register(baby["baby_id"])

    # 后台运行调度器主循环
    task = asyncio.create_task(scheduler.run())
    yield
    # 关闭时停止调度器
    scheduler.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="Angel Cradle",
        description="World Womb — Nurturing AI Individuals",
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(species_router)
    app.include_router(conceive_router)
    app.include_router(translate_router)
    app.include_router(cradle_router)
    return app
