def safe_float(value, default=0.0):
    """Convert value to float, returning default for missing or invalid values."""
    if value is None:
        return default

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_value(source, field_name):
    if isinstance(source, dict):
        return source.get(field_name)
    return getattr(source, field_name, None)


def get_machine_input_rate_per_hour(machine):
    value = _get_value(machine, "input_rate_per_hour")
    if value is not None:
        return safe_float(value)

    value = _get_value(machine, "input_quantity_30min")
    if value is not None:
        return safe_float(value) * 2

    value = _get_value(machine, "actual_capacity_per_hour")
    if value is not None:
        return safe_float(value)

    return 0.0


def get_machine_output_rate_per_hour(machine):
    value = _get_value(machine, "output_rate_per_hour")
    if value is not None:
        return safe_float(value)

    value = _get_value(machine, "out_quantity_30min")
    if value is not None:
        return safe_float(value) * 2

    value = _get_value(machine, "actual_capacity_per_hour")
    if value is not None:
        return safe_float(value)

    return 0.0
