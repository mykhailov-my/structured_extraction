"""A local web page for checking and writing the golden labels: `python main.py label`.

The page shows one posting beside a form holding its label from data/golden/job/<doc_id>.json,
if there is one. Saving writes the label back, so nobody has to match files by doc id, and
marks the posting verified in data/golden/verified.txt: a person has checked its label
against the text. Claude's labels, kept unchanged in data/golden/claude/job/, are compared
only with verified ones. The page then shows where the two differ, scored the way `eval`
scores a model, with the verified label as the expected answer.
"""

import json
import logging
import random
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import mean
from typing import Any

from pydantic import ValidationError

from extraction.collect import write_file
from extraction.data import load_documents
from extraction.evaluate import leaf_fields, score_document
from extraction.schemas import (
    CandidateLocation,
    CompanyType,
    Country,
    Currency,
    Domain,
    Employment,
    JobPosting,
    Language,
    LanguageLevel,
    LegalCondition,
    SalaryPeriod,
    Seniority,
    SkillLevel,
    SoftSkill,
    WorkFormat,
)
from extraction.skills import AREAS, OTHER

log = logging.getLogger(__name__)

DOC_TYPE = "job"  # the page's form is a JobPosting's
DEFAULT_PORT = 8765
PAGE = Path(__file__).with_name("labelling.html")
MAX_BODY = 1_000_000  # bytes; a label is a few kilobytes
OPTIONS: dict[str, Any] = {
    name: [member.value for member in enum]
    for name, enum in {
        "seniority": Seniority,
        "company_type": CompanyType,
        "domain": Domain,
        "employment": Employment,
        "work_formats": WorkFormat,
        "candidate_location": CandidateLocation,
        "country": Country,
        "language": Language,
        "language_level": LanguageLevel,
        "skill_level": SkillLevel,
        "soft_skill": SoftSkill,
        "legal_condition": LegalCondition,
        "currency": Currency,
        "period": SalaryPeriod,
    }.items()
}
# The hard skills with the names postings use for them, for the page's search.
OPTIONS["hard_skill"] = [
    {"id": skill, "name": names[0], "area": area, "aliases": list(names[1:])}
    for area, skills in AREAS.items()
    for skill, names in skills.items()
] + [{"id": OTHER, "name": "Other: anything not listed", "area": "", "aliases": []}]


class LabelStore:
    """The texts to label, your labels of them and Claude's."""

    def __init__(self, data_dir: Path) -> None:
        self._texts = {doc.doc_id: doc.text for doc in load_documents(data_dir, DOC_TYPE)}
        # A mixed order, the same every time the page opens.
        self.order = random.Random(0).sample(sorted(self._texts), len(self._texts))
        self.known = set(self.order)
        self._yours = data_dir / "golden" / DOC_TYPE
        self._claude = data_dir / "golden" / "claude" / DOC_TYPE
        self._verified = data_dir / "golden" / "verified.txt"
        self._fields = leaf_fields(JobPosting)

    def verified(self) -> set[str]:
        """The postings whose label a person has checked and saved on the page."""
        if not self._verified.exists():
            return set()
        return set(self._verified.read_text(encoding="utf-8").split())

    def postings(self) -> list[dict[str, Any]]:
        verified = self.verified()
        return [
            {
                "doc_id": doc_id,
                "title": self._texts[doc_id].split("\n", 1)[0],
                "done": doc_id in verified,
            }
            for doc_id in self.order
        ]

    def posting(self, doc_id: str) -> dict[str, Any]:
        return {
            "doc_id": doc_id,
            "text": self._texts[doc_id],
            "label": _read(self._yours, doc_id),
            "verified": doc_id in self.verified(),
            "comparison": self.comparison(doc_id),
        }

    def save(self, doc_id: str, label: Any) -> list[str]:
        """Store your label, verified, if it matches the schema; otherwise the validation
        errors."""
        try:
            posting = JobPosting.model_validate(label)
        except ValidationError as e:
            return [
                f"{'.'.join(str(part) for part in error['loc']) or '(root)'}: {error['msg']}"
                for error in e.errors()
            ]
        write_file(self._yours / f"{doc_id}.json", dump_label(posting.model_dump(mode="json")))
        verified = sorted(self.verified() | {doc_id})
        write_file(self._verified, "".join(f"{verified_id}\n" for verified_id in verified))
        return []

    def comparison(self, doc_id: str) -> dict[str, Any] | None:
        """Where Claude's label differs from yours; None until yours is verified."""
        if doc_id not in self.verified():
            return None
        yours, claude = _read(self._yours, doc_id), _read(self._claude, doc_id)
        if yours is None or claude is None:
            return None
        scores, misses = score_document(self._fields, yours, claude)
        return {
            "agreement": mean(scores.values()),
            "differences": [
                {"field": field, "yours": want, "claude": got} for field, _, want, got in misses
            ],
        }

    def agreement(self) -> dict[str, Any] | None:
        """Per field, how far Claude's labels match yours over the verified postings: the
        accuracy Claude would get with your labels as the golden set."""
        per_field: dict[str, list[float]] = {}
        compared = 0
        for doc_id in sorted(self.verified() & self.known):
            yours, claude = _read(self._yours, doc_id), _read(self._claude, doc_id)
            if yours is None or claude is None:
                continue
            compared += 1
            scores, _ = score_document(self._fields, yours, claude)
            for field, value in scores.items():
                per_field.setdefault(field, []).append(value)
        if not compared:
            return None
        fields = {field: mean(values) for field, values in per_field.items()}
        return {"postings": compared, "agreement": mean(fields.values()), "fields": fields}


