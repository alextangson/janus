import os

from gatekeeper.config import load_env


def test_load_env_injects_with_setdefault(tmp_path, monkeypatch):
    envfile = tmp_path / ".env"
    envfile.write_text("GK_TEST_FOO=1\n# 注释行\nGK_TEST_BAR = 2 \n", encoding="utf-8")
    monkeypatch.delenv("GK_TEST_FOO", raising=False)
    monkeypatch.setenv("GK_TEST_BAR", "keep")
    load_env(envfile)
    assert os.environ["GK_TEST_FOO"] == "1"
    assert os.environ["GK_TEST_BAR"] == "keep"  # setdefault:不覆盖已有值


def test_load_env_missing_file_is_silent(tmp_path):
    load_env(tmp_path / "no_such.env")  # 不抛
