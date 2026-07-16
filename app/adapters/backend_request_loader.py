from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.schemas.backend_request_schema import BackendAlgorithmRequest


class BackendRequestLoadError(ValueError):
    """Backend request JSON could not be read or parsed."""


class BackendRequestLoader:
    """Load backend request payloads into the strict external request model."""

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
                    record.pop("period_quantity", None)
                    record.pop("out_time", None)
        return BackendAlgorithmRequest.model_validate(cleaned)

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
