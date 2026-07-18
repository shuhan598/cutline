from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.adapters.backend_request_loader import BackendRequestLoader
from app.adapters.backend_request_validator import (
    BackendRequestCompletenessValidator,
    BackendRequestValidationResult,
)
from app.schemas.request_schema import CutlineAlgorithmRequest
from app.schemas.response_schema import CutlineAlgorithmResponse
from app.service.cutline_service import CutlineService


router = APIRouter(tags=["cutline"])

_backend_loader = BackendRequestLoader()
_backend_validator = BackendRequestCompletenessValidator()
_cutline_service = CutlineService()


def get_cutline_service() -> CutlineService:
    return _cutline_service


@router.post("/backend/validate", response_model=BackendRequestValidationResult)
def validate_backend_request(
    payload: dict[str, Any] = Body(...),
) -> BackendRequestValidationResult:
    try:
        request = _backend_loader.load_dict(payload)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    return _backend_validator.validate(request)


@router.post("/cutline/evaluate", response_model=CutlineAlgorithmResponse)
def evaluate_cutline_request(
    request: CutlineAlgorithmRequest,
    service: CutlineService = Depends(get_cutline_service),
) -> CutlineAlgorithmResponse:
    return service.evaluate_algorithm(request)
