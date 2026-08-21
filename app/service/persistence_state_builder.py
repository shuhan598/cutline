"""根据本轮算法结果构建下一轮请求需要持久化的状态。"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import ValidationError

from app.schemas.common_schema import AlgorithmActiveCutlineEvent
from app.schemas.pending_cutline_schema import (
    PendingCutlinePlan,
    PendingCutlinePlanStatus,
)
from app.schemas.result_schema import (
    AlgorithmMixingTraceRecord,
    AlgorithmPersistenceState,
    AlgorithmReturnResult,
    PendingCutlinePlanEvaluation,
)


class PersistenceStateBuildError(ValueError):
    """同一轮评估出现互相冲突的持久化对象标识。"""


class PersistenceStateBuilder:
    """构建一轮无状态调用结束后需要由后端完整保存的数据。"""

    def build(
        self,
        *,
        incoming_pending_plans: list[PendingCutlinePlan],
        plan_evaluations: list[PendingCutlinePlanEvaluation],
        new_pending_plans: list[PendingCutlinePlan],
        active_cutline_events: list[AlgorithmActiveCutlineEvent],
        input_return_suggested_event_ids: list[str],
        input_mixed_cutline_event_ids: list[str],
        return_results: list[AlgorithmReturnResult],
        new_mixing_trace_records: list[AlgorithmMixingTraceRecord],
        successful_mixed_event_ids: list[str],
    ) -> AlgorithmPersistenceState:
        # 合并输入状态与本轮结果时按对象标识去重，并拒绝同一标识携带不同业务内容的情况。
        """根据当前快照和业务规则执行【build】计算，返回类型标注所声明的结果。"""
        plans_by_id = self._unique_plans(
            incoming_pending_plans,
            source="incoming_pending_plans",
        )
        evaluations_by_id = self._unique_evaluations(plan_evaluations)
        unknown_ids = sorted(set(evaluations_by_id) - set(plans_by_id))
        if unknown_ids:
            raise PersistenceStateBuildError(
                "plan evaluation references unknown plan_id values: "
                f"{unknown_ids!r}"
            )

        updated_plans: dict[str, PendingCutlinePlan] = {}
        terminal_statuses = {
            PendingCutlinePlanStatus.CONFIRMED,
            PendingCutlinePlanStatus.EXPIRED,
            PendingCutlinePlanStatus.RETURN_SUGGESTED,
        }
        for plan_id, plan in plans_by_id.items():
            evaluation = evaluations_by_id.get(plan_id)
            if plan.status in terminal_statuses or evaluation is None:
                updated_plans[plan_id] = plan
                continue
            if evaluation.warning_id != plan.warning_id:
                raise PersistenceStateBuildError(
                    f"plan_id={plan_id}: evaluation warning_id="
                    f"{evaluation.warning_id!r} conflicts with plan warning_id="
                    f"{plan.warning_id!r}"
                )
            try:
                updated_plans[plan_id] = PendingCutlinePlan.model_validate(
                    {
                        **plan.model_dump(),
                    "status": evaluation.status,
                    "confirmed_machine_codes": sorted(
                        set(evaluation.confirmed_machine_codes)
                    ),
                    }
                )
            except ValidationError as error:
                raise PersistenceStateBuildError(
                    f"plan_id={plan_id}: evaluation conflicts with pending plan: "
                    f"{error}"
                ) from error

        for plan_id, plan in self._unique_plans(
            new_pending_plans,
            source="new_pending_plans",
        ).items():
            existing = updated_plans.get(plan_id)
            if existing is not None and existing != plan:
                raise PersistenceStateBuildError(
                    f"plan_id={plan_id}: conflicting pending plan payloads"
                )
            updated_plans.setdefault(plan_id, plan)

        active_events = self._unique_active_events(active_cutline_events)
        return_ids = self._sorted_unique(
            [
                *input_return_suggested_event_ids,
                *(
                    result.event_id
                    for result in return_results
                    if result.return_recommended
                ),
                *(
                    event.event_id
                    for event in active_events
                    if event.status == "return_recommended"
                ),
            ]
        )
        return_id_set = set(return_ids)
        active_ids_by_plan: dict[str, set[str]] = {}
        for event in active_events:
            if event.plan_id is not None:
                active_ids_by_plan.setdefault(event.plan_id, set()).add(
                    event.event_id
                )
        # 已确认计划关联的所有活跃事件均进入回流建议后，计划随之转为终态，避免下轮重复确认。
        for plan_id, plan in list(updated_plans.items()):
            associated_ids = active_ids_by_plan.get(plan_id, set())
            if (
                plan.status is PendingCutlinePlanStatus.CONFIRMED
                and associated_ids
                and associated_ids <= return_id_set
            ):
                updated_plans[plan_id] = plan.model_copy(
                    update={
                        "status": PendingCutlinePlanStatus.RETURN_SUGGESTED
                    },
                    deep=True,
                )

        pending_plans = [updated_plans[key] for key in sorted(updated_plans)]
        return AlgorithmPersistenceState(
            pending_cutline_plans=pending_plans,
            active_cutline_events=active_events,
            expired_pending_plan_ids=[
                plan.plan_id
                for plan in pending_plans
                if plan.status is PendingCutlinePlanStatus.EXPIRED
            ],
            completed_pending_plan_ids=[
                plan.plan_id
                for plan in pending_plans
                if plan.status
                in {
                    PendingCutlinePlanStatus.CONFIRMED,
                    PendingCutlinePlanStatus.RETURN_SUGGESTED,
                }
            ],
            return_suggested_event_ids=return_ids,
            mixed_cutline_event_ids=self._sorted_unique(
                [
                    *input_mixed_cutline_event_ids,
                    *successful_mixed_event_ids,
                ]
            ),
            new_mixing_trace_records=sorted(
                new_mixing_trace_records,
                key=lambda item: (
                    item.mix_start_time,
                    item.machine_code,
                    item.cutline_event_id,
                ),
            ),
        )

    def _unique_plans(
        self,
        plans: Iterable[PendingCutlinePlan],
        *,
        source: str,
    ) -> dict[str, PendingCutlinePlan]:
        # 同一计划 ID 的完全相同副本可以合并；内容不一致说明上游状态已失去确定性。
        """内部辅助步骤【_unique_plans】，为上层业务流程提供数据处理或共用判断。"""
        result: dict[str, PendingCutlinePlan] = {}
        for plan in plans:
            existing = result.get(plan.plan_id)
            if existing is not None and existing != plan:
                raise PersistenceStateBuildError(
                    f"plan_id={plan.plan_id}: conflicting entries in {source}"
                )
            result.setdefault(plan.plan_id, plan)
        return result

    def _unique_evaluations(
        self,
        evaluations: Iterable[PendingCutlinePlanEvaluation],
    ) -> dict[str, PendingCutlinePlanEvaluation]:
        # 一轮内每个待确认计划只能有一个评估结论。
        """内部辅助步骤【_unique_evaluations】，为上层业务流程提供数据处理或共用判断。"""
        result: dict[str, PendingCutlinePlanEvaluation] = {}
        for evaluation in evaluations:
            existing = result.get(evaluation.plan_id)
            if existing is not None and existing != evaluation:
                raise PersistenceStateBuildError(
                    f"plan_id={evaluation.plan_id}: conflicting plan evaluations"
                )
            result.setdefault(evaluation.plan_id, evaluation)
        return result

    def _unique_active_events(
        self,
        events: Iterable[AlgorithmActiveCutlineEvent],
    ) -> list[AlgorithmActiveCutlineEvent]:
        # 活跃事件按事件 ID 合并并稳定排序，使持久化结果可重复比较。
        """内部辅助步骤【_unique_active_events】，为上层业务流程提供数据处理或共用判断。"""
        by_id: dict[str, AlgorithmActiveCutlineEvent] = {}
        for event in events:
            existing = by_id.get(event.event_id)
            if existing is not None and existing != event:
                raise PersistenceStateBuildError(
                    f"event_id={event.event_id}: conflicting active event payloads"
                )
            by_id.setdefault(event.event_id, event)
        return [by_id[event_id] for event_id in sorted(by_id)]

    @staticmethod
    def _sorted_unique(values: Iterable[str]) -> list[str]:
        # 集合字段输出稳定排序，减少同一业务状态因输入顺序不同造成的无意义差异。
        """内部辅助步骤【_sorted_unique】，为上层业务流程提供数据处理或共用判断。"""
        return sorted(set(values))
