# 把后端/甲方传来的现场快照 dict 转成标准 CutlineSnapshot 对象

from datetime import datetime

from app.schemas.request_schema import CutlineSnapshot


class SnapshotAdapter:
    """dict/JSON → CutlineSnapshot。换数据源时只动适配器,不动算法。"""

    def to_snapshot(self, payload: dict) -> CutlineSnapshot:
        data = dict(payload)
        data.setdefault("current_time", datetime.now())
        return CutlineSnapshot.model_validate(data)
