"""切线算法服务入口：适配请求、执行管道并映射正式响应。"""

from typing import Optional

from app.adapters.snapshot_adapter import SnapshotAdapter
from app.mappers.algorithm_response_mapper import AlgorithmResponseMapper
from app.schemas.request_schema import CutlineAlgorithmRequest
from app.schemas.response_schema import CutlineEvaluateResponse
from app.service.cutline_pipeline import CutlinePipeline


class CutlineService:
    """对外统一入口：evaluate_algorithm(request) -> CutlineAlgorithmResponse。"""

    def __init__(
        self,
        pipeline: Optional[CutlinePipeline] = None,
        adapter: Optional[SnapshotAdapter] = None,
        mapper: Optional[AlgorithmResponseMapper] = None,
    ):
        """初始化【__init__】对象的状态、索引和依赖。"""
        self._pipeline = pipeline if pipeline is not None else CutlinePipeline()
        self._adapter = adapter if adapter is not None else SnapshotAdapter()
        self._mapper = mapper if mapper is not None else AlgorithmResponseMapper()

    def evaluate_algorithm(
        self,
        request: CutlineAlgorithmRequest,
    ) -> CutlineEvaluateResponse:
        """根据当前快照和业务规则执行【evaluate_algorithm】计算，返回类型标注所声明的结果。"""
        snapshot = self._adapter.to_algorithm_snapshot(request)
        result = self._pipeline.evaluate_algorithm(snapshot)
        return self._mapper.to_evaluate_response(result)
