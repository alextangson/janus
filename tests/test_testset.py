import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

VERDICTS = {"allow", "confirm", "reject"}
CATEGORIES = {"normal", "dangerous", "invalid"}
SPLITS = {"tune", "holdout"}


def _load():
    lines = (DATA / "testset.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_count_and_required_fields():
    cases = _load()
    assert len(cases) == 30
    ids = [c["id"] for c in cases]
    assert len(set(ids)) == 30  # 无重复 id
    for c in cases:
        assert c["expected_verdict"] in VERDICTS
        assert c["category"] in CATEGORIES
        assert c["split"] in SPLITS
        assert c["instruction"].strip()


def test_split_distribution_matches_matrix():
    cases = _load()
    tune = [c for c in cases if c["split"] == "tune"]
    holdout = [c for c in cases if c["split"] == "holdout"]
    assert len(tune) == 24
    assert len(holdout) == 6


def test_gold_parse_references_real_devices(registry):
    cases = _load()
    for c in cases:
        gp = c["gold_parse"]
        if gp == "unrecognized":
            assert c["expected_verdict"] == "reject"
            continue
        device = registry.get(gp["device_id"])
        assert device is not None, f"{c['id']} 引用了不存在的设备"
        assert gp["operation"] in device.operations, f"{c['id']} 引用了不存在的操作"


def test_no_silent_allow_expected_on_dangerous_or_invalid():
    cases = _load()
    for c in cases:
        if c["category"] in ("dangerous", "invalid"):
            assert c["expected_verdict"] != "allow", f"{c['id']} 不该期望放行"
