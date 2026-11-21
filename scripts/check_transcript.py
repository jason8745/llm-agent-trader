"""Turn a `claude -p --output-format stream-json` log into a readable transcript and check it.

    python scripts/check_transcript.py <stream.jsonl> <transcript.md>

Checks: every number in the assistant's prose appears verbatim in some tool result, and the
prose avoids the colloquial terms the skill's glossary forbids. Exits 1 on any violation.
"""

import json
import sys

from trader.fmt import unverified_numbers

GLOSSARY = [
    "訓練段",
    "測試段",
    "賺了",
    "趴",
    "最多虧",
    "跌最深",
    "硬凹",
    "背答案",
    "上車",
    "下車",
    "躺平",
    "抱著不動",
]
# Colloquialisms observed in real sessions; each has a rewrite example in the skill.
OBSERVED = [
    "方向對了",
    "多賺",
    "掉到",
    "越短越好",
    "適合誰",
    "錯過了",
    "不夠可靠",
    "一路上漲",
    "追不上",
    "輸給",
    "代價很大",
    "沒參與到",
    "比較好",
    "我做了",
    "反而變差",
    "想讓",
    "一直持有",
    "低很多",
    "只虧",
    "反應不了",
    "我對",
]
BANNED = GLOSSARY + OBSERVED


def main(stream_path: str, out_path: str) -> int:
    prose, results, md = [], [], []
    for line in open(stream_path, encoding="utf-8"):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = ev.get("message") or {}
        if ev.get("type") == "assistant":
            for block in msg.get("content", []):
                if block.get("type") == "text":
                    prose.append(block["text"])
                    md.append(f"### Claude\n\n{block['text']}\n")
                elif block.get("type") == "tool_use":
                    md.append(
                        f"### Tool call: `{block['name']}`\n\n```json\n{json.dumps(block['input'], ensure_ascii=False, indent=2)}\n```\n"
                    )
        elif ev.get("type") == "user":
            for block in msg.get("content", []) if isinstance(msg.get("content"), list) else []:
                if block.get("type") == "tool_result":
                    content = block.get("content")
                    text = (
                        content
                        if isinstance(content, str)
                        else "".join(c.get("text", "") for c in content or [])
                    )
                    results.append(text)
                    md.append(
                        f"<details><summary>Tool result</summary>\n\n```\n{text}\n```\n</details>\n"
                    )
    corpus = "\n".join(results)
    problems = []
    for p in prose:
        problems += [
            f"number not found in any tool result: {n}" for n in unverified_numbers(p, corpus)
        ]
        problems += [f"banned colloquial term: {w}" for w in BANNED if w in p]
    md.append("## Automated checks\n")
    md.append(
        "\n".join(f"- {x}" for x in problems)
        if problems
        else "- Every number in Claude's prose appears verbatim in a tool result.\n- No banned colloquial terms."
    )
    open(out_path, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(problems) if problems else "transcript checks passed")
    print(f"assistant messages: {len(prose)}, tool results: {len(results)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
