# 算法异常日志与 Docker 挂载设计

## 目标

当切线算法执行出现未预期异常时，服务必须记录完整 Python 异常堆栈，并让日志在 Docker 容器外的宿主机目录中可直接访问。

## 范围

- 仅包裹两个会调用 `CutlineService.evaluate_algorithm()` 的算法 HTTP 接口：`POST /stub/algo/run` 和 `POST /cutline/evaluate`。
- 为每次未预期异常追加一条包含 UTC 时间、请求路径、异常类型、异常消息及完整 traceback 的文本日志。
- 容器内日志目录固定为 `/app/logs`，日志文件固定为 `algorithm-exceptions.log`。
- Docker Compose 默认将项目中的 `deploy/logs` 绑定到 `/app/logs`；部署服务器可通过 `CUTLINE_LOG_HOST_DIR` 指定绝对宿主机目录。

不记录请求体，不改变成功响应、已有 422 业务错误，且不增加日志轮转或外部日志系统。

## 架构

新增一个小型日志写入组件，使用标准库 `logging` 将异常记录写到由 `CUTLINE_LOG_DIR` 环境变量指定的目录，默认 `/app/logs`。组件在首次使用时创建目录和文件处理器，并用 `logger.exception()` 保留当前异常堆栈。

API 层在 `service.evaluate_algorithm()` 周围使用 `try/except Exception`。捕获后记录接口路径，再原样重新抛出异常；现有 FastAPI 异常处理继续产生原有 HTTP 状态和响应。`/cutline/evaluate` 已有的 `SnapshotConversionError` 分支仍转换为 422，但也会在捕获点留下堆栈记录，因为它来自算法调用链。

## 部署契约

`docker-compose.yml` 将定义：

```yaml
volumes:
  - ${CUTLINE_LOG_HOST_DIR:-./deploy/logs}:/app/logs
```

不设置变量时，宿主机目录为项目根目录下的 `deploy/logs`。在 Linux 服务器上可以在启动前设置：

```sh
export CUTLINE_LOG_HOST_DIR=/var/log/cutline-algorithm
```

Compose 会在默认绑定目录不存在时创建它；仓库保留 `deploy/logs/.gitkeep` 以使默认路径可见。`.gitignore` 会排除运行生成的 `.log` 文件。

## 测试

- API 测试将以抛出 `RuntimeError` 的服务替身驱动两个算法接口，断言响应仍为 500，日志文件包含异常消息和 traceback。
- 部署契约测试将断言 Compose 包含容器路径、默认 `./deploy/logs` 路径和 `CUTLINE_LOG_HOST_DIR` 覆盖变量。
- 执行相关测试与完整 `pytest -q` 回归。

## 边界和安全性

日志只包含技术异常上下文和请求路径，不写入可能含生产业务数据的请求体。文件目录由 Compose 的可写宿主机绑定卷提供，Dockerfile 的 `appuser` 仍以非 root 运行。若日志写入失败，记录失败不得掩盖原算法异常。
