from app.core.return_judge.return_evaluator import ReturnEvaluator


def test_return_evaluator_exposes_only_algorithm_api():
    for legacy_name in (
        "evaluate",
        "_find",
        "_inventory",
        "_normalize_code",
    ):
        assert not hasattr(ReturnEvaluator, legacy_name)
