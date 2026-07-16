import importlib

import pytest

from tests.core.candidate_machine.helpers import snapshot


def _context_module():
    return importlib.import_module(
        "app.core.candidate_machine.candidate_context"
    )


def _assert_context_error(candidate_snapshot, match: str) -> None:
    module = _context_module()
    with pytest.raises(module.CandidateMachineCalculationError, match=match):
        module.CandidateContext(candidate_snapshot)


@pytest.mark.parametrize(
    ("collection_name", "match"),
    [
        ("machine_runtimes", "M-01.*duplicate machine runtime"),
        ("machine_masters", "M-01.*duplicate machine master"),
        ("machine_lines", "M-01.*multiple machine-line"),
        ("lines", "LINE-1.*duplicate line"),
        ("orders", "ORD-CURRENT.*duplicate order"),
        ("products", "PROD-CURRENT.*duplicate product"),
        ("buffer_process_relations", "BUF-01.*duplicate buffer process relation"),
    ],
)
def test_all_candidate_indexes_reject_duplicate_keys(
    collection_name: str,
    match: str,
):
    candidate_snapshot = snapshot()
    collection = getattr(candidate_snapshot, collection_name)
    collection.append(collection[0].model_copy())

    _assert_context_error(candidate_snapshot, match)


def test_context_builds_all_required_indexes():
    context = _context_module().CandidateContext(snapshot())

    assert context.runtime_by_machine_code["M-01"].machine_code == "M-01"
    assert context.machine_by_code["M-01"].machine_name == "M-01"
    assert context.machine_line_by_machine_code["M-01"].line_code == "LINE-1"
    assert context.line_by_code["LINE-1"].workshop_code == "S1"
    assert context.order_by_code["ORD-CURRENT"].product_code == "PROD-CURRENT"
    assert context.product_by_code["PROD-CURRENT"].wafer_size == "182"
    assert context.buffer_relation_by_code["BUF-01"].upstream_process_code == "P01"


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_machine", "M-01.*machine master.*does not exist"),
        ("missing_machine_line", "M-01.*machine-line.*does not exist"),
        ("missing_line", "LINE-1.*line.*does not exist"),
        ("missing_runtime_order", "ORD-CURRENT.*order.*does not exist"),
        ("missing_order_product", "PROD-CURRENT.*product.*does not exist"),
    ],
)
def test_candidate_context_rejects_missing_required_references(
    mutation: str,
    match: str,
):
    candidate_snapshot = snapshot()
    if mutation == "missing_machine":
        candidate_snapshot.machine_masters = []
    elif mutation == "missing_machine_line":
        candidate_snapshot.machine_lines = []
    elif mutation == "missing_line":
        candidate_snapshot.lines = []
    elif mutation == "missing_runtime_order":
        candidate_snapshot.orders = []
    elif mutation == "missing_order_product":
        candidate_snapshot.products = []

    _assert_context_error(candidate_snapshot, match)

