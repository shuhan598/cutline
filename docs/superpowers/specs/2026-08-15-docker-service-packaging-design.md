# 切线算法 Docker 服务化设计

## 目标

将现有切线算法 FastAPI 应用封装为可独立构建和启动的 Docker 服务。容器启动后对外提供 HTTP API，并为以后增加业务路由保留稳定的运行方式。

## 范围

- 提供 Python 3.13 slim 基础镜像的 `Dockerfile`。
- 使用 Uvicorn 启动 `app.main:app`，监听容器内 `8000` 端口。
- 提供 `docker-compose.yml`，将宿主机 `8000` 映射到容器服务，并配置服务重启与健康检查。
- 提供 `.dockerignore`，排除 Python 缓存、测试缓存、虚拟环境、文档和本地调试输出。
- 在 README 中记录构建、启动、停止和存活检查命令。

不引入反向代理、HTTPS 终止、数据库或额外运行时组件。

## 架构与数据流

`docker compose up --build` 启动一个 `cutline-algorithm` 服务。Docker Compose 将宿主机 8000 端口转发至容器的 Uvicorn 进程；Uvicorn 加载现有 `app.main:app`，由 FastAPI 继续分发 `/health`、`/backend/validate`、`/stub/algo/run` 和 `/cutline/evaluate` 等路由。

健康检查通过容器内 `GET /health` 验证服务存活。新增 FastAPI 路由仅修改 Python 应用代码，不改变镜像入口或 Compose 配置。

## 运行与安全约束

镜像安装 `requirements.txt` 中的生产依赖；运行时不复制本地缓存或测试输出。容器使用非 root 用户执行 Uvicorn，并开启 `PYTHONDONTWRITEBYTECODE` 与 `PYTHONUNBUFFERED`。本阶段不将源码目录挂载进容器，以确保启动的是镜像中构建的版本。

## 验证

测试将先覆盖 Compose 文件、Dockerfile 的入口命令及忽略规则这些可静态验证的部署契约。随后运行现有 pytest 测试套件。若本机可用 Docker，再构建镜像、启动 Compose 服务并请求 `/health`；当前环境尚未检测到 Docker CLI，因此该项验证可能需要在安装 Docker 后执行。
