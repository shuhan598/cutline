"""保存 V6 静态目录的内存版历史，并提供原子发布和增量合并能力。

目录中的机台、订单、工艺路线等数据不随每次计算发送。调用方先发布完整目录，
之后动态快照只携带版本号。本存储组件保留有限版本、验证数据集主键，并依据
幂等键防止网络重试造成重复发布或内容冲突。
"""

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
    """表示调用方可修正后重试的目录发布或更新错误。"""

    def __init__(self, code: str, message: str):
        """保存机器可读错误码，同时保留适合日志记录的异常文本。"""
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class CatalogRecord:
    """一个已发布目录版本的不可变元数据和深拷贝数据快照。"""
    catalog_version: str
    catalog: dict[str, list[dict[str, Any]]]
    catalog_hash: str
    published_at: datetime


class CatalogStore:
    """线程安全的有限目录历史存储，发布和更新均以原子方式完成。"""

    def __init__(self, *, retention: int = 5, strict: bool = False):
        """初始化存储。

        ``retention`` 控制保留的最近版本数量；``strict`` 为真时还会使用
        Pydantic V6 模型进行字段级校验，默认只执行数据集和主键完整性校验。
        """
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
        """基于稳定 JSON 序列化计算目录内容哈希，用于幂等与版本冲突判断。"""
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
        """发布完整静态目录，并返回已保留的目录记录。

        同一幂等键、版本和内容的重试直接复用已有记录；同一版本只能对应一种
        内容。目录记录和入参均使用深拷贝，防止调用方随后修改对象影响已发布数据。
        """
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
        """在当前基准目录上应用各数据集的新增、覆盖和删除操作。

        仅允许从当前版本派生，避免并发客户端在过期目录上发布分叉版本。合并完成
        后复用 ``publish`` 的完整校验、幂等与保留策略。
        """
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
            # 在副本上构造完整新目录；任何校验失败都不会污染基准版本。
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
        """按版本获取目录副本；未保留时返回 ``None``。"""
        with self._lock:
            record = self._versions.get(catalog_version)
            return deepcopy(record) if record is not None else None

    def current(self) -> CatalogRecord | None:
        """获取当前生效目录的副本；尚未发布任何目录时返回 ``None``。"""
        with self._lock:
            return self.get(self._current_version) if self._current_version else None

    def retained_versions(self) -> list[str]:
        """按发布顺序返回当前仍可用于动态评估的目录版本。"""
        with self._lock:
            return list(self._versions)

    def _commit(self, record: CatalogRecord, idempotency_key: str) -> None:
        """提交已验证目录并淘汰最早的超额历史版本。"""
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
        """按数据集定义的主键字段生成不可变键，用于去重和更新定位。"""
        fields = PRIMARY_KEYS[dataset]
        if any(field not in item for field in fields):
            raise KeyError(f"{dataset} missing primary key")
        return tuple(item[field] for field in fields)

    @classmethod
    def _deleted_key(cls, dataset: str, item: Any) -> tuple[Any, ...]:
        """将删除请求中的对象、单键字符串或复合键序列归一为主键元组。"""
        if isinstance(item, dict):
            return cls._key(dataset, item)
        fields = PRIMARY_KEYS[dataset]
        if len(fields) == 1 and isinstance(item, str):
            return (item,)
        if isinstance(item, (list, tuple)) and len(item) == len(fields):
            return tuple(item)
        raise KeyError(f"invalid deleted key for {dataset}")

    def _validate_catalog(self, catalog: dict[str, Any]) -> None:
        """校验目录数据集集合、记录类型及各数据集内主键唯一性。"""
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
