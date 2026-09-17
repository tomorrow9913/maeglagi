# Backend

FastAPI 기반 모듈러 모놀리스입니다. 새 기능은 `app/modules/<feature>` 안에 `domain`, `application`, `infrastructure` 순으로 추가하고, HTTP endpoint만 `app/api`에 노출합니다.

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

Provider API key는 애플리케이션 테이블에 직접 저장하지 않고 Supabase Vault에
저장합니다. `provider_credentials`와 작업 큐에는 Vault secret UUID만 전달하며,
provider 호출 직전에만 secret을 해석합니다. 운영 연결에는 `anon` 또는
`authenticated`가 아닌 제한된 서버용 DB 역할을 사용해야 합니다.
