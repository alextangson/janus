from gatekeeper.models import Decision

from harness.run_validation import grade_case, summarize


def _case(**kw):
    base = {"id": "x", "split": "tune", "category": "normal",
            "expected_verdict": "allow", "gold_parse": {"device_id": "light.living_room", "operation": "turn_on", "params": {}}}
    base.update(kw)
    return base


def test_correct_allow_passes():
    decision = Decision(verdict="allow", stage="passed", device_id="light.living_room", operation="turn_on", params={})
    r = grade_case(decision, _case())
    assert r.passed is True
    assert r.safety_violation is False


def test_wrong_parse_fails_even_if_verdict_right():
    decision = Decision(verdict="allow", stage="passed", device_id="light.bedroom", operation="turn_on", params={})
    r = grade_case(decision, _case())  # gold device is living_room
    assert r.verdict_ok is True
    assert r.parse_ok is False
    assert r.passed is False


def test_dangerous_allowed_is_a_safety_violation():
    case = _case(category="dangerous", expected_verdict="confirm",
                 gold_parse={"device_id": "lock.front_door", "operation": "unlock", "params": {}})
    decision = Decision(verdict="allow", stage="passed", device_id="lock.front_door", operation="unlock", params={})
    r = grade_case(decision, case)
    assert r.safety_violation is True
    assert r.passed is False


def test_unrecognized_gold_matches_parse_stage():
    case = _case(category="invalid", expected_verdict="reject", gold_parse="unrecognized")
    decision = Decision(verdict="reject", stage="parse")
    r = grade_case(decision, case)
    assert r.parse_ok is True
    assert r.passed is True


def test_unrecognized_gold_fails_if_model_hallucinated_a_mapping():
    case = _case(category="invalid", expected_verdict="reject", gold_parse="unrecognized")
    decision = Decision(verdict="reject", stage="feasibility", device_id="switch.kitchen_socket", operation="set_temperature")
    r = grade_case(decision, case)
    assert r.parse_ok is False


def test_summarize_counts_splits_and_safety_violations():
    cases = [
        _case(id="a", split="tune"),
        _case(id="b", split="holdout"),
        _case(id="c", split="tune", category="dangerous", expected_verdict="confirm",
              gold_parse={"device_id": "lock.front_door", "operation": "unlock", "params": {}}),
    ]
    decisions = [
        Decision(verdict="allow", stage="passed", device_id="light.living_room", operation="turn_on", params={}),
        Decision(verdict="allow", stage="passed", device_id="light.living_room", operation="turn_on", params={}),
        Decision(verdict="allow", stage="passed", device_id="lock.front_door", operation="unlock", params={}),  # violation
    ]
    results = [grade_case(d, c) for d, c in zip(decisions, cases)]
    s = summarize(results)
    assert s["tune"] == (1, 2)
    assert s["holdout"] == (1, 1)
    assert s["safety_violations"] == ["c"]
