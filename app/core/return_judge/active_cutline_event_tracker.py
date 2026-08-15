"""维护活动切线事件的创建、稳定、到期和关闭状态。"""

from collections.abc import Callable
from datetime import datetime
from typing import Literal
from uuid import uuid4

from app.schemas.common_schema import AlgorithmActiveCutlineEvent


class ActiveCutlineEventTracker:
    """创建活动切线事件，并以不可变方式更新其跨轮状态。"""

    def __init__(
        self,
        event_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._event_id_factory = event_id_factory or (lambda: str(uuid4()))

    def create_event(
        self,
        *,
        plan_id: str,
        warning_id: str | None = None,
        machine_code: str,
        source_order_code: str,
        target_order_code: str,
        workshop_code: str,
        source_buffer_code: str | None,
        target_buffer_code: str,
        upstream_process_code: str,
        downstream_process_code: str,
        source_wafer_size: str,
        source_wafer_spec: str,
        target_wafer_size: str,
        target_wafer_spec: str,
        cutline_start_time: datetime,
        contribution_capacity: float | None = None,
        warning_type: Literal["stockout", "overflow"] | None = None,
        process_code: str | None = None,
        warning_buffer_code: str | None = None,
        warning_upstream_process_code: str | None = None,
        warning_downstream_process_code: str | None = None,
        is_recommended_candidate: bool | None = None,
        event_id: str | None = None,
    ) -> AlgorithmActiveCutlineEvent:
        return AlgorithmActiveCutlineEvent(
            event_id=(
                event_id
                if event_id is not None
                else self._event_id_factory()
            ),
            plan_id=plan_id,
            warning_id=warning_id,
            machine_code=machine_code,
            source_order_code=source_order_code,
            target_order_code=target_order_code,
            workshop_code=workshop_code,
            source_buffer_code=source_buffer_code,
            target_buffer_code=target_buffer_code,
            upstream_process_code=upstream_process_code,
            downstream_process_code=downstream_process_code,
            source_wafer_size=source_wafer_size,
            source_wafer_spec=source_wafer_spec,
            target_wafer_size=target_wafer_size,
            target_wafer_spec=target_wafer_spec,
            cutline_start_time=cutline_start_time,
            negative_start_time=None,
            status="active",
            contribution_capacity=contribution_capacity,
            warning_type=warning_type,
            process_code=process_code,
            warning_buffer_code=warning_buffer_code,
            warning_upstream_process_code=(
                warning_upstream_process_code
            ),
            warning_downstream_process_code=(
                warning_downstream_process_code
            ),
            is_recommended_candidate=is_recommended_candidate,
        )

    def update_negative_start_time(
        self,
        *,
        event: AlgorithmActiveCutlineEvent,
        negative_start_time: datetime | None,
    ) -> AlgorithmActiveCutlineEvent:
        return event.model_copy(
            update={"negative_start_time": negative_start_time},
            deep=True,
        )

    def mark_return_recommended(
        self,
        *,
        event: AlgorithmActiveCutlineEvent,
    ) -> AlgorithmActiveCutlineEvent:
        return event.model_copy(
            update={"status": "return_recommended"},
            deep=True,
        )

    def mark_returned(
        self,
        *,
        event: AlgorithmActiveCutlineEvent,
        returned_time: datetime | None = None,
    ) -> AlgorithmActiveCutlineEvent:
        _ = returned_time
        return event.model_copy(
            update={
                "status": "returned",
                "negative_start_time": None,
            },
            deep=True,
        )

    def mark_cancelled(
        self,
        *,
        event: AlgorithmActiveCutlineEvent,
    ) -> AlgorithmActiveCutlineEvent:
        return event.model_copy(
            update={"status": "cancelled"},
            deep=True,
        )
