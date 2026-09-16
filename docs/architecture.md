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

초기에는 모듈러 모놀리스로 배포합니다. 큐 부하가 커질 때 `context_engine` application service를 worker로 옮겨도 domain contract는 유지됩니다.

## Source of Truth

| 데이터 | 저장소 | 원칙 |
|---|---|---|
| User, Workspace, Source, Context, Job metadata | PostgreSQL | 트랜잭션 기준 원장 |
| 원본 문서와 오디오 | S3/MinIO | 불변 원본 |
| chunk와 embedding | PostgreSQL + pgvector | 의미 검색 |
| Entity와 Relation | Neo4j | 원문은 저장하지 않고 source/chunk reference만 유지 |
| 단기 job 상태/queue | Redis | 재생성 가능한 임시 상태 |

## API versioning

모든 public endpoint는 `/api/v1` 아래에 둡니다. `contracts/openapi.yaml`이 프론트와 백엔드의 합의 지점이며, 구현이 늘어나면 FastAPI가 생성한 schema와 CI에서 diff를 검사합니다.

## 보안 기준

- BYOK key를 로그나 API 응답으로 반환하지 않습니다.
- 개발용 `.env`도 Git에 포함하지 않습니다.
- 업로드 파일은 확장자만 믿지 않고 크기와 MIME signature를 함께 검증합니다.
- 질문의 근거가 부족하면 답변을 생성하지 않고 불확실성을 명시합니다.
