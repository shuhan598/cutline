"""提供后端请求校验、算法试算和正式评估的 HTTP 接口。"""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import ValidationError

from app.adapters.backend_request_loader import (
    BackendRequestLoadError,
    BackendRequestLoader,
)
from app.adapters.backend_request_validator import (
    BackendRequestCompletenessValidator,
    BackendRequestValidationResult,
    BackendValidationIssue,
)
from app.adapters.snapshot_adapter import SnapshotConversionError
from app.schemas.request_schema import CutlineAlgorithmRequest
from app.schemas.v6_schema import (
    CatalogPatchRequest,
    CatalogResponse,
    FullCatalogRequest,
    V6EvaluateRequest,
    V6EvaluateResponse,
)
from app.schemas.response_schema import (
    CutlineAlgorithmResponse,
    CutlineEvaluateResponse,
)
from app.service.cutline_service import CutlineService
from app.service.algorithm_state_store import AlgorithmStateStore
from app.service.catalog_store import CatalogStore, CatalogStoreError
from app.utils.algorithm_exception_logger import log_algorithm_exception
from app.utils.input_error_codes import http_error_code


router = APIRouter(tags=["cutline"])

_backend_loader = BackendRequestLoader()
_backend_validator = BackendRequestCompletenessValidator()
_cutline_service = CutlineService()
_catalog_store = CatalogStore(strict=True)
_state_store = AlgorithmStateStore()


def configure_v6_stores() -> None:
    """在创建新的应用实例时重置进程内 V6 目录和跨轮状态。

    应用工厂模式下每个实例必须拥有独立的内存目录和车间状态，避免测试或多个
    应用实例之间泄漏已发布目录、幂等键和上一轮计算状态。
    """
    global _catalog_store, _state_store
    _catalog_store = CatalogStore(strict=True)
    _state_store = AlgorithmStateStore()


def get_cutline_service() -> CutlineService:
    """执行【get_cutline_service】业务操作；参数、返回值和异常语义以类型标注及调用方契约为准。"""
    return _cutline_service


def get_catalog_store() -> CatalogStore:
    """提供当前应用进程使用的 V6 静态目录存储实例，供依赖注入调用。"""
    return _catalog_store


def get_state_store() -> AlgorithmStateStore:
    """提供当前应用进程使用的 V6 车间跨轮状态存储实例，供依赖注入调用。"""
    return _state_store


def _catalog_http_error(exc: CatalogStoreError) -> HTTPException:
    """按目录错误类型映射 422 数据错误或 409 版本、幂等冲突错误。"""
    status = 422 if exc.code == "STATIC_DATA_INVALID" else 409
    return HTTPException(
        status_code=status,
        detail={
            "code": http_error_code(exc.code),
            "legacy_code": exc.code,
            "message": str(exc),
            "retryable": status == 409,
        },
    )


def _catalog_response(record, store: CatalogStore) -> CatalogResponse:
    """将目录内部记录和当前可保留版本转换为公开的目录响应。"""
    return CatalogResponse(
        catalog_version=record.catalog_version,
        catalog_hash=record.catalog_hash,
        published_at=record.published_at,
        retained_versions=store.retained_versions(),
    )


def _raise_request_validation_error(
    exc: ValidationError | BackendRequestLoadError,
) -> NoReturn:
    """内部辅助步骤【_raise_request_validation_error】，为上层业务流程提供数据处理或共用判断。"""
    if isinstance(exc, ValidationError):
        raise HTTPException(
            status_code=422,
            detail={
                "code": http_error_code("REQUEST_VALIDATION_ERROR"),
                "legacy_code": "REQUEST_VALIDATION_ERROR",
                "message": "请求格式或字段类型错误",
                "issues": [
                    issue.model_dump(mode="json")
                    for issue in _pydantic_validation_issues(exc)
                ],
            },
        ) from exc
    raise HTTPException(
        status_code=422,
        detail={
            "code": http_error_code("REQUEST_VALIDATION_ERROR"),
            "legacy_code": "REQUEST_VALIDATION_ERROR",
            "message": "请求载荷标准化失败",
            "issues": [
                BackendValidationIssue(
                    code="load_error",
                    dataset="agv_relations",
                    field=None,
                    record_key=None,
                    message=str(exc),
                ).model_dump(mode="json")
            ],
        },
    ) from exc


