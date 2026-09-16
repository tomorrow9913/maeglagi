# 맥락이 (Maeglagi)

> 흩어진 업무의 맥락을 잇다.

회의와 문서처럼 흩어진 업무 정보를 AI가 연결해 사람·프로젝트·결정·업무·이벤트의 관계와 현재 맥락을 자동으로 만드는 Organizational Context Platform입니다. 이 저장소는 그 PoC 모노레포입니다.

제품 정의와 슬로건, 브랜드 자산, 디자인 토큰의 기준은 [docs/brand.md](docs/brand.md), 화면 문구와 AI 답변의 말투 기준은 [docs/voice.md](docs/voice.md)에 있습니다.

## 구조

```text
.
├── frontend/          # Next.js App Router 웹 클라이언트
├── backend/           # FastAPI API + 맥락 처리 파이프라인
├── contracts/         # Ontology·AI structured output 등 도메인 계약
├── infrastructure/    # 로컬 저장소와 서비스 구성
└── docs/              # 아키텍처 결정 및 개발 문서
```

백엔드는 하나의 배포 단위를 유지하되 모듈 경계를 분명히 한 모듈러 모놀리스입니다. 해커톤 PoC에서 운영 복잡도를 낮추면서 향후 AI Context Engine이나 worker를 독립 서비스로 분리할 수 있습니다.

## 빠른 시작

필수 도구: Python 3.12+, `uv`, Node.js 22+, `pnpm`, Supabase 프로젝트

```bash
cp .env.example .env

# Supabase SQL Editor에서 supabase/migrations/202609150001_initial.sql 실행

cd backend
uv sync --all-groups
uv run uvicorn app.main:app --reload

cd ../frontend
pnpm install
pnpm dev
```

- Frontend: http://localhost:3000
- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- OpenAPI JSON: http://localhost:8000/openapi.json
- Health: http://localhost:8000/api/v1/health

Supabase가 인증, PostgreSQL, 비공개 Object Storage를 담당합니다. 프론트엔드는
Supabase Auth 세션을 쿠키로 유지하고, FastAPI는 전달받은 access token을
`/auth/v1/user`로 검증합니다. 업로드는 같은 사용자 토큰으로 Storage에 전달되어
`storage.objects`의 RLS 정책을 그대로 적용받습니다. `service_role` 키는 필요하지
않으며 클라이언트와 Render 환경변수 어디에도 저장하지 않습니다.

## Render 배포

저장소 루트의 `render.yaml`을 Blueprint로 가져온 뒤 다음 값을 설정합니다.

- API: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `CORS_ORIGINS`
- Web: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`

`DATABASE_URL`은 Supabase Dashboard의 session pooler 연결 문자열을
`postgresql+asyncpg://` 스킴으로 바꿔 사용합니다. Supabase Auth의 Site URL에는
Render 웹 주소를, Redirect URLs에는 `<웹 주소>/auth/callback`을 등록합니다.

## BYOK provider credential

워크스페이스는 OpenAI·Anthropic·NVIDIA NIM 등 provider별 키를 여러 개 보관할 수 있습니다.
각 credential은 `(workspace, provider, label)`로 구분하고 하나를 기본 키로 지정합니다.
기존 프론트의 단일 키 UI는 기본 credential을 읽고 교체하는 호환 API를 사용합니다.

- `POST /api/v1/llm-keys/validate` — provider에 실제 요청을 보내 키 검증
- `GET /api/v1/workspaces/{id}/provider-credentials` — 등록된 키 메타데이터 목록
- `GET|PUT /api/v1/workspaces/{id}/llm-key` — 기존 프론트용 기본 키 호환 API
- `GET /api/v1/workspaces/{id}/ai/providers` — 구현된 provider, capability, 사용 가능한 모델 목록
- `POST /api/v1/workspaces/{id}/ai/chat` — 공통 요청을 provider adapter로 위임

키 원문은 API 응답이나 로그로 반환하지 않고 `APP_SECRET_KEY`로 암호화해 저장합니다.
provider 호출은 공통 adapter 계약으로 정규화하되 provider 고유 옵션과 응답 메타데이터는
확장 필드에 보존합니다. 새 provider는 registry에 adapter를 등록해야만 API 목록에 노출됩니다.

## 설계 원칙

- 원문, 관계형 메타데이터, 임베딩, 그래프를 각각 Object Storage, PostgreSQL, Vector Store, Graph DB에 저장합니다.
- LLM 호출은 `context_engine` 모듈의 provider port 뒤로 격리합니다.
- 라우터는 입력 검증과 HTTP 변환만 맡고 비즈니스 흐름은 application service가 담당합니다.
- API 계약의 단일 기준은 FastAPI 라우터와 Pydantic 모델이며 OpenAPI 문서는 자동 생성합니다.
- 프론트는 FastAPI의 `/openapi.json`에서 TypeScript 타입과 API 클라이언트를 생성하고, mock/real API를 환경변수로 전환합니다.
- API key는 원문을 다시 노출하지 않으며 실제 구현 시 KMS/Vault envelope encryption을 사용합니다.

상세 내용은 [docs/architecture.md](docs/architecture.md)를 참고하세요.

## OpenAPI 계약

OpenAPI 파일을 수동으로 중복 관리하지 않습니다. FastAPI가 라우터와 Pydantic 모델을 바탕으로 생성하는 `/openapi.json`을 API 계약의 단일 Source of Truth로 사용합니다.

```text
FastAPI router + Pydantic model
                ↓
          /openapi.json
                ↓
Frontend TypeScript type / API client
```

백엔드를 실행한 뒤 프론트 타입을 생성하는 예시는 다음과 같습니다. 실제 도입 시 아래 명령을 `frontend/package.json`의 `generate:api` 스크립트로 고정합니다.

```bash
cd frontend
pnpm exec openapi-typescript \
  http://localhost:8000/openapi.json \
  -o src/lib/api/schema.d.ts
```

API 변경 시에는 FastAPI 라우터/Pydantic 모델을 먼저 수정하고 타입을 다시 생성합니다. `contracts/`에는 OpenAPI 사본이 아니라 Ontology와 AI structured output처럼 HTTP 스키마만으로 충분히 표현되지 않는 도메인 계약을 둡니다.
