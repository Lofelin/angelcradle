"""
API route registration.
"""

from fastapi import FastAPI

from .conceive import router as conceive_router
from .species import router as species_router
from .health import router as health_router
from .translate import router as translate_router
from .cradle import router as cradle_router


def create_app() -> FastAPI:
    app = FastAPI(title="Angel Cradle", description="World Womb — Nurturing AI Individuals")
    app.include_router(health_router)
    app.include_router(species_router)
    app.include_router(conceive_router)
    app.include_router(translate_router)
    app.include_router(cradle_router)
    return app
