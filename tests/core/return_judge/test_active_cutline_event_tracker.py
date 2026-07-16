from datetime import datetime
import importlib

import pytest
from pydantic import ValidationError

from app.schemas import common_schema
from app.schemas.request_schema import AlgorithmSnapshot
from tests.core.return_judge.helpers import (
    CUTLINE_START_TIME,
    active_event,
    algorithm_snapshot,
)


def _tracker(event_id_factory=None):
    module = importlib.import_module(
        "app.core.return_judge.active_cutline_event_tracker"
    )
    return module.ActiveCutlineEventTracker(event_id_factory=event_id_factory)


def _create_event(tracker, *, event_id=None):
    kwargs = dict(
        plan_id="PLAN-01",
        machine_code="MC-01",
        source_order_code="ORD-SOURCE",
        target_order_code="ORD-TARGET",
        workshop_code="WS-01",
        source_buffer_code="BUF-SOURCE",
        target_buffer_code="BUF-TARGET",
        upstream_process_code="P01",
        downstream_process_code="P02",
        source_wafer_size="182",
        source_wafer_spec="R",
        target_wafer_size="182",
        target_wafer_spec="N",
        cutline_start_time=CUTLINE_START_TIME,
        contribution_capacity=8000,
        warning_type="stockout",
    )
    if event_id is not None:
        kwargs["event_id"] = event_id
    return tracker.create_event(**kwargs)


def test_algorithm_snapshot_uses_new_active_event_type_and_independent_default():
    assert hasattr(common_schema, "AlgorithmActiveCutlineEvent")
    annotation = AlgorithmSnapshot.model_fields[
        "active_cutline_events"
    ].annotation
    assert "AlgorithmActiveCutlineEvent" in str(annotation)

    first = algorithm_snapshot()
    second = algorithm_snapshot()
    assert first.active_cutline_events == []
    assert first.active_cutline_events is not second.active_cutline_events


def test_create_event_sets_identity_context_and_initial_state():
    event = _create_event(_tracker())

    assert event.event_id
    assert event.plan_id == "PLAN-01"
    assert event.machine_code == "MC-01"
    assert event.source_order_code == "ORD-SOURCE"
    assert event.target_order_code == "ORD-TARGET"
    assert event.target_buffer_code == "BUF-TARGET"
    assert event.upstream_process_code == "P01"
    assert event.downstream_process_code == "P02"
    assert event.cutline_start_time == CUTLINE_START_TIME
    assert event.negative_start_time is None
    assert event.status == "active"


def test_create_event_generates_nonempty_unique_ids():
    tracker = _tracker()

    first = _create_event(tracker)
    second = _create_event(tracker)

    assert first.event_id
    assert second.event_id
    assert first.event_id != second.event_id


def test_create_event_uses_explicit_event_id_without_calling_factory():
    def fail_if_called():
        raise AssertionError("event ID factory must not be called")

    tracker = _tracker(event_id_factory=fail_if_called)

    event = _create_event(tracker, event_id="stable-event-id")

    assert event.event_id == "stable-event-id"


def test_create_event_preserves_explicit_empty_id_for_schema_validation():
    def fail_if_called():
        raise AssertionError("event ID factory must not be called")

    tracker = _tracker(event_id_factory=fail_if_called)

    with pytest.raises(ValidationError):
        _create_event(tracker, event_id="")


def test_update_negative_start_time_returns_copy_without_mutating_input():
    tracker = _tracker()
    original = active_event()
    negative_start_time = datetime(2026, 7, 15, 10, 0)

    updated = tracker.update_negative_start_time(
        event=original,
        negative_start_time=negative_start_time,
    )

    assert updated is not original
    assert updated.negative_start_time == negative_start_time
    assert original.negative_start_time is None


def test_status_updates_are_immutable_and_use_explicit_states():
    tracker = _tracker()
    original = active_event(
        negative_start_time=datetime(2026, 7, 15, 10, 0)
    )

    recommended = tracker.mark_return_recommended(event=original)
    returned = tracker.mark_returned(
        event=original,
        returned_time=datetime(2026, 7, 15, 11, 0),
    )
    cancelled = tracker.mark_cancelled(event=original)

    assert recommended.status == "return_recommended"
    assert returned.status == "returned"
    assert returned.negative_start_time is None
    assert cancelled.status == "cancelled"
    assert original.status == "active"
    assert original.negative_start_time == datetime(2026, 7, 15, 10, 0)
