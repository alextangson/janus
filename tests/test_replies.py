from gatekeeper.replies import zh_to_int, extract_int


def test_parse_basic_zh_numerals():
    assert zh_to_int("零") == 0
    assert zh_to_int("十") == 10
    assert zh_to_int("十六") == 16
    assert zh_to_int("二十") == 20
    assert zh_to_int("二十六") == 26
    assert zh_to_int("三十") == 30
    assert zh_to_int("一百") == 100
    assert zh_to_int("百") == 100


def test_zh_to_int_extracts_from_text():
    assert zh_to_int("调到二十六度") == 26
    assert zh_to_int("第二个") == 2


def test_zh_to_int_rejects_nonsense():
    assert zh_to_int("随便") is None
    assert zh_to_int("二六") is None       # 非规范串
    assert zh_to_int("一半") is None       # 分数词,非整数(一半≠1)
    assert zh_to_int("") is None


def test_extract_int_arabic_first_then_zh():
    assert extract_int("26度") == 26
    assert extract_int("二十六") == 26
    assert extract_int("abc") is None
