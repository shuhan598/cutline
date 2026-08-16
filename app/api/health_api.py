"""提供服务存活状态检查接口。"""

from fastapi import APIRouter


router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    """执行【health_check】业务操作；参数、返回值和异常语义以类型标注及调用方契约为准。"""
    return {"status": "ok"}
