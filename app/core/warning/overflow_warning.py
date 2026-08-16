"""根据物理 main Buffer 溢满时间生成溢满预警。"""

from app.core.warning.errors import WarningEvaluationError
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmBufferOverflowTimeResult,
    AlgorithmOverflowWarningResult,
)
from app.utils.numeric import safe_float


class OverflowWarningEvaluator:
    """判断溢满警告是否进入 overflow_warning_lead_minutes 窗口。"""

    def evaluate_algorithm(
        self,
        snapshot: AlgorithmSnapshot,
        overflow_results: list[AlgorithmBufferOverflowTimeResult],
    ) -> list[AlgorithmOverflowWarningResult]:
        """函数 ``evaluate_algorithm`` 执行当前业务步骤。参数、返回值和异常语义以类型标注及调用方契约为准。"""
        overflow_warning_lead_minutes = safe_float(
            snapshot.config.overflow_warning_lead_minutes
        )
        if overflow_warning_lead_minutes <= 0:
            raise WarningEvaluationError(
                "overflow warning lead cannot be zero, negative, or non-finite"
            )

        warnings: list[AlgorithmOverflowWarningResult] = []
        seen_main_ids: set[str] = set()
        for overflow in overflow_results:
            self._validate_algorithm_overflow(overflow)
            if overflow.main_id in seen_main_ids:
                raise WarningEvaluationError(
                    f"{overflow.main_id} duplicate overflow warning input"
                )
            seen_main_ids.add(overflow.main_id)

            if (
                overflow.overflow_minutes is None
                or overflow.overflow_minutes
                > overflow_warning_lead_minutes
            ):
                continue

            warnings.append(
                AlgorithmOverflowWarningResult(
                    warning_type="overflow",
                    warning_time=snapshot.current_time,
                    main_id=overflow.main_id,
                    buffer_code=overflow.buffer_code,
                    buffer_codes=list(overflow.buffer_codes),
                    workshop_code=overflow.workshop_code,
                    upstream_process_code=overflow.upstream_process_code,
                    downstream_process_code=overflow.downstream_process_code,
                    max_capacity=overflow.max_capacity,
                    total_inventory=overflow.total_inventory,
                    remaining_capacity=overflow.remaining_capacity,
                    buffer_growth_rate=overflow.buffer_growth_rate,
                    overflow_minutes=overflow.overflow_minutes,
                    overflow_warning_lead_minutes=(
                        overflow_warning_lead_minutes
                    ),
                    order_growth_details=[
                        detail.model_copy(deep=True)
                        for detail in overflow.order_growth_details
                    ],
                    group_key=overflow.group_key,
                )
            )

        return sorted(
            warnings,
            key=lambda warning: (
                warning.overflow_minutes,
                warning.workshop_code,
                warning.buffer_code,
                warning.upstream_process_code,
                warning.downstream_process_code,
            ),
        )

    def _validate_algorithm_overflow(
        self,
        overflow: AlgorithmBufferOverflowTimeResult,
    ) -> None:
        """函数 ``_validate_algorithm_overflow`` 执行当前业务步骤。参数、返回值和异常语义以类型标注及调用方契约为准。"""
        context = (
            f"workshop={getattr(overflow, 'workshop_code', None)}, "
            f"main_id={overflow.main_id}, "
            f"buffer={overflow.buffer_code}, "
            f"interval={getattr(overflow, 'upstream_process_code', None)}"
            f"->{getattr(overflow, 'downstream_process_code', None)}"
        )
        required_codes = (
            "main_id",
            "workshop_code",
            "buffer_code",
            "upstream_process_code",
            "downstream_process_code",
        )
        for field_name in required_codes:
            value = getattr(overflow, field_name, None)
            if not isinstance(value, str) or not value.strip():
                raise WarningEvaluationError(
                    f"{context} missing or blank {field_name}"
                )

        if not overflow.buffer_codes or any(
            not isinstance(buffer_code, str) or not buffer_code.strip()
            for buffer_code in overflow.buffer_codes
        ):
            raise WarningEvaluationError(
                f"{context} missing or blank buffer_codes"
            )

        if (
            overflow.overflow_minutes is not None
            and overflow.overflow_minutes < 0
        ):
            raise WarningEvaluationError(
                f"{context} overflow minutes cannot be negative"
            )
