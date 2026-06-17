def _get_value(source, field_name):
    if isinstance(source, dict):
        return source.get(field_name)
    return getattr(source, field_name, None)


def build_product_model_map(data):
    product_models = _get_value(data, "product_models") or []

    return {
        _get_value(product_model, "product_code"): product_model
        for product_model in product_models
        if _get_value(product_model, "product_code") is not None
    }


def is_same_size_and_shape(current_model, target_model):
    current_wafer_size = _get_value(current_model, "wafer_size")
    target_wafer_size = _get_value(target_model, "wafer_size")
    current_shape_code = _get_value(current_model, "shape_code")
    target_shape_code = _get_value(target_model, "shape_code")

    return (
        current_wafer_size is not None
        and current_shape_code is not None
        and current_wafer_size == target_wafer_size
        and current_shape_code == target_shape_code
    )


def find_candidates_for_warning(data, warning_result):
    buffer_code = _get_value(warning_result, "buffer_code")
    product_code = _get_value(warning_result, "product_code")
    process_from = _get_value(warning_result, "process_from")
    process_to = _get_value(warning_result, "process_to")
    product_model_map = build_product_model_map(data)
    target_model = product_model_map.get(product_code)
    machine_statuses = _get_value(data, "machine_statuses") or []
    candidates = []

    if (
        _get_value(warning_result, "warning_triggered") is not True
        or _get_value(warning_result, "warning_type") != "stockout"
    ):
        return {
            "buffer_code": buffer_code,
            "product_code": product_code,
            "process_from": process_from,
            "process_to": process_to,
            "candidate_found": False,
            "candidate_status": "manual_intervention_required",
            "reason": "no_compatible_running_upstream_machine",
            "candidates": [],
        }

    for machine in machine_statuses:
        current_product_code = _get_value(machine, "product_code")
        current_model = product_model_map.get(current_product_code)

        if _get_value(machine, "status") != "running":
            continue
        if _get_value(machine, "process_code") != process_from:
            continue
        if current_product_code == product_code:
            continue
        if not is_same_size_and_shape(current_model, target_model):
            continue

        candidates.append(
            {
                "equipment_code": _get_value(machine, "equipment_code"),
                "equipment_name": _get_value(machine, "equipment_name"),
                "process_code": _get_value(machine, "process_code"),
                "current_product_code": current_product_code,
                "target_product_code": product_code,
                "wafer_size": _get_value(current_model, "wafer_size"),
                "shape_code": _get_value(current_model, "shape_code"),
                "reason": "same_process_size_shape_running_machine",
            }
        )

    if candidates:
        return {
            "buffer_code": buffer_code,
            "product_code": product_code,
            "process_from": process_from,
            "process_to": process_to,
            "candidate_found": True,
            "candidate_status": "candidate_found",
            "candidates": candidates,
        }

    return {
        "buffer_code": buffer_code,
        "product_code": product_code,
        "process_from": process_from,
        "process_to": process_to,
        "candidate_found": False,
        "candidate_status": "manual_intervention_required",
        "reason": "no_compatible_running_upstream_machine",
        "candidates": [],
    }


def find_all_candidates(data, warning_results):
    def depletion_minutes_sort_key(warning_result):
        depletion_minutes = _get_value(warning_result, "depletion_minutes")
        if depletion_minutes is None:
            return float("inf")

        try:
            return float(depletion_minutes)
        except (TypeError, ValueError):
            return float("inf")

    stockout_warnings = [
        warning_result
        for warning_result in (warning_results or [])
        if (
            _get_value(warning_result, "warning_triggered") is True
            and _get_value(warning_result, "warning_type") == "stockout"
        )
    ]

    return [
        find_candidates_for_warning(data, warning_result)
        for warning_result in sorted(stockout_warnings, key=depletion_minutes_sort_key)
    ]
