from app.schemas.response_schema import CutlineAlgorithmResponse
from app.schemas.result_schema import AlgorithmEvaluateResult


class AlgorithmResponseMapper:
    def to_response(
        self,
        result: AlgorithmEvaluateResult,
    ) -> CutlineAlgorithmResponse:
        return CutlineAlgorithmResponse(
            calculation_time=result.calculation_time,
            stockout_warnings=result.stockout_warnings,
            overflow_warnings=result.overflow_warnings,
            cutline_decisions=result.cutline_decisions,
            return_results=result.return_results,
            silk_screen_results=result.silk_screen_results,
            mixing_trace_records=result.mixing_trace_records,
            mixing_trace_failures=result.mixing_trace_failures,
            new_active_cutline_events=result.new_active_cutline_events,
            updated_active_cutline_events=result.updated_active_cutline_events,
            errors=result.errors,
        )
