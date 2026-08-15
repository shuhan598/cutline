"""加载后端原始载荷，并转换为可校验的后端请求模型。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.adapters.agv_binding_selector import normalize_local_time
from app.schemas.backend_request_schema import BackendAlgorithmRequest
from app.schemas.request_schema import CutlineAlgorithmRequest


_RAW_AGV_FIELD_MAP = {
    "equipmentid": "machine_code",
    "equipmentname": "machine_name",
    "linename": "product_name",
    "lastlinename": "previous_product_name",
    "waferspec": "wafer_spec",
    "createtime": "binding_time",
}
_DATETIME_ADAPTER = TypeAdapter(datetime)


class BackendRequestLoadError(ValueError):
    """后端请求 JSON 无法读取或解析。"""


class BackendRequestLoader:
    """把后端请求载荷加载为严格的外部请求模型。"""

    @staticmethod
    def _is_raw_agv_record(record: dict[str, Any]) -> bool:
        return any(field in record for field in _RAW_AGV_FIELD_MAP)

    @staticmethod
    def _normalize_agv_record(
        record: dict[str, Any],
        index: int,
    ) -> dict[str, Any]:
        if not BackendRequestLoader._is_raw_agv_record(record):
            return record

        normalized: dict[str, Any] = {}
        for raw_field, standard_field in _RAW_AGV_FIELD_MAP.items():
            has_raw = raw_field in record
            has_standard = standard_field in record
            if (
                has_raw
                and has_standard
                and not BackendRequestLoader._agv_values_match(
                    raw_field,
                    record[raw_field],
                    record[standard_field],
                )
            ):
                raise BackendRequestLoadError(
                    f"agv_relations[{index}] field conflict: "
                    f"{raw_field}={record[raw_field]!r} does not match "
                    f"{standard_field}={record[standard_field]!r}"
                )
            if has_standard:
                normalized[standard_field] = record[standard_field]
            elif has_raw:
                normalized[standard_field] = record[raw_field]
        return normalized

    @staticmethod
    def _agv_values_match(
        raw_field: str,
        raw_value: Any,
        standard_value: Any,
    ) -> bool:
        if raw_field != "createtime":
            return raw_value == standard_value
        try:
            raw_time = _DATETIME_ADAPTER.validate_python(raw_value)
            standard_time = _DATETIME_ADAPTER.validate_python(standard_value)
        except ValidationError:
            return raw_value == standard_value
        return normalize_local_time(raw_time) == normalize_local_time(
            standard_time
        )

    def normalize_agv_relations(self, records: Any) -> Any:
        """映射原始 AGV 记录，同时保留非列表结构的 schema 错误。"""
        if not isinstance(records, list):
            return records
        return [
            self._normalize_agv_record(record, index)
            if isinstance(record, dict)
            else record
            for index, record in enumerate(records)
        ]

    def normalize_payload(self, payload: Any) -> Any:
        """深复制请求，并且只映射其中的 AGV 输入集合。"""
        normalized = deepcopy(payload)
        if isinstance(normalized, dict) and "agv_relations" in normalized:
            normalized["agv_relations"] = self.normalize_agv_relations(
                normalized["agv_relations"]
            )
        return normalized

    @staticmethod
    def _project_raw_agv_relations(records: Any) -> Any:
        if not isinstance(records, list):
            return records

        projected: list[Any] = []
        for index, record in enumerate(records):
            if (
                not isinstance(record, dict)
                or not BackendRequestLoader._is_raw_agv_record(record)
            ):
                projected.append(record)
                continue
            normalized = BackendRequestLoader._normalize_agv_record(
                record,
                index,
            )
            projected.append(
                {
                    raw_field: normalized[standard_field]
                    for raw_field, standard_field in _RAW_AGV_FIELD_MAP.items()
                    if standard_field in normalized
                }
            )
        return projected

    def load_dict(self, payload: dict[str, Any]) -> BackendAlgorithmRequest:
        cleaned = deepcopy(payload)
        machine_realtime = (
            cleaned.get("machine_realtime")
            if isinstance(cleaned, dict)
            else None
        )
        if isinstance(machine_realtime, list):
            for record in machine_realtime:
                if isinstance(record, dict):
                    record.pop("out_time", None)
        if isinstance(cleaned, dict) and "agv_relations" in cleaned:
            cleaned["agv_relations"] = self._project_raw_agv_relations(
                cleaned["agv_relations"]
            )
        return BackendAlgorithmRequest.model_validate(cleaned)

    def load_cutline_dict(
        self,
        payload: Any,
    ) -> CutlineAlgorithmRequest:
        return CutlineAlgorithmRequest.model_validate(
            self.normalize_payload(payload)
        )

    def load_json_file(self, file_path: str | Path) -> BackendAlgorithmRequest:
        path = Path(file_path)
        try:
            with path.open(encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackendRequestLoadError(
                f"Failed to load backend request JSON from {path}: {exc}"
            ) from exc
        return self.load_dict(payload)
