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

- `api`: HTTP transport와 dependency wiring. 비즈니스 규칙을 두지 않습니다.
- `modules/*/domain`: 프레임워크에 의존하지 않는 모델과 규칙입니다.
- `modules/*/application`: use case와 port(protocol)를 정의합니다.
- `modules/*/infrastructure`: DB, LLM, object/vector/graph store adapter입니다.
- `core`: 설정, 공통 오류, 로깅과 같은 횡단 관심사입니다.

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

