"""Rebuild src/trader/taiwan_stocks.json from the TWSE ISIN listings (stocks and ETFs).

uv run python scripts/build_stock_list.py
"""

import json
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

SOURCES = {
    "TWSE": ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", "TW"),
    "TPEx": ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", "TWO"),
}
KINDS = {"股票": "stock", "ETF": "etf"}
OUT = Path(__file__).resolve().parents[1] / "src" / "trader" / "taiwan_stocks.json"


class Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def fetch(url: str) -> list[list[str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "llm-agent-trader"})
    with urllib.request.urlopen(req, timeout=60) as r:
        html = r.read().decode("big5hkscs", errors="replace")
    p = Rows()
    p.feed(html)
    return p.rows


def parse(rows: list[list[str]], market: str, suffix: str) -> list[dict]:
    out, kind = [], None
    for row in rows:
        if len(row) == 1:
            kind = KINDS.get(row[0])
            continue
        if kind is None or len(row) < 5 or "　" not in row[0]:
            continue
        code, name = (part.strip() for part in row[0].split("　", 1))
        name = name.replace("*", "")  # exchange footnote marker, not part of the name
        out.append(
            {
                "symbol": f"{code}.{suffix}",
                "code": code,
                "name": name,
                "market": market,
                "kind": kind,
            }
        )
    return out


def main() -> None:
    stocks = []
    for market, (url, suffix) in SOURCES.items():
        found = parse(fetch(url), market, suffix)
        print(f"{market}: {len(found)} listings")
        stocks += found
    stocks.sort(key=lambda s: s["code"])
    OUT.write_text(json.dumps(stocks, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"wrote {len(stocks)} listings to {OUT}")


if __name__ == "__main__":
    main()
