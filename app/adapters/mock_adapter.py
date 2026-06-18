# 本地测试用：读取 examples 下的假数据 JSON，复用 SnapshotAdapter 产出快照

import json
from pathlib import Path
from typing import Optional, Union

from app.adapters.snapshot_adapter import SnapshotAdapter
from app.schemas.request_schema import CutlineSnapshot


class MockAdapter:
    """examples JSON 文件 → CutlineSnapshot。"""

    def __init__(self, snapshot_adapter: Optional[SnapshotAdapter] = None):
        self._snapshot_adapter = snapshot_adapter or SnapshotAdapter()

    def load(self, path: Union[str, Path]) -> CutlineSnapshot:
        with Path(path).open(encoding="utf-8") as file:
            payload = json.load(file)
        return self._snapshot_adapter.to_snapshot(payload)
