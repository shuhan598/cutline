# Docker 服务化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将切线算法 FastAPI 应用交付为可由 Docker Compose 构建、启动并通过健康检查验证的服务镜像。

**Architecture:** Dockerfile 基于 Python 3.13 slim，先安装 `requirements.txt` 再复制应用源码，并以非 root 用户启动 Uvicorn。Docker Compose 只编排一个应用服务，将 8000 端口暴露给宿主机，并使用应用已有的 `/health` 路由检查容器状态。

**Tech Stack:** Python 3.13、FastAPI、Uvicorn、pytest、Docker、Docker Compose。

---

## 文件结构

- Create: `Dockerfile` — 生产镜像的构建步骤和 Uvicorn 入口。
- Create: `docker-compose.yml` — 本地/部署启动服务、端口映射、重启策略和健康检查。
- Create: `.dockerignore` — 从镜像构建上下文排除本地缓存、测试产物和文档。
- Create: `tests/deployment/__init__.py` — 部署契约测试包。
- Create: `tests/deployment/test_container_contract.py` — 静态验证容器配置和现有健康端点的测试。
- Modify: `README.md` — 增加 Docker 构建、启动、停止和健康检查的操作说明。

### Task 1: 建立容器配置的部署契约测试

**Files:**
- Create: `tests/deployment/__init__.py`
- Create: `tests/deployment/test_container_contract.py`

- [ ] **Step 1: 写入会失败的 Docker 配置契约测试**

```python
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


def test_dockerignore_excludes_local_artifacts_and_docs():
    ignored = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")

    for entry in ("__pycache__/", ".pytest_cache/", "docs/", "debug_outputs/"):
        assert entry in ignored
```

- [ ] **Step 2: 运行测试，确认因配置文件尚不存在而失败**

Run: `pytest tests/deployment/test_container_contract.py -v`

Expected: FAIL，提示找不到尚未创建的 `Dockerfile`、`docker-compose.yml` 和 `.dockerignore`。

- [ ] **Step 3: 保持测试文件最小化**

`tests/deployment/__init__.py` 内容为空；不引入 YAML 解析库。测试仅断言部署所需的、稳定的文本契约，避免把格式化细节纳入约束。

- [ ] **Step 4: 再次运行测试，确认仍是预期的失败原因**

Run: `pytest tests/deployment/test_container_contract.py -v`

Expected: FAIL，且失败原因仍为三个配置文件不存在，而不是测试导入错误。

### Task 2: 添加安全的 FastAPI 服务镜像与 Compose 编排

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`
- Test: `tests/deployment/test_container_contract.py`

- [ ] **Step 1: 创建最小生产 Dockerfile**

```dockerfile
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home --shell /usr/sbin/nologin appuser
COPY app ./app
RUN chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: 创建单服务 Compose 配置**

```yaml
services:
  cutline-algorithm:
    build:
      context: .
    ports:
      - "8000:8000"
    restart: unless-stopped
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

- [ ] **Step 3: 创建 Docker 构建上下文忽略规则**

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
venv/
docs/
tests/
examples/
debug_outputs/
.git/
```

- [ ] **Step 4: 运行部署契约测试，确认配置满足服务约定**

Run: `pytest tests/deployment/test_container_contract.py -v`

Expected: PASS，3 项部署契约测试全部通过。

### Task 3: 补充可操作的部署说明

**Files:**
- Modify: `README.md`
- Test: `tests/deployment/test_container_contract.py`

- [ ] **Step 1: 在 README 末尾添加 Docker 运行章节**

````markdown
## Docker 运行

需要已安装 Docker Desktop（包含 Docker Compose）。在项目根目录执行：

```bash
docker compose up --build -d
```

服务启动后访问 `http://localhost:8000/health`，预期返回 `{"status":"ok"}`。

查看服务状态：

```bash
docker compose ps
```

停止并移除服务容器：

```bash
docker compose down
```
````

- [ ] **Step 2: 执行静态部署契约测试**

Run: `pytest tests/deployment/test_container_contract.py -v`

Expected: PASS，3 项测试全部通过。

### Task 4: 回归验证与容器冒烟测试

**Files:**
- Test: `tests/`

- [ ] **Step 1: 运行全部 Python 测试**

Run: `pytest -q`

Expected: PASS，现有算法测试与新增部署契约测试全部通过。

- [ ] **Step 2: 在可用 Docker 环境构建并启动服务**

Run: `docker compose up --build -d`

Expected: Compose 成功创建 `cutline-algorithm` 容器。

- [ ] **Step 3: 请求健康检查并检查 Compose 状态**

Run: `Invoke-WebRequest -UseBasicParsing http://localhost:8000/health | Select-Object -ExpandProperty Content; docker compose ps`

Expected: 第一条命令输出 `{"status":"ok"}`；Compose 状态显示服务为 running 或 healthy。

- [ ] **Step 4: 停止本地冒烟测试服务**

Run: `docker compose down`

Expected: Compose 停止并移除本次验证创建的容器与网络。

当前工作目录没有 `.git`，因此本计划不包含 Git 提交步骤；若项目随后初始化为 Git 仓库，应在每个已验证任务后创建独立提交。
