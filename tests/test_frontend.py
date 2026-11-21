import re
from pathlib import Path

from trader import viewer

APP = (Path(viewer.__file__).parent / "app.js").read_text(encoding="utf-8")


def test_group_digits_is_the_only_number_formatting_in_the_frontend():
    assert APP.count("function groupDigits(") == 1
    grouping = r"\B(?=(\d{3})+(?!\d))"
    assert APP.count(grouping) == 1, "thousands grouping must live only in groupDigits"
    body = APP[APP.index("function groupDigits(") :]
    body = body[: body.index("\n}\n")]
    assert grouping in body
    uses = re.findall(r"groupDigits\(", APP)
    assert len(uses) == 4, "groupDigits is defined once and used only by the three chart price formats"
    for line in APP.splitlines():
        if "groupDigits(v," in line:
            assert line.lstrip().startswith("const fmt"), line
