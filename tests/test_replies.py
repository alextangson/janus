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


from gatekeeper.models import ParamSpec
from gatekeeper.replies import coerce_param


def test_coerce_int_arabic_and_chinese():
    spec = ParamSpec(type="int", min=16, max=30, unit="°C", required=True)
    assert coerce_param("26", spec) == 26
    assert coerce_param("调到26度", spec) == 26
    assert coerce_param("二十六", spec) == 26
    assert coerce_param("设到二十六度", spec) == 26


def test_coerce_int_none_when_unparseable():
    spec = ParamSpec(type="int", min=16, max=30, required=True)
    assert coerce_param("随便", spec) is None
    assert coerce_param("一半", spec) is None      # 分数语义不支持(范围外)


def test_coerce_enum_english_and_chinese():
    spec = ParamSpec(type="enum", enum=["cool", "heat", "fan", "auto"], required=True)
    assert coerce_param("heat", spec) == "heat"
    assert coerce_param("制热", spec) == "heat"
    assert coerce_param("调成制冷", spec) == "cool"
    assert coerce_param("乱七八糟", spec) is None


from gatekeeper.replies import affirmation


def test_affirmation_positive():
    for s in ["好", "好的", "是", "对", "行", "可以", "嗯", "确认", "y", "yes", "OK"]:
        assert affirmation(s) is True, s


def test_affirmation_negative():
    for s in ["不", "不用", "不用了", "不要", "别", "取消", "算了", "不好", "n", "no", "否"]:
        assert affirmation(s) is False, s


def test_affirmation_unclear_is_none():
    for s in ["随便", "二十六", "第二个", ""]:
        assert affirmation(s) is None, s


from gatekeeper.replies import choice_index


def test_choice_index_arabic_and_spoken():
    assert choice_index("2", 3) == 2
    assert choice_index("第二个", 3) == 2
    assert choice_index("二", 3) == 2
    assert choice_index("选第一盏", 3) == 1


def test_choice_index_out_of_range_or_unparseable():
    assert choice_index("8", 2) is None       # 越界
    assert choice_index("第五个", 2) is None    # 越界
    assert choice_index("随便", 2) is None
