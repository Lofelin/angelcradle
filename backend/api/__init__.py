"""
API route registration.

[INPUT]: 依赖各子路由模块、scheduler、cradle、memory（启动自检）
[OUTPUT]: create_app() 工厂函数（含 lifespan 管理：memory.self_heal + scheduler 主循环）
[POS]: API 入口，注册所有路由 + 调度器生命周期 + 记忆系统启动自检
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

# 全局日志配置：默认 INFO，可通过 LOG_LEVEL 环境变量覆盖
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)

from .conceive import router as conceive_router
from .species import router as species_router
from .health import router as health_router
from .translate import router as translate_router
from .cradle import router as cradle_router
from .conversations import router as conversations_router
from .system import router as system_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动调度器，注册所有摇篮中的宝宝；关闭时停止调度器。"""
    from scheduler import scheduler
    from cradle import list_cradle_babies
    from cradle.state import load_state

    # 记忆系统启动自检（D1-4 崩溃恢复）
    # 扫描每个 baby 的 life_moments.jsonl 与 state.memories，
    # 补齐 Step 3 成功 Step 4 未完成时留下的孤儿降级条目
    try:
        from memory import self_heal
        total_repaired = 0
        for baby in list_cradle_babies():
            bid = baby["baby_id"]
            st = load_state(bid)
            if st is None:
                continue
            try:
                repaired = self_heal(st, bid)
                if repaired:
                    from cradle.state import save_state
                    save_state(st)
                    total_repaired += repaired
            except Exception as e:
                logger.warning("memory.self_heal failed for %s: %s", bid, e)
        if total_repaired:
            logger.info("memory.self_heal 启动自检修复 %d 条降级条目", total_repaired)
    except Exception as e:
        # 记忆模块不可用不应阻断启动
        logger.warning("memory.self_heal import/run failed: %s", e)

    # 注册所有已存在的摇篮宝宝
    for baby in list_cradle_babies():
        await scheduler.register(baby["baby_id"])

    # 后台运行调度器主循环
    def _on_scheduler_done(t: asyncio.Task):
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.critical("调度器主循环异常退出: %s", exc, exc_info=exc)

    task = asyncio.create_task(scheduler.run())
    task.add_done_callback(_on_scheduler_done)
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
    app.include_router(conversations_router)
    app.include_router(system_router)
    return app
