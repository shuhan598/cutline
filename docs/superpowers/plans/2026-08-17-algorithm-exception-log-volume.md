# Algorithm Exception Log Volume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist complete unexpected algorithm exception tracebacks to a Docker-mounted host directory without changing existing API responses.

**Architecture:** A focused utility resolves `CUTLINE_LOG_DIR` (defaulting to `/app/logs`) on every call and appends an exception record through the Python standard logging library. Both API endpoints wrap only `CutlineService.evaluate_algorithm()` and re-raise after logging, preserving the existing FastAPI error behavior. Docker Compose binds the container directory to a default repository path, with an environment-variable override for production servers.

**Tech Stack:** Python 3.13 standard-library logging, FastAPI, pytest, Docker Compose.

---

## File Structure

- Create: `app/utils/algorithm_exception_logger.py` - writes the active exception and traceback to the configured log file without masking it.
- Modify: `app/api/cutline_api.py` - wraps only the two algorithm service calls and delegates exception recording.
- Modify: `tests/api/test_fastapi_interfaces.py` - proves each algorithm endpoint remains a 500 while creating a traceback log record.
- Modify: `docker-compose.yml` - binds a configurable host log directory to `/app/logs`.
- Create: `deploy/logs/.gitkeep` - retains the default host bind-mount directory in the repository.
- Modify: `tests/deployment/test_container_contract.py` - verifies the new Compose deployment contract.
- Modify: `README.md` - documents default and server-specific log locations.

### Task 1: Record an active algorithm exception without hiding it

**Files:**
- Create: `app/utils/algorithm_exception_logger.py`
- Test: `tests/api/test_fastapi_interfaces.py`

- [ ] **Step 1: Write the failing unit-level logger test**

Add this import to `tests/api/test_fastapi_interfaces.py`:

```python
from app.utils.algorithm_exception_logger import log_algorithm_exception
```

Add this test near the existing API helper tests:

```python
def test_log_algorithm_exception_writes_active_traceback_to_configured_directory(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("CUTLINE_LOG_DIR", str(tmp_path))

    try:
        raise RuntimeError("algorithm exploded")
    except RuntimeError:
        log_algorithm_exception("/cutline/evaluate")

    content = (tmp_path / "algorithm-exceptions.log").read_text(
        encoding="utf-8"
    )
    assert "/cutline/evaluate" in content
    assert "RuntimeError: algorithm exploded" in content
    assert "Traceback (most recent call last):" in content
```

- [ ] **Step 2: Run the logger test to verify it fails because the utility does not exist**

Run: `pytest tests/api/test_fastapi_interfaces.py::test_log_algorithm_exception_writes_active_traceback_to_configured_directory -v`

Expected: FAIL during test collection with `ModuleNotFoundError: No module named 'app.utils.algorithm_exception_logger'`.

- [ ] **Step 3: Implement the smallest reusable logging utility**

Create `app/utils/algorithm_exception_logger.py` with:

```python
"""将算法调用链中的未处理异常持久化为可挂载的文本日志。"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path


_LOGGER = logging.getLogger("cutline.algorithm_exceptions")
_LOGGER.setLevel(logging.ERROR)
_LOGGER.propagate = False
_LOG_FILE_NAME = "algorithm-exceptions.log"


def log_algorithm_exception(request_path: str) -> None:
    """记录当前异常；日志故障不能覆盖原始算法异常。"""
    try:
        log_directory = Path(os.environ.get("CUTLINE_LOG_DIR", "/app/logs"))
        log_directory.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(
            log_directory / _LOG_FILE_NAME,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "%(asctime)sZ %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        _LOGGER.addHandler(handler)
        try:
            _LOGGER.exception("Unhandled algorithm exception at %s", request_path)
        finally:
            _LOGGER.removeHandler(handler)
            handler.close()
    except OSError:
        return
```

- [ ] **Step 4: Run the logger test to verify it passes**

Run: `pytest tests/api/test_fastapi_interfaces.py::test_log_algorithm_exception_writes_active_traceback_to_configured_directory -v`

Expected: PASS.

### Task 2: Preserve the two endpoint contracts while writing exception logs

**Files:**
- Modify: `app/api/cutline_api.py`
- Modify: `tests/api/test_fastapi_interfaces.py`
- Test: `tests/api/test_fastapi_interfaces.py`

- [ ] **Step 1: Write failing tests for both algorithm endpoints**

Add this helper and parameterized test to `tests/api/test_fastapi_interfaces.py`:

```python
class _FailingAlgorithmService:
    def evaluate_algorithm(self, request: CutlineAlgorithmRequest):
        raise RuntimeError("algorithm endpoint failure")


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/stub/algo/run", cutline_payload()),
        ("/cutline/evaluate", build_stockout_auto_payload()),
    ],
)
def test_algorithm_endpoint_logs_unexpected_exception_and_keeps_500(
    path: str,
    payload: dict,
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("CUTLINE_LOG_DIR", str(tmp_path))
    app = create_app()
    app.dependency_overrides[get_cutline_service] = _FailingAlgorithmService
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(path, json=payload)

    assert response.status_code == 500
    content = (tmp_path / "algorithm-exceptions.log").read_text(
        encoding="utf-8"
    )
    assert path in content
    assert "RuntimeError: algorithm endpoint failure" in content
    assert "Traceback (most recent call last):" in content
```

