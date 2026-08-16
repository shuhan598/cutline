from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_runs_fastapi_on_port_8000_as_non_root_user():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.13-slim" in dockerfile
    assert "USER appuser" in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert 'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]' in dockerfile


def test_compose_exposes_service_and_checks_health_endpoint():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "cutline-algorithm:" in compose
    assert '"8000:8000"' in compose
    assert "restart: unless-stopped" in compose
    assert "http://127.0.0.1:8000/health" in compose


def test_compose_binds_configurable_host_exception_log_directory():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "volumes:" in compose
    assert "${CUTLINE_LOG_HOST_DIR:-./deploy/logs}:/app/logs" in compose


def test_dockerignore_excludes_local_artifacts_and_docs():
    ignored = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")
    for entry in ("__pycache__/", ".pytest_cache/", "docs/", "debug_outputs/"):
        assert entry in ignored
