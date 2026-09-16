# CI/CD와 환경변수

## 파이프라인

| 워크플로 | 언제 | 하는 일 |
| --- | --- | --- |
| `ci-frontend.yml` | `frontend/**` 가 바뀐 PR과 develop/main 푸시 | `pnpm lint`(eslint + tsc) → `pnpm build` |
| `ci-backend.yml` | `backend/**` 가 바뀐 PR과 develop/main 푸시 | `ruff check` → `ruff format --check` → `pytest` |
| `deploy-vercel.yml` | `main` 푸시, 수동 실행 | Vercel production 배포 + 스모크 테스트 |

경로 필터를 둔 이유는 문서만 고친 PR을 빌드로 붙잡지 않기 위해서입니다.
브랜치 보호에서 필수 체크로 지정할 때는, 건너뛴 체크가 머지를 막지 않는지 확인하세요.

백엔드 배포는 `render.yaml` 블루프린트가 맡습니다. Render가 저장소에 연결돼 있으면
푸시할 때 자동으로 배포되므로 별도 워크플로를 두지 않았습니다.

## GitHub Actions 시크릿

저장소 **Settings → Secrets and variables → Actions** 에 등록합니다.
등록에는 저장소 admin 권한이 필요합니다.

| 키 | 값을 얻는 곳 | 필요한 워크플로 |
| --- | --- | --- |
| `VERCEL_TOKEN` | Vercel → Account Settings → Tokens → Create | `deploy-vercel.yml` |
| `VERCEL_ORG_ID` | 로컬에서 `vercel link` 후 `.vercel/project.json` 의 `orgId` | `deploy-vercel.yml` |
| `VERCEL_PROJECT_ID` | 같은 파일의 `projectId` | `deploy-vercel.yml` |

CI(`ci-frontend`, `ci-backend`)에는 시크릿이 필요 없습니다. 백엔드 `Settings`의 모든
필드에 기본값이 있고, 프론트 빌드는 `NEXT_PUBLIC_USE_MOCKS=true`로 돕니다.

**애플리케이션 환경변수는 GitHub에 넣지 않습니다.** Vercel/Render 프로젝트에 등록된 값을
`vercel pull`이 받아 쓰므로, 같은 값을 두 곳에 두면 어긋납니다.

## 배포 대상별 환경변수

### Vercel — 프론트 (Production)

| 키 | 값 | 비고 |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `https://<render-api>/api/v1` | 백엔드 배포 주소 |
| `NEXT_PUBLIC_USE_MOCKS` | `false` | 실 API를 붙이기 전까지는 `true` |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<ref>.supabase.co` | |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | `sb_publishable_...` | 공개 키. 브라우저에 노출됩니다 |

`NEXT_PUBLIC_` 접두사는 **빌드 시점에 번들에 박힙니다.** 값을 바꾸면 재배포해야 반영됩니다.
비밀로 지켜야 하는 값에는 이 접두사를 붙이면 안 됩니다.

### Render — 백엔드 (`maeglagi-api`)

`render.yaml`에 이미 선언돼 있습니다. `sync: false`는 대시보드에서 직접 넣으라는 표시입니다.

| 키 | 대시보드 입력 | 값 |
| --- | --- | --- |
| `DATABASE_URL` | 필요 | Supabase → Connect → Session pooler, `postgresql+asyncpg://` 형식 |
| `SUPABASE_URL` | 필요 | `https://<ref>.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | 필요 | `sb_publishable_...` |
| `CORS_ORIGINS` | 필요 | `["https://<프론트 도메인>"]` — JSON 배열 |
| `SENTRY_DSN` | 선택 | 비워 두면 Sentry를 끕니다 |
| `APP_SECRET_KEY` | 자동 | Render가 생성합니다 |
| `APP_ENV` / `SENTRY_TRACES_SAMPLE_RATE` / `RATE_LIMIT` / `RATE_LIMIT_STORAGE_URI` / `LOG_LEVEL` | 자동 | `render.yaml`의 값 |

API instance를 여럿 띄우면 `RATE_LIMIT_STORAGE_URI`를 `memory://`에서 Redis로 바꿔야 합니다.
프로세스마다 카운터가 따로 돌아 제한이 실제보다 느슨해집니다.

## 한 번만 해둘 설정

1. **Vercel 프로젝트의 Root Directory를 `frontend`로 지정합니다.**
   모노레포라 저장소 루트에서 빌드하면 Next.js 앱을 찾지 못합니다. 루트를 지정하면
   pnpm workspace 루트에서 설치하므로 lockfile 문제도 생기지 않습니다.
2. `vercel link` 후 `.vercel/project.json`에서 `orgId`/`projectId`를 꺼내 위 시크릿에 넣습니다.
3. Render 블루프린트를 저장소에 연결합니다.

## 배포 대상이 둘인 상태

`render.yaml`에 `maeglagi-web`(프론트)이 있고, 현재 프론트는 Vercel에도 배포돼 있습니다.
**같은 프론트를 두 곳에 배포하면 어느 주소가 최신인지 알 수 없습니다.** 하나로 정하고
나머지는 내리세요.

- Vercel로 간다면 `render.yaml`에서 `maeglagi-web` 블록을 지웁니다.
- Render로 간다면 `deploy-vercel.yml`을 지우고 Vercel 프로젝트를 정리합니다.