Replace the existing `test_cutline_evaluate_keeps_unknown_runtime_error_as_500` with this parameterized test so the behavior is covered once for each route.

- [ ] **Step 2: Run the endpoint test to verify it fails for the missing log file**

Run: `pytest tests/api/test_fastapi_interfaces.py::test_algorithm_endpoint_logs_unexpected_exception_and_keeps_500 -v`

Expected: FAIL with `FileNotFoundError` for `algorithm-exceptions.log`; the endpoints still return 500 before the API integration is added.

- [ ] **Step 3: Wrap only algorithm execution and re-raise**

Add this import to `app/api/cutline_api.py`:

```python
from app.utils.algorithm_exception_logger import log_algorithm_exception
```

Replace the body of `run_stub_algorithm_request` with:

```python
    request = _load_cutline_request(payload)
    try:
        return service.evaluate_algorithm(request)
    except Exception:
        log_algorithm_exception("/stub/algo/run")
        raise
```

Replace the algorithm call in `evaluate_cutline_request` with:

```python
    try:
        return service.evaluate_algorithm(request)
    except Exception as exc:
        log_algorithm_exception("/cutline/evaluate")
        if isinstance(exc, SnapshotConversionError):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "SNAPSHOT_CONVERSION_FAILED",
                    "message": str(exc),
                    "issues": [],
                },
            ) from exc
        raise
```

- [ ] **Step 4: Run endpoint and existing API tests to verify they pass**

Run: `pytest tests/api/test_fastapi_interfaces.py -v`

Expected: PASS, including both parameterized 500-response cases and all existing 422/success contract cases.

### Task 3: Bind the container log directory to the host filesystem

**Files:**
- Modify: `docker-compose.yml`
- Create: `deploy/logs/.gitkeep`
- Modify: `tests/deployment/test_container_contract.py`
- Test: `tests/deployment/test_container_contract.py`

- [ ] **Step 1: Write a failing Compose mount contract test**

Add this test to `tests/deployment/test_container_contract.py`:

```python
def test_compose_binds_configurable_host_exception_log_directory():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "volumes:" in compose
    assert "${CUTLINE_LOG_HOST_DIR:-./deploy/logs}:/app/logs" in compose
```

- [ ] **Step 2: Run the deployment test to verify it fails for the missing mount**

Run: `pytest tests/deployment/test_container_contract.py::test_compose_binds_configurable_host_exception_log_directory -v`

Expected: FAIL because `docker-compose.yml` does not yet define the required volume.

- [ ] **Step 3: Add the Compose volume and tracked default directory**

Add this sibling to `ports` under `services.cutline-algorithm` in `docker-compose.yml`:

```yaml
    volumes:
      - ${CUTLINE_LOG_HOST_DIR:-./deploy/logs}:/app/logs
```

Create the empty file `deploy/logs/.gitkeep`. The repository's existing `*.log` ignore rule keeps generated log files out of version control while preserving the default mount directory.

- [ ] **Step 4: Run the deployment tests to verify the container contract passes**

Run: `pytest tests/deployment/test_container_contract.py -v`

Expected: PASS.

### Task 4: Document and verify deployment behavior

**Files:**
- Modify: `README.md`
- Test: `tests/api/test_fastapi_interfaces.py`
- Test: `tests/deployment/test_container_contract.py`

- [ ] **Step 1: Add Docker log access documentation**

Append this section to `README.md` after the Docker startup instructions:

````markdown
### 算法异常日志

算法运行中出现未预期异常时，服务会将完整异常堆栈写入容器的
`/app/logs/algorithm-exceptions.log`。默认 Compose 配置会把该目录挂载到项目根目录的
`deploy/logs/algorithm-exceptions.log`。

在 Linux 服务器部署时，可在启动前指定服务器日志目录：

```sh
export CUTLINE_LOG_HOST_DIR=/var/log/cutline-algorithm
docker compose up --build -d
```

服务器目录需要允许容器内 `appuser` 写入。异常日志只记录接口路径和 Python 堆栈，
不记录请求体。
````

- [ ] **Step 2: Run targeted regression tests**

Run: `pytest tests/api/test_fastapi_interfaces.py tests/deployment/test_container_contract.py -v`

Expected: PASS with the exception-log and Docker mount contracts covered.

- [ ] **Step 3: Run the complete test suite**

Run: `pytest -q`

Expected: PASS with no test failures.

- [ ] **Step 4: Validate the rendered Compose configuration**

Run: `docker compose config`

Expected: exit code 0 and a rendered `volumes` entry that maps the default `deploy/logs` directory to `/app/logs`. If Docker CLI is unavailable in the current environment, report that limitation after the Python tests pass.
