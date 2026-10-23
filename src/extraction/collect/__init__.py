"""Collecting raw texts. For every document a collector writes the text the model reads,
data/texts/<doc_type>/<doc_id>.txt, and the record it was made from,
data/scraped/<doc_type>/<doc_id>.json: where it came from plus the scraped fields. Both are
scrubbed of contact details on the way in."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from extraction.collect.scrub import scrub


def existing_ids(data_dir: Path, doc_type: str) -> set[str]:
    return {path.stem for path in (data_dir / "texts" / doc_type).glob("*.txt")}


def save(
    data_dir: Path,
    doc_type: str,
    doc_id: str,
    *,
    text: str,
    fields: dict[str, Any],
    source: dict[str, Any],
) -> None:
    """`text` and `fields` are scrubbed; `source` (URL, dates) is kept as it is."""
    record = {
        "doc_id": doc_id,
        **source,
        "collected_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **_scrubbed(fields),
    }
    _write(data_dir / "texts" / doc_type / f"{doc_id}.txt", scrub(text))
    record_json = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    _write(data_dir / "scraped" / doc_type / f"{doc_id}.json", record_json)


def _scrubbed(value: Any) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, list):
        return [_scrubbed(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrubbed(item) for key, item in value.items()}
    return value


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
