"""카테고리 층화 평가셋 생성 (결정론적 · 재현 가능).

**왜 필요한가.** 기존 `eval_retrieval.py` 의 gold 15문항은 **전부 예금**인데, 예금은
지금 코퍼스의 **1.2%**(2,785/234,050)다. 펀드가 78.5% 를 차지한다.
즉 그 평가는 "가장 희귀한 것 찾기"만 재고 있어서, 나머지 98.8% 에 대해 아무것도
말해주지 않는다. 문항이 15개뿐이라 1~2개 차이가 전부 노이즈에 묻히기도 한다.

**무엇을 재는가.** "특정 상품을 23만 청크 속에서 찾아내는 능력"이다. 이것이 지금
진단된 결함(희귀 상품이 펀드 문서 더미에 파묻힘)과 정확히 대응한다.

**왜 이 방식이 안전한가(= 내가 사실을 지어낼 여지가 없다).**
질문은 **색인에 실제로 존재하는 product_name** 에 카테고리별 템플릿을 씌워 만들고,
정답은 "그 product_name 이 검색 결과에 나오는가"로만 판정한다. 문서 내용을 읽고
답을 창작하지 않으므로 gold 가 틀릴 수 없다.

**한계(반드시 같이 읽을 것).** 이 평가셋은 *상품 탐색*만 잰다. 문서 내용을 이해해
답하는 능력은 `eval_answer.py` 가 따로 잰다. 둘을 섞어 읽지 말 것.

실행:  python scripts/build_eval_set.py [--per-category 12]
출력:  eval/eval_set.json   (시드 고정 → 매번 같은 문항)
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import unicodedata
from collections import Counter as collections_Counter, defaultdict
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from qdrant_client import QdrantClient  # noqa: E402

from src.config import settings  # noqa: E402

SEED = 20260905

# 카테고리별로 실제 고객이 쓸 법한 어투. 상품명은 그대로 넣고 나머지만 바꾼다.
TEMPLATES = {
    "예금":    ["{n} 어떤 상품이야?", "{n} 가입 대상 알려줘", "{n} 금리 조건이 어떻게 돼?"],
    "펀드":    ["{n} 어떤 펀드야?", "{n} 환매수수료 알려줘", "{n} 투자위험등급이 뭐야?"],
    "보험":    ["{n} 어떤 보험이야?", "{n} 보장 내용 알려줘", "{n} 보험료 납입기간은?"],
    "신탁":    ["{n} 어떤 상품이야?", "{n} 신탁 기간 알려줘", "{n} 중도해지 가능해?"],
    "대출":    ["{n} 대출 조건 알려줘", "{n} 상환 방법이 어떻게 돼?", "{n} 중도상환수수료 있어?"],
    "외환":    ["{n} 어떤 상품이야?", "{n} 가입 통화 알려줘", "{n} 환전 수수료는?"],
    "전자금융": ["{n} 어떤 서비스야?", "{n} 이용 방법 알려줘", "{n} 이체한도가 어떻게 돼?"],
    "카드":    ["{n} 어떤 카드야?", "{n} 연회비 얼마야?", "{n} 혜택 알려줘"],
    "기타":    ["{n} 어떤 서비스야?", "{n} 내용 알려줘", "{n} 이용 조건은?"],
}

# 상품명 품질 필터. 적재 파이프라인이 남긴 결함 상품명("투자", "H", "②투자" 등)을
# 평가셋에 넣으면 **질문 자체가 성립하지 않아** 측정이 오염된다.
# ⚠️ 이건 자료 가공이 아니라 **평가 문항 선별**이다 — 색인 내용은 건드리지 않는다.
_BAD_EXACT = {"투자", "투자설명서", "약관", "설명서", "상품설명서", "핵심", "공통",
              "부산은행", "표준", "이용", "안내장", "추가약정서", "가계대출"}


def usable(name: str) -> bool:
    if not name:
        return False
    n = unicodedata.normalize("NFC", name).strip()
    if len(n) < 5 or n in _BAD_EXACT:
        return False
    if not re.search(r"[가-힣]{3,}", n):          # 한글 상품명이 실질적으로 있어야
        return False
    if re.fullmatch(r"[\d\s.\-_()]+", n):
        return False
    if n.startswith(("①", "②", "③", "④")):
        return False
    return True


# ── 실전형(realistic) 변형 ────────────────────────────────────────────────
# 고객은 파일명을 그대로 말하지 않는다. "암걱정없는표적치료암보험 부산은행 안내장 2311"
# 이 아니라 "암걱정없는표적치료암보험"이라고 한다. 아래 변형은 **실제 상품명을 기계적으로
# 바꾸기만** 하므로 정답(gold_product)은 그대로다 — 내용을 지어내지 않는다.

# 문서 꼬리표: 상품명에 붙어 있지만 고객이 말하지 않는 부분.
_TAGS = re.compile(
    r"\s*(추가약정서|상품설명서|투자설명서|운용설명서|이용계약서|"
    r"안내장|약관|설명서|규약|계약서|약정서|"
    r"부산은행|부산|모바일용|모바일|웹용|최종|대면|비대면|준법심의필|개정|적용|"
    r"이용|핵심|계약자용|\(.*?\)|\[.*?\]|[0-9]{4,8})\s*")

_COLLOQUIAL = ["{n} 이거 뭐야?", "{n} 좀 알려줘", "{n} 있어?", "{n} 어때?", "{n} 설명해줘"]


def strip_tags(name: str) -> str:
    """문서 꼬리표를 떼어 고객이 말할 법한 상품명만 남긴다.

    꼬리표를 떼면 "손안에VIP상해보험- -" 처럼 문장부호가 남는다. 같이 정리한다.
    """
    s = re.sub(r"\s+", " ", _TAGS.sub(" ", name))
    s = re.sub(r"[\-–—_·,./]+\s*$", "", s)      # 끝에 매달린 부호
    s = re.sub(r"\s*[\-–—]\s*[\-–—]\s*", " ", s)  # 가운데 남은 이중 부호
    return re.sub(r"\s+", " ", s).strip()


# 상품명 끝에 붙는 '상품 종류' 말. 고객은 보통 여기서 띄어 쓴다.
#   "유스타일정기예금" → "유스타일 정기예금" · "가족사랑통장" → "가족사랑 통장"
_KINDS = ("정기예금", "자유적금", "정기적금", "체크카드", "신용카드", "안심보험",
          "상해보험", "종신보험", "연금보험", "저축보험", "암보험", "건강보험",
          "투자신탁", "금전신탁", "서비스", "이용약관", "카드", "통장", "적금",
          "예금", "보험", "신탁", "대출", "펀드", "약정")


def spaced(name: str) -> str:
    """고객이 띄어 쓸 법한 위치에 띄어쓰기를 넣는다.

    ⚠️ 예전엔 한글 글자수의 **중간 지점**에 넣었는데, 그러면 단어 한복판이 갈라져
    "BNK가족사 랑신탁", "썸씽송 금 서비스" 같은 **사람이 쓰지 않는 문자열**이 나왔다.
    (1차 평가셋의 spaced 395문항 상당수가 이랬고, 난이도를 부당하게 올렸다.)
    이제 **상품 종류 말 앞**에서만 자른다 — 형태소 분석기 없이 쓸 수 있는
    가장 안전한 경계다. 해당하는 말이 없으면 변형을 만들지 않는다.
    """
    for kind in _KINDS:                       # 긴 것부터(=구체적인 것부터) 매칭
        i = name.rfind(kind)
        # 앞에 최소 2글자는 남아야 '이름 + 종류' 꼴이 된다
        if i >= 2 and not name[:i].endswith(" "):
            return (name[:i] + " " + name[i:]).strip()
    return name


def natural(name: str) -> bool:
    """**사람이 실제로 입에 담을 수 있는 상품명인가.**

    1차 평가셋에 이런 문항이 37건(2%) 섞여 있었다:
        "추가 .0 이거 뭐야?" · "8 1더확 있어?" · "26.1연금 어때?"
    상품명을 기계적으로 자르다 생긴 쓰레기다. **못 찾는 게 정상인 질문**이라
    실패로 집계되면 성능을 과소평가하게 된다. 자를 정확히 만들기 위해 걸러낸다.
    (⚠️ 반대로 "내용이 빈 문서를 겨냥한 문항"은 **빼면 안 된다** — 그건 시험지
     결함이 아니라 우리 데이터의 진짜 한계이고, 지우면 그 한계가 안 보이게 된다.)
    """
    n = name.strip()
    if len(re.findall(r"[가-힣]", n)) < 3:          # 한글이 실질적으로 없음
        return False
    if re.match(r"^[\d.\-\s]", n):                  # 숫자·점으로 시작("4.1. KDB…")
        return False
    if re.search(r"(^|\s)[\d.]{1,4}(\s|$)", n):     # 고립된 짧은 숫자 토큰("100 210")
        return False
    if re.search(r"[\s.][0-9.]+$", n):              # 끝에 매달린 숫자("추가 .0")
        return False
    return True


def build_realistic(picked, cat, uniq_prefix, rnd):
    """한 카테고리의 실전형 문항. 변형이 유효한 것만 남긴다."""
    out = []
    for n in picked:
        variants = []
        s = strip_tags(n)
        # ① 꼬리표 제거형 — 원본과 다르고, 너무 짧아지지 않은 경우만
        if s != n and len(re.findall(r"[가-힣]", s)) >= 4:
            variants.append(("tag_stripped", s))
        # ② 띄어쓰기 변형
        sp = spaced(s if s else n)
        if sp != (s or n):
            variants.append(("spaced", sp))
        # ③ 부분명(앞부분만).
        # ⚠️ 예전엔 글자수의 60% 지점에서 잘랐는데, 그러면 **단어 중간이 잘려**
        #    "통화스왑외화고정수" 같은, 사람이 말할 수 없는 문자열이 나왔다.
        #    이제 **띄어쓰기 경계에서만** 자른다(= 앞 단어들만 말하는 실제 줄임 방식).
        #    띄어쓰기가 없는 한 덩어리 이름은 줄여 말할 방법이 없으므로 건너뛴다.
        base = s or n
        words = base.split()
        if len(words) >= 2:
            cut = " ".join(words[:-1]).strip()
            # 접두사가 색인에서 유일할 때만 — 여러 상품에 걸리면 질문이 모호해져
            # 정답을 정의할 수 없다.
            if cut and cut != base and uniq_prefix.get(cut) == 1:
                variants.append(("partial", cut))
        for kind, v in variants:
            if not natural(v):          # 사람이 말할 수 없는 문자열은 문항으로 안 만든다
                continue
            out.append({
                "q": rnd.choice(_COLLOQUIAL).format(n=v),
                "gold_product": n,          # 정답은 원래 상품 그대로
                "category": cat,
                "style": "realistic",
                "variant": kind,
            })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-category", type=int, default=12)
    ap.add_argument("--out", default="eval/eval_set.json")
    args = ap.parse_args()

    cli = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=600)
    col = settings.qdrant_collection_name

    # 전량 스캔해 카테고리별 상품명 수집.
    # ⚠️ 이전에 여기서 실수했다: scroll 루프를 8만 건에서 끊어놓고 전수인 줄 알았다.
    #    offset 이 None 이 될 때까지 반드시 끝까지 돌 것.
    per_cat: dict[str, set[str]] = defaultdict(set)
    chunks: dict[str, int] = defaultdict(int)
    off = None
    seen = 0
    while True:
        pts, off = cli.scroll(col, limit=2000, with_payload=True, offset=off)
        for p in pts:
            pl = p.payload
            name = unicodedata.normalize("NFC", str(pl.get("product_name") or "")).strip()
            cat = str(pl.get("category") or "")
            seen += 1
            if usable(name):
                per_cat[cat].add(name)
                chunks[name] += 1
        if off is None:
            break
    print(f"전수 스캔 {seen:,}청크")

    # 부분명 변형이 유일한지 판정하기 위한 접두사 카운트(전 카테고리 통합).
    all_names = [n for s in per_cat.values() for n in s]
    uniq_prefix: dict[str, int] = defaultdict(int)
    for n in all_names:
        b = strip_tags(n) or n
        cut = b[: max(4, int(len(b) * 0.6))].strip()
        if cut not in uniq_prefix:
            uniq_prefix[cut] = sum(1 for o in all_names if cut in (strip_tags(o) or o))

    rnd = random.Random(SEED)
    items = []
    for cat in sorted(per_cat):
        names = sorted(per_cat[cat])                    # 정렬 → 시드와 함께 결정론
        pick = rnd.sample(names, min(args.per_category, len(names)))
        tmpl = TEMPLATES.get(cat, TEMPLATES["기타"])
        for i, n in enumerate(pick):
            items.append({
                "q": tmpl[i % len(tmpl)].format(n=n),
                "gold_product": n,
                "category": cat,
                "gold_chunks": chunks[n],
                "style": "exact",           # 상품명이 정확히 들어간 문항
                "variant": "template",
            })
        real = build_realistic(pick, cat, uniq_prefix, rnd)
        items.extend(real)
        print(f"  {cat:<6} 사용가능 {len(names):>4}종 → 정확형 {len(pick):>3} + 실전형 {len(real):>3}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    styles = collections_Counter(i["style"] for i in items)
    variants = collections_Counter(i.get("variant") for i in items)
    out.write_text(json.dumps(
        {"seed": SEED, "per_category": args.per_category, "n": len(items),
         "styles": dict(styles), "variants": dict(variants), "items": items},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n총 {len(items)}문항  {dict(styles)}  변형:{dict(variants)}\n→ {out}")


if __name__ == "__main__":
    main()
