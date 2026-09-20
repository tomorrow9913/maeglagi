# 맥락이에 기여하기

버그 제보, 사용성 개선, 문서 보완, 테스트와 코드 기여를 환영합니다.

## 시작하기

1. [기존 이슈](https://github.com/tomorrow9913/maeglagi/issues)를 확인합니다. 버그는 재현 순서, 기대한 결과, 실제 결과와 실행 환경을 적어 주세요. 화면을 첨부할 때는 계정 정보와 회의 내용을 가려 주세요.
2. 기능이나 큰 구조 변경은 이슈에서 범위를 먼저 맞춥니다. 작은 오타나 재현 가능한 버그 수정은 바로 PR을 열어도 됩니다.
3. 저장소를 fork하고 `develop`에서 작업 브랜치를 만듭니다. 개발 환경은 [README](README.md), 전체 서비스 실행은 [Docker 가이드](docs/docker-deployment.md)를 참고합니다.
4. PR의 대상 브랜치는 `develop`입니다. 어떤 문제가 어떻게 바뀌는지, 확인한 테스트, 화면 변경이 있다면 전후 모습을 적어 주세요.

## 코드 구조

HTTP API와 [MCP](docs/mcp.md)는 최종 진입 계층입니다. 입력·응답과 인증된 사용자 전달을 맡기고, 권한·업무 규칙·저장은 공통 애플리케이션 서비스에서 재사용합니다. MCP 도구가 HTTP 라우터를 직접 호출하거나 같은 저장 규칙을 다시 구현하지 않도록 해 주세요.

외부 에이전트가 제출하는 분석 결과도 원문 근거와 소유권, 수정 버전 검증을 거칩니다. 변경 시 다른 계정의 자료에 접근하지 않는지와 재시도 때 중복 저장되지 않는지를 함께 확인합니다.

## 확인할 항목

백엔드에서:

```bash
uv sync --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

PostgreSQL 통합 테스트는 운영 DB가 아닌 폐기 가능한 로컬 DB를 사용합니다. 필요한 환경변수와 테스트 서비스 구성은 [백엔드 CI](.github/workflows/ci-backend.yml)를 참고하세요. 해당 DB 설정이 없으면 일부 통합 테스트는 건너뜁니다.

프론트에서:

```bash
npm ci
npm run lint
node --test tests/*.test.mjs
npm run build
```

DB 변경에는 Alembic 마이그레이션과 기존 데이터 보존 검증을 포함합니다. 실제 `.env`, API 키, MCP 토큰, 개인 회의록은 커밋하거나 이슈·PR에 붙이지 않습니다. 설정 예시에는 자리표시자만 사용합니다.
