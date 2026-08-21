"""将未捕获的算法异常追加写入独立日志文件，且不影响原异常传播。"""

import logging
import os
import time
from pathlib import Path
from threading import Lock


DEFAULT_LOG_DIRECTORY = Path("/app/logs")
_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.ERROR)
_LOGGER.propagate = False
_LOGGER_LOCK = Lock()


def log_algorithm_exception(request_path: str) -> None:
    """记录当前异常的完整堆栈，并保证日志失败不会覆盖业务异常。

    日志目录优先使用 ``CUTLINE_LOG_DIR`` 环境变量；每次调用临时挂载文件处理器，
    在锁内完成写入和移除，避免并发请求混用处理器或留下重复日志配置。
    """
    handler = None

    try:
        log_directory = Path(os.environ.get("CUTLINE_LOG_DIR") or DEFAULT_LOG_DIRECTORY)
        log_directory.mkdir(parents=True, exist_ok=True)

        handler = logging.FileHandler(
            log_directory / "algorithm-exceptions.log",
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s",
            "%Y-%m-%dT%H:%M:%SZ",
        )
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        with _LOGGER_LOCK:
            _LOGGER.addHandler(handler)
            try:
                _LOGGER.exception("Unhandled algorithm exception at %s", request_path)
            finally:
                _LOGGER.removeHandler(handler)
    except OSError:
        return
    finally:
        if handler is not None:
            try:
                handler.close()
            except OSError:
                pass
