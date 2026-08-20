"""In-memory versioned static catalog storage for the V6 protocol."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from threading import RLock
from typing import Any


DATASETS = (
    "machine_master",
    "machine_process_times",
    "workshops",
    "orders",
    "products",
    "process_routes",
    "buffer_master",
)

PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "machine_master": ("machine_code",),
    "machine_process_times": ("machine_code", "product_code"),
    "workshops": ("workshop_code",),
    "orders": ("order_code",),
    "products": ("product_code",),
    "process_routes": ("workshop_code", "process_code"),
    "buffer_master": ("buffer_code",),
}


class CatalogStoreError(ValueError):
    """A recoverable catalog publication error."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class CatalogRecord:
    catalog_version: str
    catalog: dict[str, list[dict[str, Any]]]
    catalog_hash: str
    published_at: datetime


class CatalogStore:
    """Thread-safe bounded catalog history with atomic publication."""

    def __init__(self, *, retention: int = 5, strict: bool = False):
        if retention < 1:
            raise ValueError("retention must be positive")
        self._retention = retention
        self._strict = strict
        self._versions: dict[str, CatalogRecord] = {}
        self._idempotency: dict[str, tuple[str, str, CatalogRecord]] = {}
        self._patch_idempotency: dict[str, str] = {}
        self._current_version: str | None = None
        self._lock = RLock()

    @staticmethod
    def hash_catalog(catalog: dict[str, Any]) -> str:
        payload = json.dumps(
            catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload).hexdigest()

    def publish(
        self,
        catalog_version: str,
        catalog: dict[str, list[dict[str, Any]]],
        idempotency_key: str,
    ) -> CatalogRecord:
        with self._lock:
            digest = self.hash_catalog(catalog)
            prior = self._idempotency.get(idempotency_key)
            if prior is not None:
                version, prior_hash, record = prior
                if version == catalog_version and prior_hash == digest:
                    return record
                raise CatalogStoreError(
                    "IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs"
                )
            self._validate_catalog(catalog)
            existing = self._versions.get(catalog_version)
            if existing is not None:
                if existing.catalog_hash == digest:
                    self._idempotency[idempotency_key] = (
                        catalog_version,
                        digest,
                        existing,
                    )
                    return existing
                raise CatalogStoreError(
                    "CATALOG_VERSION_CONFLICT", "catalog version has different content"
                )
            record = CatalogRecord(
                catalog_version=catalog_version,
                catalog=deepcopy(catalog),
                catalog_hash=digest,
                published_at=datetime.now(timezone.utc),
            )
            self._commit(record, idempotency_key)
            return record

    def patch(
        self,
        base_catalog_version: str,
        next_catalog_version: str,
        changes: dict[str, dict[str, list[dict[str, Any]] | list[dict[str, Any]]]],
        idempotency_key: str,
    ) -> CatalogRecord:
        with self._lock:
            patch_fingerprint = self.hash_catalog({
                "base_catalog_version": base_catalog_version,
                "next_catalog_version": next_catalog_version,
                "changes": changes,
            })
            prior = self._idempotency.get(idempotency_key)
            if prior is not None:
                version, _, record = prior
                if (
                    version == next_catalog_version
                    and self._patch_idempotency.get(idempotency_key)
                    == patch_fingerprint
                ):
                    return record
                raise CatalogStoreError(
                    "IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs"
                )
            base = self._versions.get(base_catalog_version)
            if base is None:
                raise CatalogStoreError(
                    "BASE_CATALOG_VERSION_NOT_FOUND", "base catalog was not retained"
                )
            if self._current_version != base_catalog_version:
                raise CatalogStoreError(
                    "BASE_CATALOG_VERSION_STALE", "base catalog is no longer current"
                )
            merged = deepcopy(base.catalog)
            try:
                for dataset, change in changes.items():
                    if dataset not in DATASETS:
                        raise KeyError(dataset)
                    records = {self._key(dataset, item): item for item in merged[dataset]}
                    for item in change.get("upserts", []):
                        records[self._key(dataset, item)] = deepcopy(item)
                    for key in change.get("deleted_keys", []):
                        records.pop(self._deleted_key(dataset, key), None)
                    merged[dataset] = list(records.values())
            except (KeyError, TypeError, AttributeError) as exc:
                raise CatalogStoreError("STATIC_DATA_INVALID", str(exc)) from exc
            record = self.publish(next_catalog_version, merged, idempotency_key)
            self._patch_idempotency[idempotency_key] = patch_fingerprint
            return record

    def get(self, catalog_version: str) -> CatalogRecord | None:
        with self._lock:
            record = self._versions.get(catalog_version)
            return deepcopy(record) if record is not None else None

    def current(self) -> CatalogRecord | None:
        with self._lock:
            return self.get(self._current_version) if self._current_version else None

    def retained_versions(self) -> list[str]:
        with self._lock:
            return list(self._versions)

    def _commit(self, record: CatalogRecord, idempotency_key: str) -> None:
        self._versions[record.catalog_version] = record
        self._current_version = record.catalog_version
        self._idempotency[idempotency_key] = (
            record.catalog_version,
            record.catalog_hash,
            record,
        )
        while len(self._versions) > self._retention:
            oldest = next(iter(self._versions))
            del self._versions[oldest]

    @staticmethod
    def _key(dataset: str, item: dict[str, Any]) -> tuple[Any, ...]:
        fields = PRIMARY_KEYS[dataset]
        if any(field not in item for field in fields):
            raise KeyError(f"{dataset} missing primary key")
        return tuple(item[field] for field in fields)

    @classmethod
    def _deleted_key(cls, dataset: str, item: Any) -> tuple[Any, ...]:
        if isinstance(item, dict):
            return cls._key(dataset, item)
        fields = PRIMARY_KEYS[dataset]
        if len(fields) == 1 and isinstance(item, str):
            return (item,)
        if isinstance(item, (list, tuple)) and len(item) == len(fields):
            return tuple(item)
        raise KeyError(f"invalid deleted key for {dataset}")

    def _validate_catalog(self, catalog: dict[str, Any]) -> None:
        if set(catalog) != set(DATASETS):
            raise CatalogStoreError("STATIC_DATA_INVALID", "catalog datasets must match V6")
        for dataset in DATASETS:
            records = catalog[dataset]
            if not isinstance(records, list):
                raise CatalogStoreError("STATIC_DATA_INVALID", f"{dataset} must be an array")
            seen: set[tuple[Any, ...]] = set()
            for item in records:
                if not isinstance(item, dict):
                    raise CatalogStoreError("STATIC_DATA_INVALID", f"{dataset} records must be objects")
                try:
                    key = self._key(dataset, item)
                except KeyError as exc:
                    raise CatalogStoreError("STATIC_DATA_INVALID", str(exc)) from exc
                if key in seen:
                    raise CatalogStoreError("STATIC_DATA_INVALID", f"duplicate {dataset} key")
                seen.add(key)
        if self._strict:
            try:
                from app.schemas.v6_schema import StaticCatalog

                StaticCatalog.model_validate(catalog)
            except Exception as exc:
                raise CatalogStoreError("STATIC_DATA_INVALID", str(exc)) from exc
