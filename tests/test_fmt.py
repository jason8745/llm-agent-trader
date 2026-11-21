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
