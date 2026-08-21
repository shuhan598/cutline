"""将 V6 静态目录与动态快照组合为既有算法内部请求模型。

V6 传输层不重复携带静态主数据，内部算法仍依赖完整请求。因此适配器负责将目录
记录注入动态快照，并把 V6 AGV 的外部字段名转换为内部统一字段名。
"""

from __future__ import annotations

from app.schemas.request_schema import CutlineAlgorithmRequest
from app.schemas.v6_schema import V6EvaluateRequest
from app.service.catalog_store import CatalogRecord


class V6RequestAdapter:
    """执行 V6 请求到 ``CutlineAlgorithmRequest`` 的无状态转换。"""
    def to_internal(
        self, request: V6EvaluateRequest, catalog: CatalogRecord
    ) -> CutlineAlgorithmRequest:
        """合并已解析目录和动态数据，并进行最终内部模型校验。

        目录版本必须与请求声明一致；产线和机台产线信息在 V6 中不再传输，因此
        显式传入空列表。AGV 关系字段在此处改名，后续核心算法无需感知 V6 协议。
        """
        if request.catalog_version != catalog.catalog_version:
            raise ValueError("catalog version does not match resolved catalog")
        meta = request.snapshot_meta.model_dump()
        meta.update(
            catalog_version=catalog.catalog_version,
            catalog_loaded_at=catalog.published_at,
        )
        dynamic = request.dynamic
        # V6 沿用后端 AGV 字段名，内部模型使用与其他数据源一致的语义字段名。
        agv = [
            {
                "machine_code": item.equipmentid,
                "machine_name": item.equipmentname,
                "product_name": item.linename,
                "previous_product_name": item.lastlinename,
                "wafer_spec": item.waferspec,
                "binding_time": item.createtime,
            }
            for item in dynamic.agv_relations
        ]
        payload = {
            "snapshot_meta": meta,
            "machine_realtime": [item.model_dump() for item in dynamic.machine_realtime],
            "machine_master": catalog.catalog["machine_master"],
            "machine_process_times": catalog.catalog["machine_process_times"],
            "workshops": catalog.catalog["workshops"],
            "lines": [],
            "machine_lines": [],
            "orders": catalog.catalog["orders"],
            "products": catalog.catalog["products"],
            "process_routes": catalog.catalog["process_routes"],
            "buffer_realtime": [item.model_dump() for item in dynamic.buffer_realtime],
            "buffer_master": catalog.catalog["buffer_master"],
            "agv_relations": agv,
        }
        return CutlineAlgorithmRequest.model_validate(payload)

