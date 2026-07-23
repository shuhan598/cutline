# 断料预警组件：输入 AlgorithmSnapshot 与 AlgorithmDepletionTimeResult 列表，输出 AlgorithmStockoutWarningResult 列表

from app.core.warning.errors import WarningEvaluationError
from app.schemas.request_schema import AlgorithmSnapshot
from app.schemas.result_schema import (
    AlgorithmDepletionTimeResult,
    AlgorithmStockoutWarningResult,
)
from app.utils.numeric import safe_float


class StockoutWarningEvaluator:
    """耗尽时间 ≤ 切线提前量则触发断料预警。"""

    def evaluate_algorithm(
        self,
        snapshot: AlgorithmSnapshot,
        depletion_results: list[AlgorithmDepletionTimeResult],
    ) -> list[AlgorithmStockoutWarningResult]:
        stockout_warning_lead_minutes = safe_float(
            snapshot.config.stockout_warning_lead_minutes
        )
        if stockout_warning_lead_minutes <= 0:
            raise WarningEvaluationError(
                "stockout warning lead cannot be zero, negative, or non-finite"
            )

        warnings: list[AlgorithmStockoutWarningResult] = []
        seen: set[tuple[str, str, str, str, str, str, str]] = set()
        for depletion in depletion_results:
            self._validate_algorithm_depletion(depletion)
            unique_key = (
                depletion.workshop_code,
                depletion.main_id,
                depletion.order_code,
                depletion.wafer_size,
                depletion.wafer_spec,
                depletion.upstream_process_code,
                depletion.downstream_process_code,
            )
            if unique_key in seen:
                raise WarningEvaluationError(
                    "duplicate stockout warning input: "
                    f"workshop={depletion.workshop_code}, "
                    f"main_id={depletion.main_id}, "
                    f"buffer={depletion.buffer_code}, "
                    f"order={depletion.order_code}, "
                    f"wafer_size={depletion.wafer_size}, "
                    f"wafer_spec={depletion.wafer_spec}, "
                    f"interval={depletion.upstream_process_code}"
                    f"->{depletion.downstream_process_code}"
                )
            seen.add(unique_key)

            if (
                depletion.depletion_minutes is None
                or depletion.depletion_minutes
                > stockout_warning_lead_minutes
            ):
                continue

            warnings.append(
                AlgorithmStockoutWarningResult(
                    warning_type="stockout",
                    warning_time=snapshot.current_time,
                    main_id=depletion.main_id,
                    buffer_code=depletion.buffer_code,
                    buffer_codes=list(depletion.buffer_codes),
                    order_code=depletion.order_code,
                    wafer_size=depletion.wafer_size,
                    wafer_spec=depletion.wafer_spec,
                    workshop_code=depletion.workshop_code,
                    upstream_process_code=(
                        depletion.upstream_process_code
                    ),
                    downstream_process_code=(
                        depletion.downstream_process_code
                    ),
                    current_quantity=depletion.current_quantity,
                    upstream_output_rate=depletion.upstream_output_rate,
                    downstream_input_rate=depletion.downstream_input_rate,
                    net_consumption_rate=depletion.net_consumption_rate,
                    depletion_minutes=depletion.depletion_minutes,
                    stockout_warning_lead_minutes=(
                        stockout_warning_lead_minutes
                    ),
                )
            )

        return sorted(
            warnings,
            key=lambda warning: (
                warning.depletion_minutes,
                warning.workshop_code,
                warning.buffer_code,
                warning.order_code,
                warning.wafer_size,
                warning.wafer_spec,
                warning.upstream_process_code,
                warning.downstream_process_code,
            ),
        )

    def _validate_algorithm_depletion(
        self,
        depletion: AlgorithmDepletionTimeResult,
    ) -> None:
        context = (
            f"workshop={depletion.workshop_code}, "
            f"main_id={depletion.main_id}, "
            f"buffer={depletion.buffer_code}, "
            f"order={depletion.order_code}, "
            f"wafer_size={depletion.wafer_size}, "
            f"wafer_spec={depletion.wafer_spec}, "
            f"interval={depletion.upstream_process_code}"
            f"->{depletion.downstream_process_code}"
        )
        required_codes = (
            "main_id",
            "buffer_code",
            "order_code",
            "wafer_size",
            "wafer_spec",
            "workshop_code",
            "upstream_process_code",
            "downstream_process_code",
        )
        for field_name in required_codes:
            value = getattr(depletion, field_name, None)
            if not isinstance(value, str) or not value.strip():
                raise WarningEvaluationError(
                    f"{context} missing or blank {field_name}"
                )

        if not depletion.buffer_codes or any(
            not isinstance(buffer_code, str) or not buffer_code.strip()
            for buffer_code in depletion.buffer_codes
        ):
            raise WarningEvaluationError(
                f"{context} missing or blank buffer_codes"
            )

        if (
            depletion.depletion_minutes is not None
            and depletion.depletion_minutes < 0
        ):
            raise WarningEvaluationError(
                f"{context} depletion minutes cannot be negative"
            )
