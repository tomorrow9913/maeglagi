# Backend

FastAPI 기반 모듈러 모놀리스입니다. 새 기능은 `app/modules/<feature>` 안에 `domain`, `application`, `infrastructure` 순으로 추가하고, HTTP endpoint만 `app/api`에 노출합니다.

