from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.adapters.backend_request_loader import (
    BackendRequestLoadError,
    BackendRequestLoader,
)
from app.adapters.backend_request_validator import (
    BackendRequestCompletenessValidator,
    BackendRequestValidationResult,
)
from app.schemas.request_schema import CutlineAlgorithmRequest
from app.schemas.response_schema import (
    CutlineAlgorithmResponse,
    CutlineEvaluateResponse,
)
from app.service.cutline_service import CutlineService


router = APIRouter(tags=["cutline"])

_backend_loader = BackendRequestLoader()
_backend_validator = BackendRequestCompletenessValidator()
_cutline_service = CutlineService()


def get_cutline_service() -> CutlineService:
    return _cutline_service


def _raise_request_validation_error(
    exc: ValidationError | BackendRequestLoadError,
) -> NoReturn:
    if isinstance(exc, ValidationError):
        raise RequestValidationError(exc.errors()) from exc
    raise HTTPException(
        status_code=422,
        detail=[
            {
                "type": "value_error",
                "loc": ["body", "agv_relations"],
                "msg": str(exc),
            }
        ],
    ) from exc


def _load_cutline_request(payload: dict[str, Any]) -> CutlineAlgorithmRequest:
    try:
        return _backend_loader.load_cutline_dict(payload)
    except (ValidationError, BackendRequestLoadError) as exc:
        _raise_request_validation_error(exc)


@router.post("/backend/validate", response_model=BackendRequestValidationResult)
def validate_backend_request(
    payload: dict[str, Any] = Body(...),
) -> BackendRequestValidationResult:
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
    return service.evaluate_algorithm(_load_cutline_request(payload))

@router.post("/cutline/evaluate", response_model=CutlineEvaluateResponse)
def evaluate_cutline_request(
    payload: dict[str, Any] = Body(...),
    service: CutlineService = Depends(get_cutline_service),
) -> CutlineEvaluateResponse:
    return service.evaluate_algorithm(_load_cutline_request(payload))

