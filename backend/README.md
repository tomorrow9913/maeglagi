# Backend

FastAPI 기반 모듈러 모놀리스입니다. 새 기능은 `app/modules/<feature>` 안에 `domain`, `application`, `infrastructure` 순으로 추가하고, HTTP endpoint만 `app/api`에 노출합니다.

데모 입력 주입과 API 통합 검증은 [백엔드 스모크 실행 가이드](../docs/backend-smoke.md)를
참고하세요. `uv run python -m app.demo_smoke`는 외부 호출 없이 입력을 미리 확인합니다.

## Database migration

모든 테이블 모델은 SQLModel로 정의하며 `app/models.py`가 Alembic metadata에
등록합니다. `DATABASE_URL`을 설정한 뒤 다음 명령으로 Supabase PostgreSQL을
최신 schema로 맞춥니다.

```bash
uv run alembic upgrade head
uv run alembic current
```

모델 변경 시 `uv run alembic revision --autogenerate -m "description"`으로 revision을
만들고 생성된 diff를 반드시 검토합니다.

새 Provider API key는 Supabase Vault에 저장하고 `provider_credentials`에는 Vault
secret UUID만 기록합니다. Celery 작업 메시지는 `source_id`만 전달하며, provider
호출 시 서버에서 secret을 해석합니다. 기존 암호화 credential은 읽기 호환 경로를
유지하며, 갱신하면 Vault로 옮깁니다. 운영 연결에는 `anon` 또는 `authenticated`가
아닌 제한된 서버용 DB 역할을 사용해야 합니다.

## Background worker

로컬 Valkey/Redis를 실행하고 API와 worker에 같은 `CELERY_BROKER_URL`을 설정합니다.

```bash
uv run celery -A app.core.celery:celery_app worker --loglevel=INFO --concurrency=2
```

API는 원본을 Supabase Storage에 저장하고 즉시 `202`와 job을 반환합니다. Celery 메시지는
민감한 키나 파일 대신 `source_id`만 전달합니다. worker는 문서를 MarkItDown으로 파싱하거나
회의를 STT 처리한 뒤 Source의 단계와 진행률을 갱신합니다. 작업은 late acknowledgement,
worker-loss 재전달, 최대 3회 exponential backoff 재시도를 사용합니다.

## Model catalog and price ordering

키 등록·교체는 credential만 갱신하고 기존 모델 설정이나 미선택 역할을 바꾸지 않습니다.
모델 설정은 등록된 모든 provider의 활성 키에서 제공하는 모델을 모아 용도별로 저장합니다.
Ask 화면의 모델 변경도 같은 워크스페이스의 `answer` 역할만 갱신하며 다음 질문부터 적용됩니다.

모델 후보는 사용자의 키로 각 provider의 모델 목록 API에서 조회합니다. 가격순 정렬은
LiteLLM의 공개 가격 맵을 6시간 캐시해 입력·출력 토큰 단가 합계로 비교합니다. 가격은
참고용이며 실제 청구액과 다를 수 있습니다. 가격이 없거나 가격 맵 조회에 실패해도
모델을 숨기지 않고, 가격을 모르는 모델은 확인된 모델 뒤에 보여줍니다. API 키는 가격
맵 제공처로 전송하지 않습니다.
