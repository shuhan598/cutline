import math


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        converted = float(value)
        if not math.isfinite(converted):
            return default

        return converted
    except (TypeError, ValueError, OverflowError):
        return default


def _get_value(source, field_name):
    if isinstance(source, dict):
        return source.get(field_name)
    return getattr(source, field_name, None)


def get_cutline_lead_minutes(data):
    config = _get_value(data, "config") or {}
    return safe_float(_get_value(config, "cutline_lead_minutes"))


def evaluate_stockout_warning(data, depletion_time_result):
    buffer_code = _get_value(depletion_time_result, "buffer_code")
    product_code = _get_value(depletion_time_result, "product_code")
    process_from = _get_value(depletion_time_result, "process_from")
    process_to = _get_value(depletion_time_result, "process_to")
    inventory_quantity = safe_float(_get_value(depletion_time_result, "inventory_quantity"))
    net_rate_per_hour = safe_float(_get_value(depletion_time_result, "net_rate_per_hour"))
    raw_depletion_minutes = _get_value(depletion_time_result, "depletion_minutes")
    depletion_minutes = (
        None
        if raw_depletion_minutes is None
        else safe_float(raw_depletion_minutes, default=None)
    )
    depletion_status = _get_value(depletion_time_result, "depletion_status")
    cutline_lead_minutes = get_cutline_lead_minutes(data)

    warning_triggered = False
    if depletion_status != "decreasing":
        reason = "inventory_not_decreasing"
    elif depletion_minutes is None:
        reason = "depletion_time_not_available"
    elif depletion_minutes <= cutline_lead_minutes:
        warning_triggered = True
        reason = "depletion_time_within_lead_time"
    else:
        reason = "depletion_time_beyond_lead_time"

    return {
        "buffer_code": buffer_code,
        "product_code": product_code,
        "process_from": process_from,
        "process_to": process_to,
        "warning_type": "stockout",
        "warning_triggered": warning_triggered,
        "reason": reason,
        "inventory_quantity": inventory_quantity,
        "net_rate_per_hour": net_rate_per_hour,
        "depletion_minutes": depletion_minutes,
        "depletion_status": depletion_status,
        "cutline_lead_minutes": cutline_lead_minutes,
    }


def evaluate_all_stockout_warnings(data, depletion_time_results):
    return [
        evaluate_stockout_warning(data, depletion_time_result)
        for depletion_time_result in (depletion_time_results or [])
    ]
