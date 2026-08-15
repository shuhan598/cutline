"""创建并装配切线算法 FastAPI 应用。"""

from fastapi import FastAPI

from app.api.cutline_api import router as cutline_router
from app.api.health_api import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="Cutline Algorithm Service")
    app.include_router(health_router)
    app.include_router(cutline_router)
    return app


app = create_app()
