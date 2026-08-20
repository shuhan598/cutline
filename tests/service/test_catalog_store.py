import pytest

from app.service.catalog_store import (
    CatalogStore,
    CatalogStoreError,
)


def catalog(**overrides):
    value = {
        "machine_master": [{"machine_code": "M1"}],
        "machine_process_times": [],
        "workshops": [{"workshop_code": "W1"}],
        "orders": [],
        "products": [],
        "process_routes": [],
        "buffer_master": [],
    }
    value.update(overrides)
    return value


def test_publish_is_idempotent_and_hash_is_stable():
    store = CatalogStore()
    first = store.publish("v1", catalog(), "key-1")
    retry = store.publish("v1", catalog(), "key-1")
    assert retry == first
    assert first.catalog_hash.startswith("sha256:")
    assert store.get("v1").catalog["machine_master"][0]["machine_code"] == "M1"


def test_reused_key_and_version_conflicts_are_rejected():
    store = CatalogStore()
    store.publish("v1", catalog(), "key-1")
    with pytest.raises(CatalogStoreError, match="IDEMPOTENCY_KEY_REUSED"):
        store.publish("v2", catalog(), "key-1")
    with pytest.raises(CatalogStoreError, match="CATALOG_VERSION_CONFLICT"):
        store.publish("v1", catalog(machine_master=[{"machine_code": "M2"}]), "key-2")


def test_patch_upserts_and_explicit_deletes_create_new_version():
    store = CatalogStore()
    store.publish("v1", catalog(), "key-1")
    result = store.patch(
        "v1",
        "v2",
        {"machine_master": {"upserts": [{"machine_code": "M2"}], "deleted_keys": [{"machine_code": "M1"}]}},
        "key-2",
    )
    assert result.catalog_version == "v2"
    assert store.get("v2").catalog["machine_master"] == [{"machine_code": "M2"}]


def test_invalid_patch_does_not_replace_current_catalog():
    store = CatalogStore()
    store.publish("v1", catalog(), "key-1")
    with pytest.raises(CatalogStoreError, match="STATIC_DATA_INVALID"):
        store.patch("v1", "v2", {"unknown": {"upserts": [], "deleted_keys": []}}, "key-2")
    assert store.current().catalog_version == "v1"


def test_patch_reusing_key_with_different_changes_is_rejected():
    store = CatalogStore()
    store.publish("v1", catalog(), "key-1")
    store.patch("v1", "v2", {"orders": {"upserts": [], "deleted_keys": []}}, "key-2")
    with pytest.raises(CatalogStoreError, match="IDEMPOTENCY_KEY_REUSED"):
        store.patch(
            "v1", "v2",
            {"orders": {"upserts": [{"order_code": "O1"}], "deleted_keys": []}},
            "key-2",
        )
