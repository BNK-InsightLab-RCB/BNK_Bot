"""청킹 글자 보존 검증 (read-only).

금융 문서 원칙: 변환·정제는 **"글자 재배치"만, 재생성 금지**. 청킹이 본문 글자를
잃거나 바꾸면 이율·조건이 조용히 사라질 수 있으므로, MD 원본과 청크 본문의
'내용 문자'가 완전히 일치하는지 기계적으로 대조한다.

비교 방법 (두 가지를 함께 본다)
------------------------------
1. **본문 보존**: 섹션 헤더가 아닌 모든 블록의 '내용 문자'가 청크 ``body`` 에 그대로
   남아야 한다. 문자 다중집합(Counter)으로 대조하므로 손실·변조가 모두 잡힌다.
2. **섹션 헤더 이동**: 섹션 헤더 표(``| 2 | 거래 조건 |``)는 설계상 청크 본문이
   되지 않고 ``section`` 필드로 **이동**한다. 그래서 본문 비교에서는 제외하되,
   그 제목이 실제로 어떤 청크의 ``section`` 으로 살아 있는지 따로 확인한다.
   (이 구분이 없으면 정상 동작을 '데이터 손실'로 오판한다.)

- 제외 대상: ``<!-- page N -->`` 페이지 마커, ``_PLACEHOLDER_LINES``(내용 없는
  Docling placeholder), 모든 공백.
- 청크 쪽은 ``body``(verbatim 본문)만 쓴다 — ``text`` 는 컨텍스트 헤더가 붙어 있어
  원본에 없는 글자를 포함하므로 비교 대상이 아니다.

실행:  python scripts/check_chunk_conservation.py [--limit N] [경로...]
결과:  logs/check_chunk_conservation.log (덮어쓰기)
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.ingestion.processor import (  # noqa: E402
    KoreanFinanceProfile,
    chunk_md_file,
    parse_blocks,
)


def content_chars(text: str) -> Counter:
    """공백을 뺀 '내용 문자'의 다중집합. (페이지 마커·placeholder 는 parse_blocks 가 이미 제거)

    **양쪽 모두 NFC 로 정규화**한 뒤 센다. 청커는 payload 를 NFC 로 저장하는데
    (macOS NFD 경로 때문에 필수 — 안 하면 Qdrant 정확매칭 필터가 0건이 된다), 그
    정규화는 파일명뿐 아니라 **본문 글자에도 적용**된다. 원본을 정규화하지 않고
    비교하면 정상 동작이 '손실+추가'로 잡힌다 — 실제로 펀드 문서 15건이 이 이유로
    오탐했다(`零` U+F9B2→U+96F6 호환 한자, `·` U+0387→U+00B7 그리스어 구두점).
    보존의 기준은 '바이트 동일'이 아니라 '**정규화 후** 동일'이다.
    """
    return Counter(c for c in unicodedata.normalize("NFC", text) if not c.isspace())


def split_source(md: str, profile) -> tuple[str, list[str]]:
    """MD → (본문 블록 텍스트, 섹션 헤더 제목들). 청커와 동일한 판정을 쓴다."""
    bodies, titles = [], []
    for b in parse_blocks(md):
        t = profile.section_title(b)
        (titles.append(t) if t is not None else bodies.append(b.text))
    return "\n".join(bodies), titles


def check(md_path: Path) -> tuple[bool, str]:
    profile = KoreanFinanceProfile()
    chunks = chunk_md_file(md_path, profile=profile)
    src_body, titles = split_source(md_path.read_text(encoding="utf-8"), profile)

    src = content_chars(src_body)
    got = content_chars("\n".join(c.body for c in chunks))
    seen_sections = {c.section for c in chunks}
    # 헤더 제목은 NFC 로 저장되므로 비교도 그 형태로(청크 쪽이 이미 NFC).
    missing_sections = [t for t in titles if t.strip() and t.strip() not in
                        {s.strip() for s in seen_sections}]

    if src == got and not missing_sections:
        return True, (
            f"OK   {sum(src.values()):>7} chars · {len(chunks):>3} chunks · "
            f"{len(titles):>2} sections · {md_path.parent.name}"
        )
    lost = src - got          # 원본에 있는데 청크에 없음 = 데이터 손실
    added = got - src         # 청크에만 있음 = 재생성/오염
    msg = [f"FAIL {md_path.parent.name}"]
    if lost:
        msg.append(f"       lost={sum(lost.values())} {dict(list(lost.items())[:12])}")
    if added:
        msg.append(f"       added={sum(added.values())} {dict(list(added.items())[:12])}")
    if missing_sections:
        msg.append(f"       section 유실={missing_sections[:5]}")
    return False, "\n".join(msg)


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify chunking preserves every content char.")
    ap.add_argument("paths", nargs="*", help="MD 파일(생략 시 data/processed 전체)")
    ap.add_argument("--limit", type=int, default=0, help="앞 N개만 검사")
    args = ap.parse_args()

    if args.paths:
        mds = [Path(p) for p in args.paths]
    else:
        mds = sorted(settings.processed_dir.glob("*/*.md"))
    if args.limit:
        mds = mds[: args.limit]

    lines = [f"# chunk conservation check · {len(mds)} documents"]
    ok = 0
    for md in mds:
        try:
            passed, msg = check(md)
        except Exception as e:  # 청킹 자체가 터지는 것도 실패로 기록
            passed, msg = False, f"FAIL {md.parent.name} :: {type(e).__name__}: {e}"
        ok += passed
        if not passed:
            lines.append(msg)
        elif len(mds) <= 20:
            lines.append(msg)

    verdict = f"\n== {ok}/{len(mds)} passed =="
    lines.append(verdict)
    report = "\n".join(lines)
    print(report)

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    (settings.logs_dir / "check_chunk_conservation.log").write_text(report, encoding="utf-8")
    sys.exit(0 if ok == len(mds) else 1)


if __name__ == "__main__":
    main()