def dump_label(label: dict[str, Any]) -> str:
    """A label as JSON with one requirement a line, easy to read and to diff."""
    lines = []
    for key, value in label.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            items = ",\n".join(f"    {json.dumps(item, ensure_ascii=False)}" for item in value)
            lines.append(f'  "{key}": [\n{items}\n  ]')
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}")
    return "{\n" + ",\n".join(lines) + "\n}\n"


def make_server(store: LabelStore, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """The page's server, on this machine only. Port 0 picks a free one."""
    handler = type("Handler", (_Handler,), {"store": store})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve(store: LabelStore, *, port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    with make_server(store, port) as server:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        log.info("labelling page at %s - Ctrl+C to stop", url)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log.info("stopped")


def _read(folder: Path, doc_id: str) -> dict[str, Any] | None:
    path = folder / f"{doc_id}.json"
    if not path.exists():
        return None
    return JobPosting.model_validate_json(path.read_bytes()).model_dump(mode="json")


class _Handler(BaseHTTPRequestHandler):
    store: LabelStore
    _PREFIX = "/api/postings/"

    def do_GET(self) -> None:
        if not self._local():
            return
        doc_id = self._doc_id()
        if self.path == "/":
            self._send(HTTPStatus.OK, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/postings":
            body = {
                "postings": self.store.postings(),
                "options": OPTIONS,
                "agreement": self.store.agreement(),
            }
            self._json(HTTPStatus.OK, body)
        elif doc_id is not None:
            self._json(HTTPStatus.OK, self.store.posting(doc_id))
        else:
            self._json(HTTPStatus.NOT_FOUND, {"errors": [f"no such page: {self.path}"]})

    def do_PUT(self) -> None:
        if not self._local():
            return
        doc_id = self._doc_id()
        if doc_id is None:
            self._json(HTTPStatus.NOT_FOUND, {"errors": [f"no such posting: {self.path}"]})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            label = json.loads(self.rfile.read(min(length, MAX_BODY)))
        except json.JSONDecodeError as e:
            self._json(HTTPStatus.BAD_REQUEST, {"errors": [f"not JSON: {e}"]})
            return
        errors = self.store.save(doc_id, label)
        if errors:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"errors": errors})
            return
        body = {
            "comparison": self.store.comparison(doc_id),
            "agreement": self.store.agreement(),
        }
        self._json(HTTPStatus.OK, body)

    def _local(self) -> bool:
        """Refuse requests addressed to another host name: a web page elsewhere could
        otherwise reach this server by pointing its own domain at 127.0.0.1."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host in ("127.0.0.1", "localhost"):
            return True
        self._json(HTTPStatus.FORBIDDEN, {"errors": ["open the page at 127.0.0.1"]})
        return False

    def _doc_id(self) -> str | None:
        if not self.path.startswith(self._PREFIX):
            return None
        doc_id = self.path[len(self._PREFIX) :]
        return doc_id if doc_id in self.store.known else None

    def _json(self, status: HTTPStatus, body: Any) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self._send(status, payload, "application/json; charset=utf-8")

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass  # a line per request would bury the useful output
