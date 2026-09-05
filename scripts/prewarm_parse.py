"""파싱만 미리 병렬로 돌려 MD 캐시를 채운다 (적재 전 준비 단계).

**왜 분리하는가.** 적재는 `파싱 → 청킹 → 임베딩 → upsert` 를 문서마다 순차로 도는데,
두 단계의 자원이 다르다:
  - 파싱   = CPU 바운드 → **코어 수만큼 병렬화 가능**
  - 임베딩 = MPS(GPU 1개) → 병렬화해도 경합만 생김

실측(전체 코퍼스): 파싱 19.8시간 + 임베딩 17.5시간. 순차로 돌면 37시간인데,
파싱을 먼저 N개 프로세스로 끝내두면 이후 적재에서 파싱이 **캐시 히트로 0** 이 된다.
→ 파싱 19.8h ÷ 5 ≈ 4h + 임베딩 17.5h ≈ **21시간**(약 43% 단축).

**품질에는 영향이 없다** — 같은 `PDFParser`, 같은 설정으로 순서만 바꾼다.
파서는 MD 가 이미 있으면 건너뛰므로 몇 번을 돌려도 안전하고, 중단 후 재개도 된다.

실행:
    python scripts/prewarm_parse.py                     # data_root 전체
    python scripts/prewarm_parse.py <경로> --workers 5
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.ingestion.pipeline import find_documents  # noqa: E402

_parser = None  # 워커 프로세스마다 1개(Docling 모델 로딩이 무거워 재사용해야 한다)


def _init() -> None:
    global _parser
    from src.ingestion.parser import PDFParser

    _parser = PDFParser(settings.processed_dir)


def _parse_one(path_str: str) -> tuple[str, str, float]:
    """(파일명, 상태, 소요초). 실패해도 예외를 올리지 않는다 — 배치가 멈추면 안 된다."""
    t = time.time()
    p = Path(path_str)
    try:
        _parser.parse(p)
        return p.name, "ok", time.time() - t
    except Exception as e:
        return p.name, f"fail: {type(e).__name__}: {e}"[:160], time.time() - t


def main() -> None:
    ap = argparse.ArgumentParser(description="Pre-warm the MD parse cache in parallel.")
    ap.add_argument("roots", nargs="*", help="대상 디렉토리(생략 시 settings.data_root)")
    # 기본 5: 성능코어 수에 맞춘다. 워커마다 Docling 모델이 뜨므로 메모리를 본다.
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    roots = [Path(r) for r in args.roots] or [settings.data_root]
    docs: list[Path] = []
    for r in roots:
        docs += find_documents(r)

    # 이미 MD 가 있으면 건너뛴다(파서도 같은 판단을 하지만, 미리 걸러야 진행률이 정확하다)
    todo = [p for p in docs if not (settings.processed_dir / p.stem / f"{p.stem}.md").exists()]
    print(f"대상 {len(docs):,}건 중 미파싱 {len(todo):,}건 · 워커 {args.workers}개")
    if not todo:
        print("파싱할 문서 없음")
        return

    t0 = time.time()
    ok = fail = 0
    # spawn: fork 로는 부모의 torch/Docling 상태가 워커에 섞여 불안정할 수 있다.
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers, initializer=_init) as pool:
        for i, (name, status, dt) in enumerate(pool.imap_unordered(_parse_one, [str(p) for p in todo]), 1):
            if status == "ok":
                ok += 1
            else:
                fail += 1
                print(f"  FAIL {name[:60]} :: {status}", flush=True)
            if i % 25 == 0 or i == len(todo):
                el = time.time() - t0
                eta = (len(todo) - i) * el / i / 3600
                print(f"  [{i}/{len(todo)}] ok={ok} fail={fail} · "
                      f"{el/i:.1f}초/건 · 잔여 {eta:.1f}시간", flush=True)

    print(f"\n완료: ok={ok} fail={fail} · {(time.time()-t0)/3600:.2f}시간")


if __name__ == "__main__":
    main()
