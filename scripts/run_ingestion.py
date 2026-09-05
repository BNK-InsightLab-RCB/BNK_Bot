"""CLI: batch-ingest a directory tree of PDFs into Qdrant.

Walks ``root`` recursively, routes each PDF through the pipeline, isolates
failures, and writes a JSON report. Re-runs are idempotent (deterministic point
ids); pass ``--recreate`` for a clean rebuild of the collection.

Examples
--------
    # ingest only 예금 (default root = settings.raw_dir), fresh collection
    python scripts/run_ingestion.py --recreate

    # smoke test: first 3 PDFs only
    python scripts/run_ingestion.py --limit 3

    # a specific subtree
    python scripts/run_ingestion.py /path/to/Data_PDF/예금/설명서
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.ingestion.pipeline import find_documents, ingest_directory, ingest_paths  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch-ingest PDFs into Qdrant.")
    ap.add_argument("root", nargs="?", default=str(settings.raw_dir),
                    help="directory to ingest recursively (default: settings.raw_dir)")
    ap.add_argument("--recreate", action="store_true",
                    help="wipe and recreate the collection before ingesting")
    ap.add_argument("--limit", type=int, default=0,
                    help="process only N documents (from --offset)")
    # 오프셋이 필요한 이유: 대형 카테고리를 **여러 프로세스로 쪼개 돌기** 위해서다.
    # 한 프로세스로 642건(평균 185쪽)을 연속 처리하면 Python 힙·파서 객체가 누적돼
    # 후반부에 스와핑이 심해진다(실측: 2.2분/건 → 7.0분/건, 잔여 추정 23h → 72h).
    # --offset/--limit 로 100건씩 끊으면 배치마다 프로세스가 새로 떠 메모리가 반환된다.
    ap.add_argument("--offset", type=int, default=0,
                    help="skip the first N documents (배치 분할용)")
    args = ap.parse_args()

    root = Path(args.root)
    t0 = time.time()
    if args.limit or args.offset:
        all_docs = find_documents(root)
        end = args.offset + args.limit if args.limit else len(all_docs)
        docs = all_docs[args.offset : end]
        print(f"[slice {args.offset}:{end}] ingesting {len(docs)} of {len(all_docs)} documents under {root}")
        summary = ingest_paths(docs, recreate=args.recreate)
    else:
        summary = ingest_directory(root, recreate=args.recreate)
    summary["elapsed_sec"] = round(time.time() - t0, 1)

    report = settings.logs_dir / "ingestion_report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n==== INGESTION SUMMARY ====")
    print(f"root   = {root}")
    print(f"ok={summary['ok']}  failed={summary['failed']}  total={summary['total']}")
    print(f"chunks={summary['chunks']}  points_in_collection={summary['points_in_collection']}")
    print(f"elapsed={summary['elapsed_sec']}s")
    if summary["failures"]:
        print("failures:")
        for f in summary["failures"]:
            print(f"  - {f['file']} :: {f['error'][:140]}")
    print(f"report -> {report}")


if __name__ == "__main__":
    main()
