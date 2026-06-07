"""Ingestion pipeline: data/ files -> clean -> chunk -> embed (BGE-M3) -> Qdrant.

Run inside the backend container:
    docker compose run --rm backend python -m ingestion.ingest
Options:
    --recreate   drop & recreate the collection before loading
    --data DIR   source directory (default: data)
"""
import argparse
import hashlib
import re
import sys
import uuid
from pathlib import Path
from typing import Iterable, List

import ftfy
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client.http import models as qm

from app.config import settings
from app.embeddings import embed_texts
from app.qdrant_store import ensure_collection, get_client

SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".csv"}


# ---------- load ----------
def read_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def read_docx(path: Path) -> str:
    import docx
    doc = docx.Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text for c in row.cells))
    return "\n".join(parts)


def raw_corruption_ratio(path: Path) -> float:
    """Fraction of literal '?' (0x3F) bytes in the raw file. A high value means
    the source's non-Latin text was destroyed at export time (saved to an
    encoding that can't represent Cyrillic) — unrecoverable from this file."""
    raw = path.read_bytes()
    if not raw:
        return 1.0
    return raw.count(0x3F) / len(raw)


def read_text(path: Path) -> str:
    """Decode robustly. BOM/UTF-8 first, then charset detection, then cp1251.
    Deliberately avoids blind UTF-16 fallback, which would turn a file of
    literal '?' bytes into CJK garbage and hide the corruption."""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    from charset_normalizer import from_bytes
    best = from_bytes(raw).best()
    if best is not None:
        enc = (best.encoding or "").lower()
        if not enc.startswith("utf_16") and not enc.startswith("utf-16"):
            return str(best)
    return raw.decode("cp1251", errors="ignore")


def read_csv(path: Path) -> str:
    """Flatten a CSV into readable lines (auto-detect ; or , delimiter)."""
    text = read_text(path)
    import csv
    import io
    delim = ";" if text[:2000].count(";") >= text[:2000].count(",") else ","
    rows = csv.reader(io.StringIO(text), delimiter=delim)
    return "\n".join(" | ".join(cell.strip() for cell in row if cell.strip()) for row in rows)


def _broken_ratio(text: str) -> float:
    """Fraction of chars that are '?' or the replacement char — signals a file
    whose non-ASCII content was destroyed at export time."""
    if not text:
        return 1.0
    bad = text.count("?") + text.count("�")
    return bad / len(text)


def load_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return read_pdf(path)
    if ext == ".docx":
        return read_docx(path)
    if ext == ".csv":
        return read_csv(path)
    if ext in (".txt", ".md"):
        return read_text(path)
    return ""


# ---------- clean ----------
def clean_text(text: str) -> str:
    text = ftfy.fix_text(text)
    text = text.replace("­", "")           # soft hyphens
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def guess_lang(text: str) -> str:
    sample = text[:2000]
    cyr = len(re.findall(r"[а-яёңүөъ]", sample, flags=re.IGNORECASE))
    lat = len(re.findall(r"[a-z]", sample, flags=re.IGNORECASE))
    # Kyrgyz-specific letters
    if re.search(r"[ңүөъ]", sample, flags=re.IGNORECASE):
        return "ky"
    if cyr > lat:
        return "ru"
    if lat > 0:
        return "en"
    return "ru"


# ---------- chunk ----------
def chunk_text(text: str) -> List[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=900,
        chunk_overlap=150,
        separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " ", ""],
    )
    return [c.strip() for c in splitter.split_text(text) if c.strip()]


# ---------- pipeline ----------
def iter_files(data_dir: Path) -> Iterable[Path]:
    for p in sorted(data_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in SUPPORTED:
            yield p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--recreate", action="store_true")
    args = ap.parse_args()

    data_dir = Path(args.data)
    if not data_dir.exists():
        print(f"[!] Data dir '{data_dir}' not found.", file=sys.stderr)
        sys.exit(1)

    client = get_client()
    ensure_collection(client, recreate=args.recreate)

    files = list(iter_files(data_dir))
    if not files:
        print(f"[!] No supported files ({', '.join(SUPPORTED)}) in {data_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[i] Found {len(files)} files. Collection: {settings.qdrant_collection}")
    seen_hashes = set()
    total_chunks = 0

    for path in files:
        # Detect destroyed-encoding files at the byte level (literal '?' bytes).
        if path.suffix.lower() in (".txt", ".md", ".csv") and raw_corruption_ratio(path) >= 0.2:
            print(f"  - SKIP (corrupted encoding, Cyrillic text lost): {path.name}")
            continue
        raw = load_file(path)
        text = clean_text(raw)
        if not text:
            print(f"  - skip (empty): {path.name}")
            continue
        if _broken_ratio(text) >= 0.2:
            print(f"  - SKIP (corrupted text): {path.name}")
            continue
        lang = guess_lang(text)
        chunks = chunk_text(text)

        points = []
        for ch in chunks:
            h = hashlib.sha256(ch.encode("utf-8")).hexdigest()
            if h in seen_hashes:          # dedup identical chunks across files
                continue
            seen_hashes.add(h)
            points.append((ch, h))

        if not points:
            continue

        vectors = embed_texts([c for c, _ in points])
        qpoints = []
        for (ch, h), vec in zip(points, vectors):
            qpoints.append(
                qm.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, h)),
                    vector=vec,
                    payload={
                        "text": ch,
                        "title": path.stem,
                        "source": path.name,
                        "doc_type": path.suffix.lower().lstrip("."),
                        "lang": lang,
                        "updated_at": int(path.stat().st_mtime),
                    },
                )
            )

        # batch upsert
        for i in range(0, len(qpoints), 64):
            client.upsert(
                collection_name=settings.qdrant_collection,
                points=qpoints[i:i + 64],
            )
        total_chunks += len(qpoints)
        print(f"  + {path.name}: {len(qpoints)} chunks ({lang})")

    info = client.get_collection(settings.qdrant_collection)
    print(f"[✓] Done. Upserted {total_chunks} chunks. Points in collection: {info.points_count}")


if __name__ == "__main__":
    main()