def _load_cutline_request(payload: dict[str, Any]) -> CutlineAlgorithmRequest:
    """在後端输入与算法内部模型之间执行【_load_cutline_request】转换，并保留必要的校验信息。"""
    try:
        return _backend_loader.load_cutline_dict(payload)
    except (ValidationError, BackendRequestLoadError) as exc:
        _raise_request_validation_error(exc)


def _raise_backend_data_invalid(
    issues: list[BackendValidationIssue],
    *,
    cause: Exception | None = None,
) -> NoReturn:
    """内部辅助步骤【_raise_backend_data_invalid】，为上层业务流程提供数据处理或共用判断。"""
    http_error = HTTPException(
        status_code=422,
        detail={
            "code": http_error_code("BACKEND_DATA_INVALID"),
            "legacy_code": "BACKEND_DATA_INVALID",
            "message": "后端数据不完整或数据关联关系错误",
            "issues": [
                issue.model_dump(mode="json") for issue in issues
            ],
        },
    )
    if cause is not None:
        raise http_error from cause
    raise http_error


def _pydantic_validation_issues(
    exc: ValidationError,
) -> list[BackendValidationIssue]:
    """内部辅助步骤【_pydantic_validation_issues】，为上层业务流程提供数据处理或共用判断。"""
    issues: list[BackendValidationIssue] = []
    for error in exc.errors(include_url=False):
        location = list(error.get("loc", ()))
        dataset = str(location[0]) if location else "request"
        has_record_index = len(location) > 1 and isinstance(location[1], int)
        field_parts = location[2:] if has_record_index else location[1:]
        issues.append(
            BackendValidationIssue(
                code=str(error.get("type", "validation_error")),
                dataset=dataset,
                field=(
                    ".".join(str(item) for item in field_parts)
                    if field_parts
                    else None
                ),
                record_key=(
                    f"index:{location[1]}" if has_record_index else None
                ),
                message=str(error.get("msg", "request validation failed")),
            )
        )
    return issues


def _load_validated_cutline_request(
    payload: Any,
) -> CutlineAlgorithmRequest:
    """在後端输入与算法内部模型之间执行【_load_validated_cutline_request】转换，并保留必要的校验信息。"""
    try:
        request = _backend_loader.load_cutline_dict(payload)
    except ValidationError as exc:
        _raise_backend_data_invalid(
            _pydantic_validation_issues(exc),
            cause=exc,
        )
    except BackendRequestLoadError as exc:
        _raise_backend_data_invalid(
            [
                BackendValidationIssue(
                    code="load_error",
                    dataset="agv_relations",
                    field=None,
                    record_key=None,
                    message=str(exc),
                )
            ],
            cause=exc,
        )

    validation = _backend_validator.validate(request)
    if not validation.valid:
        _raise_backend_data_invalid(validation.issues)
    return request


@router.post("/backend/validate", response_model=BackendRequestValidationResult)
def validate_backend_request(
    payload: dict[str, Any] = Body(...),
) -> BackendRequestValidationResult:
    """校验【validate_backend_request】所需的数据和业务前置条件，失败时按本模块契约报告问题。"""
    try:
        request = _backend_loader.load_dict(payload)
    except (ValidationError, BackendRequestLoadError) as exc:
        _raise_request_validation_error(exc)
    return _backend_validator.validate(request)


@router.post("/stub/algo/run", response_model=CutlineAlgorithmResponse)
def run_stub_algorithm_request(
    payload: dict[str, Any] = Body(...),
    service: CutlineService = Depends(get_cutline_service),
) -> CutlineAlgorithmResponse:
    """执行【run_stub_algorithm_request】业务操作；参数、返回值和异常语义以类型标注及调用方契约为准。"""
    request = _load_cutline_request(payload)
    try:
        return service.evaluate_algorithm(request)
    except Exception:
        log_algorithm_exception("/stub/algo/run")
        raise

def evaluate_cutline_request(
    payload: Any = Body(None),
    service: CutlineService = Depends(get_cutline_service),
) -> CutlineEvaluateResponse:
    """根据当前快照和业务规则执行【evaluate_cutline_request】计算，返回类型标注所声明的结果。"""
    request = _load_validated_cutline_request(payload)
    try:
        return service.evaluate_algorithm(request)
    except Exception as exc:
        log_algorithm_exception("/cutline/evaluate")
        if isinstance(exc, SnapshotConversionError):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": http_error_code("SNAPSHOT_CONVERSION_FAILED"),
                    "legacy_code": "SNAPSHOT_CONVERSION_FAILED",
                    "message": str(exc),
                    "issues": [],
                },
            ) from exc
        raise
