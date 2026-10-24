"""Pages kept between crawls, so a better parser reads them again without asking anyone:
<cache>/pages/<key>.html.gz, gzipped, where a key is "<yyyymmddhhmmss>-<job id>". What a
source had no page for goes to <cache>/failed.txt, so it isn't asked for again."""

import gzip
from pathlib import Path


def page_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / "pages" / f"{key}.html.gz"


def cached_keys(cache_dir: Path) -> set[str]:
    return {path.name.removesuffix(".html.gz") for path in (cache_dir / "pages").glob("*.html.gz")}


def read_page(path: Path) -> str:
    return gzip.decompress(path.read_bytes()).decode("utf-8")


def write_page(cache_dir: Path, key: str, html: str) -> None:
    path = page_path(cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".tmp")  # an interrupted write leaves no broken page behind
    partial.write_bytes(gzip.compress(html.encode("utf-8")))
    partial.replace(path)


def failed(cache_dir: Path) -> set[str]:
    path = cache_dir / "failed.txt"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return {line.split()[0] for line in lines if line}


def remember_failure(cache_dir: Path, key: str, reason: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    with (cache_dir / "failed.txt").open("a", encoding="utf-8") as file:
        file.write(f"{key} {reason}\n")
