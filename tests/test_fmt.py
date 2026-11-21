import pytest

from trader import fmt


@pytest.mark.parametrize(
    "x,signed,expected",
    [
        (0.123455, True, "+12.35%"),  # half up, not banker's rounding
        (0.12344, True, "+12.34%"),
        (-0.0670, True, "-6.70%"),
        (0.0, True, "0.00%"),
        (-0.00001, True, "0.00%"),  # rounds to zero: no sign
        (0.5, False, "50.00%"),
        (None, True, "—"),
        (2.571157, True, "+257.12%"),
    ],
)
def test_pct(x, signed, expected):
    assert fmt.pct(x, signed) == expected


@pytest.mark.parametrize(
    "x,expected",
    [(1_275_226.5, "1,275,227"), (1422.0, "1,422"), (-401.4, "-401"), (0.4, "0"), (-0.4, "0")],
)
def test_money(x, expected):
    assert fmt.money(x) == expected


def test_price_and_shares():
    assert fmt.price(564.6) == "564.60"
    assert fmt.price(1045.0) == "1,045.00"
    assert fmt.price(0.125) == "0.13"
    assert fmt.shares(2031) == "2,031"


def test_symbol_label_adds_the_chinese_name_when_listed():
    assert fmt.symbol_label("2330.TW") == "2330.TW 台積電"
    assert fmt.symbol_label("0050.TW") == "0050.TW 元大台灣50"
    assert fmt.symbol_label("AAPL") == "AAPL"


def test_ratio_and_signed_money():
    assert fmt.ratio(1.2849) == "1.28" and fmt.ratio(-0.001) == "0.00" and fmt.ratio(None) == "—"
    assert fmt.money(12_345.4, signed=True) == "+12,345"
    assert fmt.money(-1_234, signed=True) == "-1,234"
    assert fmt.money(None) == "—"


def test_regime_rules_follow_the_regime_constants():
    assert fmt.REGIME_RULES == (
        "盤勢分段依固定規則：價格在 12% 區間內來回達 60 個交易日以上為盤整段；"
        "其餘期間以反轉 10% 判斷轉折，漲幅達 15% 為上漲段、跌幅達 15% 為下跌段，其餘為盤整段。"
    )


def test_unverified_numbers():
    corpus = "| 總報酬率 | +12.34% | 1,047,040 |"
    text = "總報酬率 +12.34%，期末權益 1,047,040，另以 2025 年驗證，共 3 次，年化 +9.99%，2024"
    assert fmt.unverified_numbers(text, corpus) == ["+9.99%", "2024"]
    assert fmt.unverified_numbers("報酬率 12.34%", corpus) == []  # leading + may be dropped
