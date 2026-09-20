# Frontend

Next.js App Router 기반 웹 클라이언트입니다.

## 스택

| 항목          | 선택                     | 비고                               |
| ------------- | ------------------------ | ---------------------------------- |
| 프레임워크    | Next.js 15 (App Router)  | React 19                           |
| 언어          | TypeScript (strict)      |                                    |
| 스타일        | Tailwind CSS v4          | `src/app/globals.css` 단일 진입점  |
| UI            | shadcn/ui (`radix-nova`) | Radix 기반, `components.json` 참조 |
| 아이콘        | lucide-react             |                                    |
| 패키지 매니저 | pnpm 10 (workspace)      | 루트 `pnpm-workspace.yaml`         |

shadcn은 React + Tailwind + Radix를 전제로 하므로 위 조합은 Day 1에 고정합니다.

## 검사

`pnpm lint`는 ESLint와 타입 검사를 함께 돌립니다. 둘의 역할이 다릅니다.

- `tsc --noEmit` — 타입이 맞지 않는 코드를 막습니다.
- `eslint` — 타입은 맞지만 의도와 어긋난 코드를 막습니다. 선언만 하고 쓰지 않는 prop, Hook 의존성 누락 등입니다. 경고도 실패로 처리합니다(`--max-warnings 0`).

`src/components/ui`는 shadcn 원본이라 규칙을 완화해 뒀습니다. 변형이 필요하면 원본을 고치지 말고 래퍼를 만드세요.

## 실행

```bash
pnpm install
pnpm dev      # http://localhost:3000
pnpm lint     # eslint + tsc --noEmit
pnpm lint:fix # 자동 수정 가능한 것만 고침
pnpm build
```

## 폴더 구조

```text
src/
├── app/                     # 라우트 전용 (page/layout만 둡니다)
│   ├── page.tsx             # 랜딩
│   └── workspaces/
│       ├── page.tsx         # 워크스페이스 목록
│       └── [workspaceId]/
│           ├── layout.tsx   # 좌측 내비게이션 셸
│           ├── sources/     # 소스 업로드·처리 상태
│           ├── timeline/    # Context Timeline
│           ├── graph/       # Knowledge Graph
│           ├── ask/         # Ask Workspace
│           └── settings/    # 워크스페이스·BYOK 설정
├── components/
│   ├── ui/                  # shadcn 원본 (직접 수정 금지, 변형은 래퍼로)
│   └── layout/              # 헤더·내비게이션 등 앱 셸
├── features/                # 도메인별 기능 모듈 (컴포넌트·훅·타입)
├── hooks/                   # 범용 훅
├── lib/
│   ├── api/                 # HTTP 경계 (mock/real 전환 포함)
│   ├── navigation.ts        # 워크스페이스 내비게이션 정의
│   └── utils.ts             # cn 등 유틸
└── types/                   # 공용 타입
```

라우트 파일에는 화면 조립만 두고, 실제 UI와 상태는 `features/` 아래 모듈에 둡니다.

## 라우팅 규칙

- 모든 워크스페이스 화면은 `/workspaces/[workspaceId]/*` 아래에 둡니다.
- 메뉴 항목은 `src/lib/navigation.ts`의 `workspaceNavItems` 한 곳에서 관리합니다. 화면을 추가할 때 라우트와 이 배열을 함께 수정합니다.
- 경로 문자열은 직접 조합하지 말고 `workspacePath(workspaceId, segment)`를 사용합니다.

## 데모 모드

`NEXT_PUBLIC_USE_MOCKS=true`이면 in-memory mock이 붙고, 화면 상단에 데모 배너가 뜹니다. 백엔드 없이도 전 화면을 시연할 수 있습니다.

- `/demo` — 시드 데이터가 들어 있는 워크스페이스의 Timeline으로 바로 진입합니다. 발표 때 목록을 거치지 않으려고 둔 경로입니다.
- 업로드한 파일과 만든 워크스페이스는 새로고침하면 초기 시드로 돌아갑니다.

실 API 연결에는 `NEXT_PUBLIC_USE_MOCKS=false`를 정확히 설정해야 합니다. 미설정이거나 다른 값이면 mock이 유지됩니다. 화면 상단의 데모 배너로 현재 모드를 확인할 수 있습니다.

