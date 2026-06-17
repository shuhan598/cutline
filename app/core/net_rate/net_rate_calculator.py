from app.core.net_rate.rate_utils import (
    get_machine_input_rate_per_hour,
    get_machine_output_rate_per_hour,
)


def _get_value(source, field_name):
    if isinstance(source, dict):
        return source.get(field_name)
    return getattr(source, field_name, None)


def calculate_net_rate(
    data,
    buffer_code,
    product_code,
    process_from,
    process_to,
):
    machine_statuses = data.get("machine_statuses", []) if isinstance(data, dict) else []

    upstream_output_per_hour = 0.0
    downstream_input_per_hour = 0.0
    upstream_equipment_codes = []
    downstream_equipment_codes = []

    for machine in machine_statuses:
        equipment_code = _get_value(machine, "equipment_code")

        if _get_value(machine, "status") != "running":
            continue

        if _get_value(machine, "product_code") != product_code:
            continue

        process_code = _get_value(machine, "process_code")
        if process_code == process_from:
            upstream_output_per_hour += get_machine_output_rate_per_hour(machine)
            upstream_equipment_codes.append(equipment_code)
        elif process_code == process_to:
            downstream_input_per_hour += get_machine_input_rate_per_hour(machine)
            downstream_equipment_codes.append(equipment_code)

    return {
        "buffer_code": buffer_code,
        "product_code": product_code,
        "process_from": process_from,
        "process_to": process_to,
        "upstream_output_per_hour": upstream_output_per_hour,
        "downstream_input_per_hour": downstream_input_per_hour,
        "net_rate_per_hour": downstream_input_per_hour - upstream_output_per_hour,
        "upstream_equipment_codes": upstream_equipment_codes,
        "downstream_equipment_codes": downstream_equipment_codes,
    }


def calculate_all_net_rates(data):
    buffer_inventories = data.get("buffer_inventories", []) if isinstance(data, dict) else []
    results = []
    seen_segments = set()

    for inventory in buffer_inventories:
        segment_key = (
            _get_value(inventory, "buffer_code"),
            _get_value(inventory, "product_code"),
            _get_value(inventory, "process_from"),
            _get_value(inventory, "process_to"),
        )

        if segment_key in seen_segments:
            continue

        seen_segments.add(segment_key)
        results.append(calculate_net_rate(data, *segment_key))

    return results
