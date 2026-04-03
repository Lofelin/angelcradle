"""
API 路由注册。
"""

from fastapi import FastAPI

from .conceive import router as conceive_router
from .species import router as species_router
from .health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="Angel Cradle", description="世界子宫 — 孕育 AI 个体")
    app.include_router(health_router)
    app.include_router(species_router)
    app.include_router(conceive_router)
    return app
