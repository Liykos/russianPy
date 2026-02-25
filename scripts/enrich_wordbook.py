#!/usr/bin/env python3
"""
将原始词表 CSV/TSV 转成词书 JSON，并做基础富化。

输入列支持：
- russian (必填)
- chinese (必填)
- example (可选)
- derivatives (可选，逗号分隔)
- pronunciation (可选)
- note (可选)

用法：
python scripts/enrich_wordbook.py \
  --input data/raw/tem4.csv \
  --output data/wordbooks/tem4.json \
  --slug tem4-russian-core \
  --title "俄语专四核心词汇"
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


TRANSLIT_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def transliterate_ru(word: str) -> str:
    parts = []
    for ch in word.lower():
        parts.append(TRANSLIT_MAP.get(ch, ch))
    return "".join(parts)


def read_rows(path: Path) -> list[dict]:
    dialect = csv.excel
    if path.suffix.lower() == ".tsv":
        dialect = csv.excel_tab
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, dialect=dialect)
        return list(reader)


def normalize_entry(raw: dict, order_index: int) -> dict | None:
    russian = (raw.get("russian") or "").strip()
    chinese = (raw.get("chinese") or "").strip()
    if not russian or not chinese:
        return None

    pronunciation = (raw.get("pronunciation") or "").strip()
    if not pronunciation:
        pronunciation = transliterate_ru(russian)

    example = (raw.get("example") or raw.get("exampleSentence") or "").strip() or None
    derivatives = (raw.get("derivatives") or "").strip()
    note = (raw.get("note") or "").strip() or None

    # 标准化衍生词为逗号分隔字符串
    if derivatives:
        derivatives = ",".join([part.strip() for part in derivatives.split(",") if part.strip()])
    else:
        derivatives = None

    return {
        "russian": russian,
        "chinese": chinese,
        "pronunciation": pronunciation,
        "exampleSentence": example,
        "derivatives": derivatives,
        "note": note,
        "orderIndex": order_index,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="CSV/TSV 文件路径")
    parser.add_argument("--output", required=True, help="词书 JSON 输出路径")
    parser.add_argument("--slug", required=True, help="词书唯一标识")
    parser.add_argument("--title", required=True, help="词书标题")
    parser.add_argument("--description", default="", help="词书描述")
    parser.add_argument("--language", default="ru", help="语言，默认 ru")
    parser.add_argument("--level", default="", help="词书等级，如 TEM4")
    parser.add_argument("--source", default="Custom", help="来源")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = read_rows(in_path)
    entries = []
    for idx, row in enumerate(rows):
        normalized = normalize_entry(row, idx)
        if normalized:
            entries.append(normalized)

    payload = {
        "slug": args.slug,
        "title": args.title,
        "description": args.description,
        "language": args.language,
        "level": args.level or None,
        "source": args.source,
        "entries": entries,
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done. entries={len(entries)} output={out_path}")


if __name__ == "__main__":
    main()
