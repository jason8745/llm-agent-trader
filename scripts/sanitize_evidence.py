"""Strip local paths from evidence before it is committed or posted.

python scripts/sanitize_evidence.py <file>...      (rewrites in place; '-' filters stdin)
"""

import re
import sys
from pathlib import Path

RULES = [
    (re.compile(r"/private/tmp/claude-\d+/[^\s\"'`)]*?/scratchpad"), "<scratch>"),
    (re.compile(str(Path(__file__).resolve().parents[1])), "<repo>"),
    (re.compile(re.escape(str(Path.home()))), "~"),
]


def clean(text: str) -> str:
    for pattern, repl in RULES:
        text = pattern.sub(repl, text)
    return text


if __name__ == "__main__":
    if sys.argv[1:] == ["-"]:
        sys.stdout.write(clean(sys.stdin.read()))
    for name in sys.argv[1:]:
        if name != "-":
            p = Path(name)
            p.write_text(clean(p.read_text(encoding="utf-8")), encoding="utf-8")
