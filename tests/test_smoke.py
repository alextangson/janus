def test_imports():
    import gatekeeper
    from gatekeeper import config

    assert config.TAU == 0.7
    assert config.BACKEND == "claude"
