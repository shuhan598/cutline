from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.cutline_api import evaluate_cutline_request
from app.main import create_app
from app.schemas.response_schema import CutlineEvaluateResponse


LEGACY_EVALUATE_TEST_PATH = "/_test/legacy-cutline-evaluate"


class LegacyEvaluateTestClient(TestClient):
    """Redirect legacy evaluate calls without changing the production app."""

    def request(self, method, url, **kwargs):
        if url == "/cutline/evaluate":
            url = LEGACY_EVALUATE_TEST_PATH
        return super().request(method, url, **kwargs)


def create_legacy_evaluate_test_app() -> FastAPI:
    """Expose the unregistered legacy handler only inside legacy contract tests."""
    app = create_app()
    app.add_api_route(
        LEGACY_EVALUATE_TEST_PATH,
        evaluate_cutline_request,
        methods=["POST"],
        response_model=CutlineEvaluateResponse,
        include_in_schema=False,
    )
    return app
