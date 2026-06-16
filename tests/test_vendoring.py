"""漂移守卫:集成里的 vendored 引擎副本必须与 root gatekeeper/ 逐字节一致。

custom_components/janus/gatekeeper/ 是构建产物(harness/vendor.sh 由 root 生成),
但已纳入版本控制以便 git clone / HACS 安装拿得到引擎代码。任一处漂移 = 线上跑旧码,
正是历史上"查询/缺参反问没在 HA 生效"那个 bug。此测试在 root 改动未 re-vendor 时当场失败。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "gatekeeper"
VENDORED = ROOT / "custom_components" / "janus" / "gatekeeper"

_SYNC_HINT = "运行 `bash harness/vendor.sh` 重新同步。"


def _py_files(d: Path) -> set[Path]:
    return {p.relative_to(d) for p in d.rglob("*.py") if "__pycache__" not in p.parts}


def test_vendored_engine_file_set_matches_root():
    src, vend = _py_files(SRC), _py_files(VENDORED)
    assert src == vend, (
        f"vendored 文件集与 root 不一致。{_SYNC_HINT}\n"
        f"仅 root: {sorted(map(str, src - vend))}\n"
        f"仅 vendored: {sorted(map(str, vend - src))}"
    )


def test_vendored_engine_bytes_match_root():
    mismatched = sorted(
        str(f) for f in _py_files(SRC)
        if (SRC / f).read_bytes() != (VENDORED / f).read_bytes()
    )
    assert not mismatched, f"vendored 引擎与 root 漂移。{_SYNC_HINT}\n不一致文件: {mismatched}"
