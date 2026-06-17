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


def find_inventory_quantity(data, buffer_code, product_code, process_from, process_to):
    buffer_inventories = _get_value(data, "buffer_inventories") or []
    inventory_quantity = 0.0

    for inventory in buffer_inventories:
        if (
            _get_value(inventory, "buffer_code") == buffer_code
            and _get_value(inventory, "product_code") == product_code
            and _get_value(inventory, "process_from") == process_from
            and _get_value(inventory, "process_to") == process_to
        ):
            inventory_quantity += safe_float(_get_value(inventory, "inventory_quantity"))

    return inventory_quantity


def calculate_depletion_time(data, net_rate_result):
    buffer_code = _get_value(net_rate_result, "buffer_code")
    product_code = _get_value(net_rate_result, "product_code")
    process_from = _get_value(net_rate_result, "process_from")
    process_to = _get_value(net_rate_result, "process_to")
    net_rate_per_hour = safe_float(_get_value(net_rate_result, "net_rate_per_hour"))
    inventory_quantity = find_inventory_quantity(
        data,
        buffer_code=buffer_code,
        product_code=product_code,
        process_from=process_from,
        process_to=process_to,
    )

    depletion_minutes = None
    if net_rate_per_hour > 0:
        depletion_minutes = inventory_quantity / net_rate_per_hour * 60
        depletion_status = "decreasing"
    elif net_rate_per_hour == 0:
        depletion_status = "stable"
    else:
        depletion_status = "increasing"

    return {
        "buffer_code": buffer_code,
        "product_code": product_code,
        "process_from": process_from,
        "process_to": process_to,
        "inventory_quantity": inventory_quantity,
        "net_rate_per_hour": net_rate_per_hour,
        "depletion_minutes": depletion_minutes,
        "depletion_status": depletion_status,
    }


def calculate_all_depletion_times(data, net_rate_results):
    return [
        calculate_depletion_time(data, net_rate_result)
        for net_rate_result in (net_rate_results or [])
    ]
