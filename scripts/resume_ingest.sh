#!/bin/bash
# 재부팅 후 적재 재개용. 파싱은 이미 끝났으므로(MD 캐시 3,814개) 임베딩·적재만 돈다.
#
# 순서: Docker/Qdrant 기동 확인 → 슬립 방지 → 카테고리별 순차 적재
# 카테고리마다 프로세스를 새로 띄우는 이유: 장시간 단일 프로세스는 메모리가 누적돼
# 후반부에 스래싱/OOM 이 난다(실측). 단계가 끝날 때마다 반환된다.
#
# 사용:  bash scripts/resume_ingest.sh
set -u
cd "$(dirname "$0")/.." || exit 1
D=/Users/jhyeong/Project/InsightLab/Data_PDF
export PYTHONUNBUFFERED=1

echo "════ 적재 재개 $(date '+%m-%d %H:%M:%S') ════"

# 1) Docker 기동 대기
if ! docker info >/dev/null 2>&1; then
  echo "Docker 시작 중..."
  open -a Docker
  for i in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 5; done
fi
docker info >/dev/null 2>&1 || { echo "❌ Docker 기동 실패"; exit 1; }

# 2) Qdrant 기동 대기
docker compose up -d >/dev/null 2>&1
for i in $(seq 1 30); do
  curl -s --max-time 2 localhost:6333/collections >/dev/null 2>&1 && break; sleep 2
done
PTS=$(curl -s localhost:6333/collections/bnk_bot_collection \
      | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['points_count'])" 2>/dev/null)
echo "Qdrant 준비됨 · 현재 ${PTS:-?}청크"

# 3) 슬립 방지(이 스크립트가 끝나면 자동 해제)
caffeinate -dimsu -w $$ >/dev/null 2>&1 &

# 4) 카테고리별 순차 적재 (가벼운 것 → 무거운 것)
for sub in "보험/운용설명서" "보험/설명서" "펀드/약관" "펀드/설명서" "보험/약관"; do
  tag=${sub//\//_}
  echo "──── $sub  시작 $(date '+%H:%M:%S')"
  .venv/bin/python scripts/run_ingestion.py "$D/$sub" > "logs/stage_${tag}.log" 2>&1
  grep -E "^ok=|elapsed=" "logs/stage_${tag}.log" | sed 's/^/    /'
  echo "──── $sub  완료 $(date '+%H:%M:%S')"
done

echo "════ ALL COMPLETE $(date '+%m-%d %H:%M:%S') ════"
curl -s localhost:6333/collections/bnk_bot_collection \
  | python3 -c "import sys,json;print('최종 색인:', f\"{json.load(sys.stdin)['result']['points_count']:,}청크\")" 2>/dev/null
