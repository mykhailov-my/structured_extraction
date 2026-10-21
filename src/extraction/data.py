"""The corpus and the golden set on disk:

- data/texts/<doc_type>/<doc_id>.txt: raw texts (what the crawler will write)
- data/golden/<doc_type>/<doc_id>.json: hand-labelled expected output for some of them
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from extraction.schemas import SCHEMAS


@dataclass(frozen=True)
class Document:
    doc_id: str
    doc_type: str
    text: str

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:12]


def load_documents(data_dir: Path, doc_type: str) -> list[Document]:
    paths = sorted((data_dir / "texts" / doc_type).glob("*.txt"))
    return [Document(path.stem, doc_type, path.read_text(encoding="utf-8")) for path in paths]


def golden_paths(data_dir: Path, doc_type: str) -> list[Path]:
    return sorted((data_dir / "golden" / doc_type).glob("*.json"))


def load_golden(data_dir: Path, doc_type: str) -> dict[str, BaseModel]:
    """Golden labels by doc id. A file that doesn't match the schema is an error."""
    schema = SCHEMAS[doc_type]
    golden = {}
    for path in golden_paths(data_dir, doc_type):
        try:
            golden[path.stem] = schema.model_validate_json(path.read_bytes())
        except ValidationError as e:
            raise ValueError(f"{path}: {e}") from e
    return golden
