from app.service.algorithm_state_store import AlgorithmStateStore


def test_workshop_first_success_reports_reset_then_false():
    store = AlgorithmStateStore()
    first = store.begin("W1")
    assert first.state_reset is True
    store.commit("W1", {"pending": ["p1"]})
    second = store.begin("W1")
    assert second.state_reset is False
    assert second.state.get("pending") == ["p1"]


def test_failed_evaluation_does_not_commit_state():
    store = AlgorithmStateStore()
    store.begin("W1")
    store.abort("W1")
    next_attempt = store.begin("W1")
    assert next_attempt.state_reset is True

