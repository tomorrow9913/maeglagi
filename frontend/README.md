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

## 실행

```bash
pnpm install
pnpm dev      # http://localhost:3000
pnpm lint     # tsc --noEmit
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

## 배포 (Vercel)

모노레포이므로 Vercel 프로젝트에서 **Root Directory를 `frontend`로 지정**해야 합니다.

1. Vercel에서 저장소를 import 합니다.
2. Root Directory: `frontend`
3. Framework Preset: Next.js (`vercel.json`에 고정되어 있습니다)
4. Environment Variables: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_USE_MOCKS`

`main` 브랜치는 production, 그 외 브랜치는 preview 배포로 연결합니다.
