from pathlib import Path

from trader import viewer

APP = (Path(viewer.__file__).parent / "app.js").read_text(encoding="utf-8")


def _function(name: str) -> str:
    body = APP[APP.index(f"function {name}(") :]
    return body[: body.index("\n}\n")]


def test_group_digits_is_the_only_number_formatting_in_the_frontend():
    """Text numbers come from trader.fmt; groupDigits only labels chart axes and the readout."""
    assert APP.count("function groupDigits(") == 1
    grouping = r"\B(?=(\d{3})+(?!\d))"
    assert APP.count(grouping) == 1 and grouping in _function("groupDigits")
    readout = _function("readout")
    rest = APP.replace(_function("groupDigits"), "").replace(readout, "")
    for line in rest.splitlines():
        if "groupDigits(" in line:
            assert line.lstrip().startswith("const fmt"), line
    assert readout.count("groupDigits(") >= 1
