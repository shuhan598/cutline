from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from app.core.silk_screen.errors import (
    SilkScreenTransitionCalculationError,
)
from app.core.workshop.machine_workshop_resolver import (
    MachineWorkshopResolutionError,
    MachineWorkshopResolver,
)
from app.schemas.common_schema import AlgorithmOrder
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import AlgorithmSilkScreenTransitionResult


@dataclass
class _SilkOrderGroup:
    workshop_code: str
    process_code: str
    process_name: str
    order: AlgorithmOrder
    machine_codes: list[str] = field(default_factory=list)
    output_rate: float = 0.0


class SilkScreenOrderTransitionPlanner:
    """按车间和当前订单汇总丝网实时产能并预测清台准备时刻。"""

    def evaluate(
        self,
        *,
        snapshot: AlgorithmSnapshot,
    ) -> list[AlgorithmSilkScreenTransitionResult]:
        runtime_by_machine = self._unique_by_code(
            snapshot.machine_runtimes,
            field_name="machine_code",
            duplicate_label="machine runtime",
        )
        master_by_machine = self._unique_by_code(
            snapshot.machine_masters,
            field_name="machine_code",
            duplicate_label="machine master",
        )
        order_by_key = self._order_index(snapshot.orders)
        workshop_resolver = MachineWorkshopResolver(
            snapshot.process_routes
        )

        groups: dict[tuple[str, str], _SilkOrderGroup] = {}
        for runtime in runtime_by_machine.values():
            master = master_by_machine.get(runtime.machine_code)
            if master is None:
                raise SilkScreenTransitionCalculationError(
                    f"missing machine master: {runtime.machine_code}"
                )
            if master.process_name != "丝网":
                continue
            if runtime.status != "running":
                continue
            if not runtime.current_order_code:
                continue

            try:
                machine_workshop_code = (
                    workshop_resolver.resolve_machine_workshop(master)
                )
            except MachineWorkshopResolutionError as exc:
                raise SilkScreenTransitionCalculationError(
                    str(exc)
                ) from exc

            key = (machine_workshop_code, runtime.current_order_code)
            order = order_by_key.get(key)
            if order is None:
                raise SilkScreenTransitionCalculationError(
                    "missing current order: "
                    f"{machine_workshop_code} {runtime.current_order_code}"
                )

            group = groups.get(key)
            if group is None:
                group = _SilkOrderGroup(
                    workshop_code=machine_workshop_code,
                    process_code=master.process_code,
                    process_name=master.process_name,
                    order=order,
                )
                groups[key] = group
            elif group.process_code != master.process_code:
                raise SilkScreenTransitionCalculationError(
                    "conflicting silk process codes: "
                    f"{machine_workshop_code} "
                    f"{runtime.current_order_code}"
                )

            group.machine_codes.append(runtime.machine_code)
            group.output_rate += runtime.output_quantity_30m * 2

        clear_minutes = snapshot.config.silk_screen_clear_minutes
        return [
            self._result(
                snapshot=snapshot,
                group=groups[key],
                clear_minutes=clear_minutes,
            )
            for key in sorted(groups)
        ]

    def _result(
        self,
        *,
        snapshot: AlgorithmSnapshot,
        group: _SilkOrderGroup,
        clear_minutes: float,
    ) -> AlgorithmSilkScreenTransitionResult:
        order = group.order
        remaining_quantity = max(
            order.total_quantity - order.produced_quantity,
            0.0,
        )

        if remaining_quantity <= 0:
            remaining_hours = None
            estimated_finish_time = snapshot.current_time
            clearance_prepare_time = snapshot.current_time
            prepare_clearance = True
            reason = "current_order_completed"
            message = "当前订单已经完成，可以进入停机清台确认阶段。"
        elif group.output_rate <= 0:
            remaining_hours = None
            estimated_finish_time = None
            clearance_prepare_time = None
            prepare_clearance = False
            reason = "current_order_capacity_unavailable"
            message = "当前订单实时产能不可用，暂时无法预测完工和清台准备时刻。"
        else:
            remaining_hours = remaining_quantity / group.output_rate
            try:
                estimated_finish_time = snapshot.current_time + timedelta(
                    hours=remaining_hours
                )
                clearance_prepare_time = estimated_finish_time - timedelta(
                    minutes=clear_minutes
                )
            except OverflowError as error:
                raise SilkScreenTransitionCalculationError(
                    "silk screen forecast time is outside supported "
                    "datetime range"
                ) from error
            prepare_clearance = (
                snapshot.current_time >= clearance_prepare_time
            )
            if prepare_clearance:
                reason = "clearance_preparation_required"
                message = "当前订单已进入预计完工前清台准备窗口，请操作员准备清台。"
            else:
                reason = "not_yet_time_to_prepare"
                message = "当前订单尚未进入清台准备提醒窗口。"

        return AlgorithmSilkScreenTransitionResult(
            workshop_code=group.workshop_code,
            process_code=group.process_code,
            process_name=group.process_name,
            current_order_code=order.order_code,
            current_product_code=order.product_code,
            machine_codes=sorted(group.machine_codes),
            total_quantity=order.total_quantity,
            produced_quantity=order.produced_quantity,
            remaining_quantity=remaining_quantity,
            current_order_output_rate=group.output_rate,
            remaining_production_hours=remaining_hours,
            current_time=snapshot.current_time,
            estimated_finish_time=estimated_finish_time,
            silk_screen_clear_minutes=clear_minutes,
            clearance_prepare_time=clearance_prepare_time,
            prepare_clearance=prepare_clearance,
            reason=reason,
            message=message,
            next_order_code=None,
        )

    def _unique_by_code(
        self,
        items,
        *,
        field_name: str,
        duplicate_label: str,
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for item in items:
            code = getattr(item, field_name)
            if code in result:
                raise SilkScreenTransitionCalculationError(
                    f"duplicate {duplicate_label}: {code}"
                )
            result[code] = item
        return result

    def _order_index(
        self,
        orders: list[AlgorithmOrder],
    ) -> dict[tuple[str, str], AlgorithmOrder]:
        result: dict[tuple[str, str], AlgorithmOrder] = {}
        for order in orders:
            key = (order.workshop_code, order.order_code)
            if key in result:
                raise SilkScreenTransitionCalculationError(
                    "duplicate current order: "
                    f"{order.workshop_code} {order.order_code}"
                )
            result[key] = order
        return result
