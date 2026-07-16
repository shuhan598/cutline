import app.core.cutline_plan.plan_builder as plan_builder_module
from app.core.cutline_plan.plan_builder import CutlinePlanBuilder


def test_plan_builder_exposes_only_algorithm_decision_api():
    assert not hasattr(CutlinePlanBuilder, "build_stockout")
    assert not hasattr(CutlinePlanBuilder, "build_overflow")


def test_plan_builder_does_not_import_legacy_result_types():
    for legacy_name in (
        "DepletionResult",
        "ManualInterventionResult",
        "NetRateResult",
        "OverflowWarningResult",
        "PlanResult",
        "StockoutWarningResult",
    ):
        assert not hasattr(plan_builder_module, legacy_name)
