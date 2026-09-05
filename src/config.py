from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection_name: str = "bnk_bot_collection"

    # LLM (답변 생성: Ollama 로컬, OpenAI 호환 엔드포인트로 호출.
    # 운영 전환 시 vLLM/GPU 로 base_url 만 교체하면 됨 — 코드 불변.)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"  # Ollama 는 키 검증 안 함 (더미; OpenAI SDK 가 빈 키를 거부해서 채움)
    llm_model: str = "qwen3.5-bnk"  # Modelfile 파생(num_ctx=16384); base는 qwen3.5:9b
    llm_timeout_s: float = 120.0  # LLM 호출 타임아웃(초). 큰 표 답변 ~30s + 동시적재 슬로다운 여유

    # 검색 결과 채택 하한(cosine). 이 아래 점수는 '근거 없음'으로 보고 버린다.
    # → 무관 질문이 LLM 에 도달하기 전에 **결정론적으로** 거부된다(모델 협조에 의존 X).
    # 보정 근거(scripts/measure_score_threshold.py, **234,050청크 / 9카테고리** 기준,
    # 2026-09-05 재보정. IN 38문항은 예금 20 + 나머지 8카테고리 18로, 실제 색인된
    # 상품명을 Qdrant 페이로드에서 뽑아 만들었다):
    #   IN(답 가능 38문항)   min 0.6245 / median 0.7242
    #   OUT(도메인 밖 10문항) max 0.6753 / median 0.5170   → gap -0.0508 **겹침**
    #
    # ⚠️ 코퍼스가 151배가 되면서 **완전 분리가 원리상 불가능해졌다.** 청크가 23만 개면
    # 어떤 금융 인접 질문이든 어딘가에 0.67 로 걸린다("코스피 지수" → 펀드 투자설명서).
    # 그래서 기준을 바꿨다: **IN 무손실을 제약으로 두고 OUT 차단을 최대화**한다.
    #   0.60 → IN 38/38 통과 · OUT 9/10 차단 · IN.min 까지 여유 +0.0245
    #   (옛 0.55 는 OUT 8/10 차단에 그침 — 무관 질문 2건이 LLM 까지 도달)
    # 남은 1건(코스피)은 LLM 프롬프트 + 숫자 가드레일이 2차로 거른다(2단 방어).
    # IN 무손실이 제약인 이유: 게이트에서 죽은 정상 질문은 복구 경로가 없지만,
    # 통과한 무관 질문은 뒤에서 한 번 더 걸리기 때문.
    # ⚠️ 코퍼스가 또 바뀌면 **반드시 재보정**.
    retrieval_score_threshold: float = 0.60

    # 검색 시 어휘 필터(hybrid)를 쓸지. 코퍼스가 234,050청크·펀드 78.5% 로 기울면서
    # 희귀 상품이 dense 검색에서 파묻히는 문제의 대응책.
    # 실측(scripts/eval_retrieval_v2.py · 108문항 층화): pass@1 64% → 74%.
    # 근거와 **하면 안 되는 변형들**은 src/chat/lexical.py 상단 참조.
    # False 로 두면 dense 단독으로 즉시 되돌아간다.
    retrieval_use_lexical_filter: bool = True

    # cross-encoder 리랭커로 검색 결과를 재정렬할지.
    # ❌ **측정해서 기각했다. 기본 False.** (2026-09-05, 914문항)
    #      어휘필터        pass@1 755/914 (82%)  ·  0.17초/질의
    #      + 리랭커        pass@1 757/914 (82%)  ·  4.13초/질의   ← +2문항에 24배 지연
    # 붙이기 전 진단이 "실패의 1/3 은 top5 안에 있는데 순서만 밀린 것"이었는데,
    # 그 진단 자체가 틀렸다. 실제로는 **평가의 상품명 비교가 띄어쓰기를 구분해서**
    # 같은 문서를 오답으로 세고 있었다("계좌통합관리서비스이용" vs "… 이용").
    # 판정을 고치자 82%→86% 가 되었고, 남은 순위 여지는 pass@5 91% 와의 5%p 뿐이다.
    # 코드는 `src/chat/reranker.py` 에 남겨 뒀다 — 되살리려면 이 값을 True 로.
    # (그럴 땐 모델 2.1GB 가 KURE 와 별도로 더 올라간다는 점을 감안할 것.)
    retrieval_use_reranker: bool = False
    # 리랭커에 넘길 후보 수. 클수록 건질 여지는 커지지만 질의 지연이 비례해 늘어난다.
    retrieval_rerank_candidates: int = 20

    # 답변 숫자가 근거에 없을 때(= 지어낸 수치 후보) 답변을 폐기하고 "모름"으로 돌릴지.
    # True = 사용자 확정 원칙("정확하거나 모른다")을 코드로 강제. False 로 두면 위반을
    # 로그·응답 필드로만 알리고 답변은 그대로 내보낸다(관찰 모드).
    guardrail_block_on_number_violation: bool = True

    # Paths
    base_dir: Path = Path(__file__).parent.parent
    data_dir: Path = base_dir / "data"
    # 원본 문서 루트. 적재가 닿을 수 있는 경로의 **상한(보안 경계)** 이기도 하다 —
    # `/admin/ingest` 의 root 는 반드시 이 아래여야 한다(임의 경로 스캔 차단).
    #
    # 기본값은 **프로젝트 기준 상대경로**(`BNK_Bot/../Data_PDF`). 특정 머신의 절대경로를
    # 박아두면 clone 한 쪽에서 조용히 깨진다. 다른 위치면 `.env` 의 `DATA_ROOT` 로 지정
    # (`.env.example` 참조).
    data_root: Path = base_dir.parent / "Data_PDF"
    # 기본 적재 대상. 지정하지 않으면 `data_root` 전체를 쓴다(아래 validator).
    # 일부만 적재하려면 `RAW_DIR` 로 하위 경로를 지정 — 단 `data_root` 안이어야 한다.
    raw_dir: Path | None = None
    processed_dir: Path = data_dir / "processed"
    chunks_dir: Path = data_dir / "chunks"
    failed_dir: Path = data_dir / "failed"
    logs_dir: Path = base_dir / "logs"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _default_raw_dir(self):
        """`raw_dir` 미지정 시 `data_root` 를 따라가게 한다.

        ⚠️ 예전엔 `raw_dir: Path = data_root` 로 써뒀는데, 이건 **클래스 정의 시점의
        기본값을 복사**하는 것이라 `.env` 로 `DATA_ROOT` 를 바꿔도 `raw_dir` 은 옛 경로에
        머물렀다. 그러면 `/admin/ingest` 를 root 없이 호출했을 때 존재하지 않는 경로를
        적재하려 해 조용히 실패한다(경계 검사는 통과시키므로 원인도 안 보인다).
        """
        if self.raw_dir is None:
            self.raw_dir = self.data_root
        return self

settings = Settings()