### 실 API 연결 설정

로컬에서는 `frontend/.env.example`을 `frontend/.env.local`로 복사해 다음 네 변수를 설정합니다. Next.js의 작업 디렉터리는 `frontend`이므로 저장소 루트의 `.env`만으로는 프론트 설정이 적용되지 않습니다.

| 변수 | 실 API에서 필요한 값 |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | 브라우저에서 접근 가능한 FastAPI 주소와 `/api/v1` 경로. 끝에 `/`를 붙이지 않습니다. |
| `NEXT_PUBLIC_USE_MOCKS` | 정확히 `false`. |
| `NEXT_PUBLIC_SUPABASE_URL` | 백엔드가 사용하는 것과 같은 Supabase 프로젝트 URL. |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | 같은 프로젝트의 공개 키. |

배포에서는 이 네 변수를 Vercel 프로젝트의 해당 환경(production/preview)에 설정하고 다시 빌드해야 합니다. `NEXT_PUBLIC_` 값은 빌드 시 브라우저 번들에 포함됩니다. 백엔드의 `CORS_ORIGINS`에는 실제 프론트 origin을 JSON 배열로 지정하고, 백엔드의 `SUPABASE_URL` 및 `SUPABASE_PUBLISHABLE_KEY`는 프론트와 같은 프로젝트를 가리켜야 합니다. 이메일 가입 확인에 쓰는 `/auth/callback` URL은 Supabase Auth의 redirect URL 허용 목록에 추가합니다. 백엔드 `SUPABASE_SERVICE_ROLE_KEY`와 provider 비밀 키는 프론트 환경변수에 넣지 않습니다.

## 카카오 로그인 설정

`/login`의 로그인과 계정 만들기 화면에서 같은 카카오 OAuth 버튼을 사용합니다. 프론트는 Supabase `kakao` provider에 `queryParams.scope`로 `profile_nickname profile_image` 범위만 요청하며, 인증 후 기존 `/auth/callback`에서 세션을 교환합니다. Supabase Kakao provider의 기본 범위에는 `account_email`이 포함되므로 `options.scopes`만 지정하면 이메일 권한이 다시 붙습니다. Kakao 앱이 비즈 앱이 아니므로 `queryParams.scope`로 기본값을 덮어써 이메일 권한을 요청하지 않습니다. 카카오 계정은 이메일이 없는 Supabase 사용자로 들어올 수 있으며 백엔드 `/api/v1/auth/me`는 이 경우 `email: null`을 반환합니다.

대시보드 설정 시 Kakao Developers에서 로그인 기능과 닉네임·프로필 이미지 동의를 켜고, Supabase Auth의 Kakao provider에 Kakao REST API 키와 Client Secret을 등록합니다. Kakao Redirect URI에는 Supabase의 `https://<project-ref>.supabase.co/auth/v1/callback`을, Supabase Auth Redirect URLs에는 실제 프론트의 `https://<frontend-origin>/auth/callback`을 등록합니다(로컬 개발 주소도 사용할 경우 별도 등록). Supabase에서 이메일 없는 OAuth 사용자를 허용하는 설정도 필요합니다. 비밀 키는 서버 측 대시보드에만 둡니다.

이미 이메일로 가입한 회원은 `/account/security`에서 카카오 identity를 현재 Supabase 사용자에 연결합니다. 연결 후에는 어느 방법으로 로그인해도 같은 `auth.users.id`와 서비스 자료를 사용합니다. Supabase 대시보드의 Authentication 설정에서 **Enable Manual Linking**을 켜야 합니다. 이미 다른 사용자에 소유된 identity는 안전을 위해 자동 병합하지 않습니다.

## 배포 (Vercel)

모노레포이므로 Vercel 프로젝트에서 **Root Directory를 `frontend`로 지정**해야 합니다.

1. Vercel에서 저장소를 import 합니다.
2. Root Directory: `frontend`
3. Framework Preset: Next.js (`vercel.json`에 고정되어 있습니다)
4. Environment Variables: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_USE_MOCKS`,
   `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`

`main` 브랜치는 production, 그 외 브랜치는 preview 배포로 연결합니다.
