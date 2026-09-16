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
