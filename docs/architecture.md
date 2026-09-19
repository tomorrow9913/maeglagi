# Architecture

## 제품 흐름

```text
Document / Meeting
        ↓
  ingestion normalization
        ↓
classification → entity extraction → event/decision/task extraction
        ↓
 relation extraction → entity resolution → context update
        ↓
PostgreSQL / Object Storage / Vector Store / Graph DB
        ↓
 hybrid retrieval → grounded answer + sources
```

## 백엔드 경계

- `api/<prefix>`: URL prefix 단위의 router와 request/response schema를 함께 둡니다.
- `auth`: 인증 사용자 모델과 FastAPI dependency를 한곳에서 관리합니다.
- `decorators`: endpoint에 재사용하는 권한 정책 helper를 둡니다.
- `middleware`: CORS 등 middleware와 앱 시작 시의 등록 순서를 관리합니다.
- `modules/*/domain`: 프레임워크에 의존하지 않는 모델과 규칙입니다.
- `modules/*/application`: use case와 port(protocol)를 정의합니다.
- `modules/*/infrastructure`: DB, LLM, object/vector/graph store adapter입니다.
- `core`: 설정, 공통 오류, 로깅과 같은 횡단 관심사입니다.

```text
app/
├── api/
│   ├── auth/{router,schemas}.py
│   ├── jobs/{router,schemas}.py
│   ├── workspaces/{router,credentials,schemas}.py
│   └── ai/{router,schemas}.py
├── auth/{dependencies,models}.py
├── decorators/authorization.py
├── middleware/
│   ├── http/{rate_limit,request_logging}.py
│   └── setup.py
└── modules/context_engine/...
```

`api/ai`는 HTTP 입력 변환과 credential 선택까지만 담당합니다. provider adapter와
정규화된 AI 호출 계약은 `modules/context_engine`에 남겨 API, worker, batch에서 함께 씁니다.

## 관측성과 요청 보호

- `SENTRY_DSN`이 설정된 환경에서만 Sentry FastAPI/Starlette integration을 활성화합니다.
- 모든 요청에 `X-Request-ID`를 생성하거나 전달하고 structlog JSON 로그에 함께 기록합니다.
- `RATE_LIMIT`은 기본 `120/minute`이며 health check와 CORS preflight는 제외합니다.
- `RATE_LIMIT_STORAGE_URI` 기본값은 `memory://`입니다. 여러 Render instance를 사용할 때는
  Redis URI로 교체해 인스턴스 간 카운터를 공유합니다.

백엔드 코드는 모듈러 모놀리스로 유지하고 API와 Celery worker를 별도 프로세스로 배포합니다.
문서·회의 처리 작업은 Celery worker가 맡습니다.

## Source of Truth

| 데이터 | 저장소 | 원칙 |
|---|---|---|
| 원본 문서와 오디오 | Supabase Object Storage | private `sources` bucket의 불변 원본 |
| User, Workspace, Source, Context, Job metadata와 Source 처리 상태 | Supabase PostgreSQL | 트랜잭션 기준 원장 |
| chunk와 embedding | Supabase PostgreSQL + pgvector | 의미 검색 |
| Entity와 Relation | Neo4j | 원문 없이 source/chunk reference만 유지 |
| 작업 큐 | Valkey (Render Key Value) | Celery broker |

PoC에서는 Object Storage와 Vector DB를 Supabase에 통합하고 Graph DB는 `.env`의
`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`로 연결합니다. 별도 MinIO나
Vector DB 컨테이너는 운영하지 않습니다. `render.yaml`은 FastAPI API, Celery worker,
Valkey 기반 Key Value 서비스를 배포하고 API와 worker에 `CELERY_BROKER_URL`을 연결합니다.
`/api/v1/health`는 프로세스 liveness, `/api/v1/ready`는 Object Storage,
PostgreSQL, pgvector 확장, Neo4j 연결 상태를 확인합니다.

## 회의 수집 경로

회의는 두 경로로 수집하지만 정규화 이후에는 같은 파이프라인을 사용합니다.

```text
audio upload ── provider STT ──┐
                               ├─ normalization → chunking → embedding → pgvector
browser transcript ────────────┘
```

- `POST /workspaces/{id}/sources/recordings`: 원본 오디오를 Storage에 보존한 뒤
  transcription capability가 있는 BYOK provider로 일괄 STT합니다.
- `POST /workspaces/{id}/sources/transcripts`: 브라우저가 만든 대본을 원문으로
  보존하고 STT 단계 없이 분석을 시작합니다.
- `transcriptSource`가 `server`면 `transcribing` 단계를 포함하고, `browser`면
  해당 단계를 생략합니다.
- chunk는 `source_id`, 순번, 회의 시간 범위를 보존하고 1,200자/200자 overlap
  전략으로 생성합니다. embedding은 Supabase PostgreSQL의 pgvector에 적재합니다.

## API versioning

모든 public endpoint는 `/api/v1` 아래에 둡니다. API 계약의 기준은 FastAPI 라우터와
Pydantic 모델이며, 개발 환경의 `/openapi.json`은 여기에서 자동 생성됩니다. 운영
환경에서는 OpenAPI와 API 문서 경로를 비활성화합니다. 저장소의
`contracts/openapi.yaml`은 현재 API의 기준이 아닌 수동 명세입니다.

## 보안 기준

- BYOK key를 로그나 API 응답으로 반환하지 않습니다.
- 개발용 `.env`도 Git에 포함하지 않습니다.
- 업로드 파일은 확장자만 믿지 않고 크기와 MIME signature를 함께 검증합니다.
- 질문의 근거가 부족하면 답변을 생성하지 않고 불확실성을 명시합니다.
