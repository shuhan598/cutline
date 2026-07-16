import importlib.util
import inspect
from importlib.machinery import PathFinder

import app.core
import app.core.candidate_machine.product_compatibility as compatibility
from app.core.candidate_machine.overflow_candidate_finder import (
    OverflowCandidateFinder,
)
from app.core.candidate_machine.stockout_candidate_finder import (
    StockoutCandidateFinder,
)


def test_candidate_finders_expose_only_algorithm_api():
    for finder_type in (StockoutCandidateFinder, OverflowCandidateFinder):
        assert tuple(inspect.signature(finder_type).parameters) == ()
        assert not hasattr(finder_type, "find")


def test_product_compatibility_exposes_only_algorithm_functions():
    assert not hasattr(compatibility, "ProductCompatibilityChecker")


def test_legacy_workshop_modules_are_not_importable():
    assert importlib.util.find_spec(
        "app.core.candidate_machine.workshop_scope"
    ) is None
    assert importlib.util.find_spec(
        "app.core.workshop.workshop_resolver"
    ) is None


def test_legacy_workshop_package_has_no_concrete_package_entrypoint():
    spec = PathFinder.find_spec("app.core.workshop", app.core.__path__)

    assert spec is None or spec.loader is None
