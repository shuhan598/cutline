"""Adapt strict V6 wire requests to the existing internal request model."""

from __future__ import annotations

from app.schemas.request_schema import CutlineAlgorithmRequest
from app.schemas.v6_schema import V6EvaluateRequest
from app.service.catalog_store import CatalogRecord


class V6RequestAdapter:
    def to_internal(
        self, request: V6EvaluateRequest, catalog: CatalogRecord
    ) -> CutlineAlgorithmRequest:
        if request.catalog_version != catalog.catalog_version:
            raise ValueError("catalog version does not match resolved catalog")
        meta = request.snapshot_meta.model_dump()
        meta.update(
            catalog_version=catalog.catalog_version,
            catalog_loaded_at=catalog.published_at,
        )
        dynamic = request.dynamic
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

