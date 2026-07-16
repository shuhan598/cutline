import inspect
from importlib.machinery import PathFinder

import app.adapters
from app.adapters.snapshot_adapter import SnapshotAdapter
from app.schemas import common_schema, request_schema, response_schema, result_schema


LEGACY_COMMON_SCHEMA_NAMES = (
    "MachineRuntimeStatus",
    "MachineMaster",
    "LineMaster",
    "CycleMaster",
    "ProductModel",
    "ProcessRouteStep",
    "BufferSegment",
    "BufferServiceProcess",
    "BufferInventoryItem",
    "MachineCapacityRecord",
    "OrderInfo",
    "CutlineEvent",
)

LEGACY_REQUEST_SCHEMA_NAMES = (
    "CutlineSnapshot",
    "CutlineEvaluateRequest",
    "MixTraceRequest",
)

LEGACY_RESULT_SCHEMA_NAMES = (
    "NetRateResult",
    "DepletionResult",
    "StockoutWarningResult",
    "CandidateMachine",
    "CandidateResult",
    "OverflowTimeResult",
    "OverflowWarningResult",
    "PlanResult",
    "ManualInterventionResult",
    "ReturnResult",
    "SilkScreenOrderResult",
)

LEGACY_RESPONSE_SCHEMA_NAMES = (
    "WarningResult",
    "SelectedMachine",
    "CutlinePlan",
    "ManualIntervention",
    "ReturnSuggestion",
    "CutlineEvaluateResponse",
    "MixTraceNotification",
    "MixTraceResponse",
)

LEGACY_ALGORITHM_CONFIG_FIELDS = (
    "cutline_lead_minutes",
    "mix_basket_count",
    "basket_capacity",
    "max_feed_basket_count",
)


def test_legacy_schema_models_are_not_exposed():
    for module, names in (
        (common_schema, LEGACY_COMMON_SCHEMA_NAMES),
        (request_schema, LEGACY_REQUEST_SCHEMA_NAMES),
        (result_schema, LEGACY_RESULT_SCHEMA_NAMES),
        (response_schema, LEGACY_RESPONSE_SCHEMA_NAMES),
    ):
        assert not set(names).intersection(vars(module))


def test_algorithm_config_has_no_legacy_fields_or_validator():
    assert not set(LEGACY_ALGORITHM_CONFIG_FIELDS).intersection(
        common_schema.AlgorithmConfig.model_fields
    )
    assert not hasattr(
        common_schema.AlgorithmConfig,
        "populate_warning_leads_from_legacy",
    )


def test_snapshot_adapter_exposes_only_algorithm_conversion():
    assert "to_snapshot" not in vars(SnapshotAdapter)
    assert "to_algorithm_snapshot" in vars(SnapshotAdapter)
    assert tuple(inspect.signature(SnapshotAdapter.to_algorithm_snapshot).parameters) == (
        "self",
        "request",
    )


def test_legacy_mock_adapter_has_no_concrete_module():
    spec = PathFinder.find_spec("app.adapters.mock_adapter", app.adapters.__path__)

    assert spec is None or spec.loader is None
