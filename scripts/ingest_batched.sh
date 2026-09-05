#!/bin/bash
# 대형 카테고리를 100건씩 끊어 적재한다.
#
# 왜: 한 프로세스로 642건(평균 185쪽)을 연속 처리하면 Python 힙·파서 객체가 누적돼
# 스와핑이 심해진다. 실측으로 2.2분/건 → 7.0분/건까지 떨어졌고 잔여 추정이 23h → 72h 가 됐다.
# 배치마다 프로세스를 새로 띄우면 종료 시 메모리가 통째로 반환된다.
#
# 적재는 idempotent(결정론 point id)라 이미 넣은 문서를 다시 돌려도 덮어쓰기만 된다.
#
# 사용:  bash scripts/ingest_batched.sh "보험/약관" [배치크기]
set -u
cd "$(dirname "$0")/.." || exit 1
SUB="${1:?사용: ingest_batched.sh <카테고리/문서종류> [배치크기]}"
STEP="${2:-100}"
D=/Users/jhyeong/Project/InsightLab/Data_PDF
TAG=${SUB//\//_}
export PYTHONUNBUFFERED=1

TOTAL=$(.venv/bin/python -c "
from src.ingestion.pipeline import find_documents
print(len(find_documents('$D/$SUB')))" 2>/dev/null)
echo "════ 배치 적재 시작 $(date '+%m-%d %H:%M:%S') · $SUB · 총 ${TOTAL}건 · ${STEP}건씩"

caffeinate -dimsu -w $$ >/dev/null 2>&1 &

off=0
while [ "$off" -lt "${TOTAL:-0}" ]; do
  echo "──── [$off ~ $((off+STEP))]  시작 $(date '+%H:%M:%S')  swap=$(sysctl -n vm.swapusage | awk '{print $6}')"
  .venv/bin/python scripts/run_ingestion.py "$D/$SUB" --offset "$off" --limit "$STEP" \
      > "logs/batch_${TAG}_${off}.log" 2>&1
  grep -E "^ok=" "logs/batch_${TAG}_${off}.log" | sed 's/^/      /'
  off=$((off+STEP))
done

echo "════ $SUB 완료 $(date '+%m-%d %H:%M:%S')"
curl -s localhost:6333/collections/bnk_bot_collection \
  | python3 -c "import sys,json;print('최종 색인:', f\"{json.load(sys.stdin)['result']['points_count']:,}청크\")" 2>/dev/null
