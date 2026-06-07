"""QC: review product names stored in Qdrant after a batch ingest.

Two checks, both read-only (never touch the collection):

1. SUSPICIOUS  — product names that look malformed (start with a digit/paren,
   too short, or still contain a document-type word like 설명서/약관/심의). Catches
   NEW filename patterns the extraction profile doesn't handle yet.

2. DRIFT       — stored product name vs what the CURRENT profile would produce
   from the same source_file. Mismatches are exactly what a re-ingest would
   change, so this is the human-review list when the profile's rules change.

Usage
-----
    python scripts/check_product_names.py            # both checks
    python scripts/check_product_names.py --suspicious-only
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.ingestion.processor import KoreanFinanceProfile, _nfc  # noqa: E402
from src.ingestion.qdrant import QdrantStore  # noqa: E402

_DOC_WORDS = ("설명서", "약관", "특약", "규약", "심의", "신탁계약서", "주요내용")


def is_suspicious(name: str) -> bool:
    return (
        bool(re.match(r"^[\(\[\d]", name))      # starts with digit / ( / [
        or len(name.strip()) < 2                # too short
        or any(w in name for w in _DOC_WORDS)   # leftover doc-type word
    )


def collect(store: QdrantStore) -> dict[str, str]:
    """{source_file: product_name} over the whole collection."""
    out: dict[str, str] = {}
    nxt = None
    while True:
        pts, nxt = store.client.scroll(store.collection, limit=500, offset=nxt, with_payload=True)
        for p in pts:
            out.setdefault(p.payload["source_file"], p.payload["product_name"])
        if nxt is None:
            break
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Review stored product names (read-only).")
    ap.add_argument("--suspicious-only", action="store_true")
    args = ap.parse_args()

    store = QdrantStore(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection_name,
        api_key=settings.qdrant_api_key,
    )
    stored = collect(store)
    profile = KoreanFinanceProfile()
    print(f"collection '{store.collection}': {len(stored)} unique source files\n")

    # 1) suspicious
    suspicious = sorted((n, s) for s, n in stored.items() if is_suspicious(n))
    print(f"== SUSPICIOUS product names: {len(suspicious)} ==")
    for name, src in suspicious:
        print(f"  {name!r}   <- {src}")

    if args.suspicious_only:
        return

    # 2) drift (stored vs current rules) — the human-review list before re-ingest
    drift = []
    for src, oldname in sorted(stored.items()):
        new = _nfc(profile.product_name(src))
        if new != oldname:
            drift.append((oldname, new, src))
    print(f"\n== DRIFT (stored → current-rule): {len(drift)} would change on re-ingest ==")
    for old, new, src in drift:
        print(f"  {old!r}\n   → {new!r}")
    if not drift:
        print("  (none — stored names match current rules)")


if __name__ == "__main__":
    main()
