# 백엔드 데모 시드와 통합 스모크

TSK-49의 Redis 도입 데모 입력과 TSK-39의 API 통합 검증을 반복 실행하기 위한 도구다.
시드는 기존 `backend/tests/seeds.py`의 테스트 시나리오를 파일로 분리했다.
Notion의 상세 완료 기준 전체를 열람하지 못했으므로, 아래 항목은 현재 API에 대한
기술 검증 범위이며 제품 완료 기준 5개를 모두 충족했다는 판정은 아니다.

## 실행

미리보기는 서비스 연결이나 토큰 없이 입력 파일과 결정적인 업로드 제목을 확인한다.

```bash
cd backend
uv run python -m app.demo_smoke
```

실행 전 개발용 워크스페이스를 생성하고 embedding/extraction/answer 모델과 키를
설정한다. API, Celery worker, Valkey, Supabase Storage/PostgreSQL/pgvector/Vault,
Neo4j가 준비되어 있어야 한다. 사용자 로그인 세션의 access token을
`MAEGLAGI_ACCESS_TOKEN` 환경변수에 설정한다. 서비스 역할 키를 대신 사용하지 않는다.

```bash
uv run python -m app.demo_smoke \
  --base-url http://localhost:8000/api/v1/ \
  --workspace <개발용-workspace-UUID> \
  --execute --timeout 600 --report /tmp/maeglagi-smoke.json
```

`--execute`는 네 개의 소스를 업로드하고 실제 모델을 호출하므로 해당 provider 사용량이
발생한다. 기존 소스를 삭제하거나 워크스페이스 설정을 변경하지 않는다. 회의 두 개는
대본 업로드 경로를 사용하므로 녹음·STT 경로는 이 검증에 포함되지 않는다.

## 검증과 재실행

1. `/ready`와 워크스페이스 조회가 성공한다.
2. 문서 두 개와 회의 대본 두 개가 순서대로 처리되어 `succeeded/completed`가 된다.
3. 네 소스의 원문 조회에 인덱싱된 청크가 존재한다.
4. 타임라인과 Context Store가 네 소스를 포함하고, 그래프에 데모 노드 간 관계가 있다.
5. “Redis를 왜 도입했나요?”의 SSE 답변이 정상 종료되며, 인용 번호가 실제 소스의 청크로
   연결되고 적어도 하나의 인용이 데모 소스를 가리킨다.

성공 시 종료 코드는 0, 실패 시 1이다. JSON 보고서의 `checks`는 통과한 단계만 담으며,
중간에 실패해도 확인한 source ID를 남긴다. HTTP 오류 본문이나 provider 오류 원문은
보고서에 기록하지 않는다. 성공 보고서에는 답변과 근거 발췌가 포함된다.

입력 ID와 원문 해시를 포함하는 제목으로 기존 소스를 찾아 재사용한다. 중단 후 재실행하면
이미 업로드된 소스의 처리를 기다린다. 실패 소스나 동일 제목의 복수 소스를 발견하면
중단하며 자동 재업로드하지 않는다. 실패 원인을 해결하고 새 개발용 워크스페이스에서
다시 실행할 수 있다. 이 방식은 순차 재실행을 위한 것으로, 같은 워크스페이스에 두
실행을 동시에 시작하지 않는다. 시드 원문이나 제목을 바꾸면 새 소스로 취급된다.

질문 답변의 의미적 정확성, 브라우저 UI, 실제 녹음/STT, workspace 간 접근 차단은
별도 확인이 필요하다. 로컬 `httpx.MockTransport` 테스트 통과는 실제 인프라 검증 성공을
뜻하지 않는다.

## 이번 작업의 검증 상태

- 시드 미리보기와 실패 경로를 포함한 로컬 자동 테스트를 제공한다.
- 메인 checkout의 `.env`를 수정·복사 없이 프로세스 환경으로 읽어 실제 PostgreSQL,
  Neo4j 연결과 Supabase 인증 서비스 응답을 확인했다. DB에는 pgvector/Vault 확장과
  최신 revision `202609200001`이 적용되어 있다.
- 해당 설정으로 현재 FastAPI를 in-process ASGI 요청으로 검증했다. `/health`와
  `/ready`는 200, 토큰 없는 `/workspaces`는 예상대로 401이었다. readiness의 Storage
  결과는 서비스 응답 확인이며 실제 bucket 업로드 권한 검증은 아니다.
- 전체 업로드·worker·답변 검증은 미실행: 등록된 provider credential이 없고, 읽은
  `.env`에는 사용자 access token, `SUPABASE_SERVICE_ROLE_KEY`, `CELERY_BROKER_URL`이
  없다. 모델 키, 로그인 세션, worker 설정을 갖춘 뒤 위 실행 명령으로 검증해야 한다.
- Notion 작업 트래커의 작업명은 확인했으나 두 번째 문서는 Orca 브라우저의
  `runtime_unavailable` 오류로 열람하지 못했다.
- 후속 후보: 실제 환경 스모크 실행과 상세 완료 기준 대조, Anthropic 점진적 스트리밍
  지원(현재는 전체 응답 fallback).
