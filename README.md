# Source-Aware Branch Support RAG Chatbot

소스코드 기반 영업점 운영지원 RAG 챗봇 PoC입니다. 이 프로젝트는 매뉴얼 문서만 검색하는 RAG가 아니라, 화면 코드, Spring Controller/Service, MyBatis SQL, 테이블 정의서에서 업무 규칙 단위의 지식 문서를 생성한 뒤 영업점 직원용 안내와 IT 담당자용 요약을 분리해 제공합니다.

## Architecture

```text
sample/source repository
  -> source scanner
  -> frontend/java/mybatis/sql/table parsers
  -> static business-rule extractor
  -> optional Qwen summary enhancer
  -> embeddings
  -> Elasticsearch + local JSON checkpoint
  -> SQLite relation graph
  -> hybrid retrieval + RRF
  -> role-aware RAG answer
  -> React UI
```

## Requirements

- Python 3.11+
- Docker Desktop
- Node.js 20+
- macOS native MLX Qwen server for LLM calls

The MVP is designed to keep the end-to-end sample testable even when Elasticsearch or Qwen is not running. When those services are available, the same pipeline writes to Elasticsearch and calls the local OpenAI-compatible Qwen server.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Run Elasticsearch

```bash
docker compose up -d elasticsearch
```

The Docker compose file limits Elasticsearch JVM heap to 2 GB for a Mac M4 Pro / 24 GB RAM PoC.

## Run Qwen Local Server

```bash
./scripts/run_qwen_server.sh
```

This script runs:

```bash
mlx_lm.server --model "Qwen/Qwen3-14B-MLX-4bit"
```

No external LLM API is used.

## Ingest Sample Source

```bash
python -m backend.app.ingestion.pipeline \
  --source-dir backend/examples/bank_sample \
  --reset-index \
  --generate-summaries
```

For a faster static-only run:

```bash
python -m backend.app.ingestion.pipeline \
  --source-dir backend/examples/bank_sample \
  --reset-index
```

## Run Backend

```bash
uvicorn backend.app.main:app --reload --port 9000
```

To use the local Qwen server for chat responses instead of the static fallback:

```bash
ENABLE_LLM_CHAT=true uvicorn backend.app.main:app --reload --port 9000
```

Important endpoints:

- `GET /api/health`
- `POST /api/ingest/run`
- `GET /api/ingest/status`
- `POST /api/search`
- `POST /api/chat`

## Run Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` to `http://localhost:9000`.

## Test

```bash
pytest backend/tests
```

The end-to-end tests use the bundled sample source and the local JSON index fallback, so they do not require Elasticsearch or Qwen to be running.

## Sample Questions

- 고객조회 화면에서 저장이 안돼요.
- 고객번호 넣었는데 고객이 조회되지 않아요.
- 저장 권한이 없다고 나오는데 어떻게 해야 하나요?
- 해지 고객 수정이 안되는 이유가 뭐예요?

## Security Model

`branch` role responses hide source code, internal API paths, table details, and implementation identifiers. `it` role responses may include file names, method names, SQL IDs, and table names after sensitive values are masked. The safety guard blocks guidance for permission bypass, security bypass, direct production DB updates, and secret exposure.

## Project Intent

본 PoC의 핵심은 단순히 매뉴얼이나 소스코드를 벡터DB에 저장하는 것이 아니라, 소스코드 내부의 화면 흐름, API 호출, Controller-Service-Mapper-SQL 연결, 조건문, 권한 검증, 상태값 분기, 예외 메시지를 자동 분석하여 업무 규칙 단위의 지식 데이터로 변환하는 것이다.

이를 통해 영업점 직원의 자연어 문의가 들어왔을 때 관련 화면과 소스 위치를 찾는 것에 그치지 않고, 해당 화면에서 발생 가능한 오류 조건과 조치 방법을 영업점 직원이 이해할 수 있는 업무 언어로 안내할 수 있다.

초기 PoC는 Mac M4 Pro 24GB 환경에서 Qwen3-14B-MLX-4bit와 Elasticsearch를 활용하여 로컬 환경 중심으로 구현하며, 향후 운영 로그, 장애 이력, ITSM, 배포 이력과 연계하여 장애 대응 자동화 수준을 높이는 방향으로 확장한다.
