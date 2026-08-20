"""创建并装配切线算法 FastAPI 应用。"""

from fastapi import FastAPI

from app.api.cutline_api import router as cutline_router
from app.api.cutline_api import configure_v6_stores
from app.api.v6_api import router as v6_router
from app.api.health_api import router as health_router


def create_app() -> FastAPI:
    """根据当前快照和业务规则执行【create_app】计算，返回类型标注所声明的结果。"""
    app = FastAPI(title="Cutline Algorithm Service")
    configure_v6_stores()
    app.include_router(health_router)
    app.include_router(v6_router)
    app.include_router(cutline_router)
    return app


app = create_app()
