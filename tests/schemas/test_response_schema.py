from datetime import datetime

from app.schemas.response_schema import (
    CutlinePlan,
    ManualIntervention,
    MixTraceNotification,
    ReturnSuggestion,
    SelectedMachine,
    WarningResult,
)


def _warning(**updates):
    payload = {
        "warning_time": datetime(2026, 6, 20, 9, 30, 0),
        "warning_type": "stockout",
        "buffer_code": "BUF",
        "upstream_process_code": "ZR",
        "downstream_process_code": "PK",
        "product_code": "HG182T",
    }
    payload.update(updates)
    return WarningResult(**payload)


def _return_suggestion(**updates):
    payload = {
        "suggestion_time": datetime(2026, 6, 20, 11, 0, 0),
        "equipment_code": "zr03",
        "product_code": "HG182T",
    }
    payload.update(updates)
    return ReturnSuggestion(**payload)


def _mix_notification(**updates):
    payload = {
        "source_equipment_code": "pk03",
        "cut_time": datetime(2026, 6, 20, 10, 0, 0),
        "previous_product_code": "HG210R",
        "next_product_code": "HG182T",
        "mix_start_time": datetime(2026, 6, 20, 11, 12, 30),
        "mix_basket_count": 2,
        "estimated_total_quantity": 240,
    }
    payload.update(updates)
    return MixTraceNotification(**payload)


def test_response_models_accept_workshop_fields():
    warning = _warning(workshop_code="S2", workshop_name="S2车间")
    selected_machine = SelectedMachine(
        equipment_code="zr03",
        workshop_code="S2",
        workshop_name="S2车间",
    )
    plan = CutlinePlan(
        plan_id="plan-1",
        workshop_code="S2",
        workshop_name="S2车间",
        warning=warning,
    )
    manual = ManualIntervention(
        intervention_id="manual-1",
        workshop_code="S2",
        workshop_name="S2车间",
        warning=warning,
        reason="no_candidate",
    )
    return_suggestion = _return_suggestion(workshop_code="S2", workshop_name="S2车间")
    mix_notification = _mix_notification(workshop_code="S2", workshop_name="S2车间")

    for model in [
        warning,
        selected_machine,
        plan,
        manual,
        return_suggestion,
        mix_notification,
    ]:
        assert model.workshop_code == "S2"
        assert model.workshop_name == "S2车间"


def test_response_model_workshop_fields_default_to_none():
    warning = _warning()
    selected_machine = SelectedMachine(equipment_code="zr03")
    plan = CutlinePlan(warning=warning)
    manual = ManualIntervention(warning=warning, reason="no_candidate")
    return_suggestion = _return_suggestion()
    mix_notification = _mix_notification()

    for model in [
        warning,
        selected_machine,
        plan,
        manual,
        return_suggestion,
        mix_notification,
    ]:
        assert model.workshop_code is None
        assert model.workshop_name is None
