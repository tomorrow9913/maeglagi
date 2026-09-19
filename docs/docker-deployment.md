# Docker 배포

루트 `compose.yaml`은 Next.js, FastAPI, Celery worker, 영속 Redis를 실행합니다. **Supabase Auth, Storage, Vault, PostgreSQL은 외부 서비스로 계속 필요합니다.** 일반 PostgreSQL만 띄워서는 Supabase 인증·비공개 Storage·Vault 기능을 대체할 수 없습니다. Neo4j와 Ollama는 선택 프로필입니다.

## 설정

```sh
cp .env.docker.example .env.docker
# .env.docker에 실제 외부 서비스 주소와 비밀 값을 입력합니다.
chmod 600 .env.docker
```

모든 Compose 명령에 `--env-file .env.docker`를 붙입니다. 기존 `.env`와 `frontend/.env.local`은 읽지 않습니다. `.env.docker`는 Git과 Docker 빌드 컨텍스트에서 제외됩니다. `DATABASE_URL`에는 Supabase session pooler의 `postgresql+asyncpg://...` URL을 사용합니다. API와 worker는 같은 `APP_SECRET_KEY`, Supabase 프로젝트·키, 데이터베이스, Storage bucket, Redis 인스턴스 및 DB 번호, 선택한 Neo4j·Ollama 인스턴스를 사용해야 합니다. Compose의 로컬 API/worker에는 같은 설정이 전달됩니다. 서비스 역할 키와 DB URL은 서버 비밀 값이며 `NEXT_PUBLIC_*`에는 공개 가능한 Supabase 값만 넣습니다. 기존 DB 기반 공개 데모를 사용한다면 `DEMO_WORKSPACE_ID`를 설정합니다.

기본 `CELERY_BROKER_URL`은 Compose의 `redis` 서비스를 가리키고 URL 비밀번호는 `REDIS_PASSWORD`와 일치해야 합니다. URL 비밀번호의 예약 문자는 URL 인코딩합니다. Redis 데이터는 `redis-data` 볼륨에 보존되며 일반 TCP와 선택 TLS 게시 포트 모두 기본으로 `127.0.0.1`에만 바인딩됩니다. 기본값에서는 TLS 포트 매핑만 있고 Redis TLS 리스너는 꺼져 있습니다. API와 Next.js 포트도 loopback에 바인딩됩니다. 브라우저의 `NEXT_PUBLIC_API_URL`은 Docker 서비스 이름이 아닌 브라우저에서 접근 가능한 주소입니다. `CORS_ORIGINS`는 브라우저 origin의 JSON 목록입니다. `NEXT_PUBLIC_*` 값은 **빌드 시점**에 프론트에 포함되므로 변경 후 프론트를 다시 빌드해야 합니다.

## 전체 로컬 실행

Supabase Auth의 Redirect URLs에 사용할 프론트 주소의 `/auth/callback`을 등록합니다.
로컬 실행은 `http://localhost:3000/auth/callback`, 별도 도메인은 `https://<도메인>/auth/callback`입니다.
기존 Vercel 운영 주소를 유지한다면 Site URL은 그대로 두고 필요한 콜백만 추가합니다.

```sh
docker compose --env-file .env.docker build
docker compose --env-file .env.docker up -d
docker compose --env-file .env.docker ps
curl -fsS http://localhost:8000/api/v1/health
```

프론트는 `http://localhost:3000`입니다. 새 Supabase 프로젝트에서 DB 기능을 사용하기 전에 migration을 검토하고 **별도로 한 번** 실행합니다. 컨테이너 시작 시 자동 migration은 하지 않습니다.

```sh
docker compose --env-file .env.docker run --rm migrate
```

운영 DB에는 백업과 변경 시간을 확보하세요. `/api/v1/health`는 API 프로세스를 확인하고 `/api/v1/ready`는 pgvector를 포함한 외부 저장소와 선택 graph의 연결 상태를 표시합니다. 컨테이너가 실행 중인 것만으로 Supabase 자격 증명까지 검증되지는 않습니다.

## PostgreSQL 실행기만 사용하는 PoC

먼저 migration을 적용하고 API 환경에 `PROCESSING_EXECUTOR=postgres`를 설정합니다. 기존 Supabase PostgreSQL에 작업을 저장하고 API 프로세스가 실행하므로 Redis 주소와 별도 Celery worker는 필요하지 않습니다. 같은 자료를 서로 다른 실행기로 처리하지 않도록 전환 전 기존 작업을 정리하고 worker를 중지합니다. 이미 실패한 자료는 화면에서 재시도합니다.

```sh
# .env.docker: PROCESSING_EXECUTOR=postgres
# migration은 기존 DB와 새 DB 모두 새 버전 적용 시 필요합니다.
docker compose --env-file .env.docker run --rm migrate
docker compose --env-file .env.docker up -d --build api frontend
```

Render API와 Vercel 프론트를 계속 쓴다면 이 모드에서 별도 Docker 서버를 실행할 필요는 없습니다. 프론트 환경변수는 동일하며, API 실행기 설정은 프론트에 공개하지 않습니다. 무료 API의 수면·재시작과 PoC 이후 Airflow 이전 범위는 [분석 실행기 계획](free-processing-plan.md)에 정리합니다.

### PostgreSQL worker를 API와 분리

API 재시작과 분석 프로세스를 분리하려면 Render API에 `PROCESSING_EXECUTOR=postgres`, `PG_EXECUTOR_ENABLED=false`를 설정하고, Docker 서버의 `.env.docker`에 같은 Supabase DB/Storage/서버 키 및 선택 graph 설정을 넣습니다. API는 작업 등록과 상태 조회만 맡습니다. worker를 먼저 기동하고 연결을 확인한 뒤 API 내 실행기를 끄면 전환 중 처리가 멈추는 시간을 줄일 수 있습니다. 잠깐 겹치는 동안에도 DB 선점과 자료 잠금이 중복 처리를 제어합니다.

```sh
# Redis 없이 PostgreSQL worker만 실행합니다.
docker compose --env-file .env.docker up -d --build pg-worker
docker compose --env-file .env.docker logs -f pg-worker
```

독립 worker는 `PG_EXECUTOR_ENABLED=false`여도 동작합니다. 이 변수는 API 내 실행 여부만 제어합니다. `pg-worker` 서비스는 실행기를 `postgres`로 고정합니다. API와 worker 모두 멈추더라도 작업은 PostgreSQL에 남아 worker가 다시 시작되면 이어서 처리됩니다. 단, 작업 등록 트랜잭션 자체가 DB 장애로 실패한 경우에는 성공 응답을 보내지 않으므로 화면에서 재시도해야 합니다.

## Render API + Vercel 프론트 + Docker worker

1. Render API와 Docker worker가 **같은 Redis 인스턴스, DB 번호, 기본 Celery queue**에 접근하도록 구성합니다. Docker 내부 `redis` 호스트 이름은 Render에서 해석되지 않습니다. 양쪽 URL은 서로 달라도 됩니다. 예를 들어 worker는 `redis://:PASSWORD@redis:6379/0`, Render는 `rediss://:PASSWORD@redis.example.com:6380/0?ssl_cert_reqs=required`를 사용할 수 있습니다. 비밀번호의 URL 예약 문자는 인코딩합니다.
2. 관리형 Redis를 쓸 때는 접근 제어와 TLS를 지원하는 인스턴스의 `rediss://` URL을 Render와 로컬 `.env.docker`에 설정하고 `docker compose --env-file .env.docker up -d worker`만 실행합니다.
3. 이 Compose의 Redis를 Render와 공유할 때는 아래 **직접 TLS 설정**을 사용합니다. worker는 내부 일반 TCP 주소, Render는 외부 TLS 주소를 사용합니다. 두 주소 모두 같은 Redis 프로세스와 `/0` DB를 가리킵니다.
4. Render API와 Docker worker에 같은 `APP_SECRET_KEY`, Supabase 프로젝트/서버 키, Storage bucket, DB, 선택 graph 설정을 입력합니다. 각 주소는 실행 환경에서 해당 인스턴스에 닿아야 합니다. Vercel에는 공개 Render API 주소를 `NEXT_PUBLIC_API_URL`로 넣고 Render `CORS_ORIGINS`에 Vercel origin을 넣습니다. Vercel 공개 Supabase URL/키도 같은 프로젝트여야 합니다.

### Compose Redis 직접 TLS 설정

서버 인증서에 Render가 접속할 공개 DNS 이름(`redis.example.com`)을 SAN으로 포함하고, 발급 기관이 신뢰되는 인증서를 준비합니다. 호스트의 비공개 인증서 디렉터리에 `fullchain.pem`(서버 인증서와 중간 체인), `privkey.pem`(서버 개인 키), `ca.crt`(검증용 CA 인증서)를 배치합니다. 이 파일들은 **읽기 전용**으로 컨테이너에 마운트하며 저장소나 이미지에 넣지 않습니다. 비밀번호 인증을 사용하므로 Redis는 클라이언트 인증서를 요구하지 않습니다(`tls-auth-clients no`). 인증서 발급·갱신 및 개인 키 권한은 운영자가 관리합니다.

`.env.docker`에서 `REDIS_TLS_ENABLED=true`, `REDIS_TLS_CERT_DIR=/absolute/private/cert/directory`, `REDIS_TLS_BIND_ADDRESS=<Redis 호스트의 공개 인터페이스 주소>`, `REDIS_TLS_PORT=6380`으로 설정합니다. 공개 DNS A/AAAA 레코드를 해당 호스트로 연결하고 TCP 6380을 Render의 허용된 egress IP 또는 사설 네트워크에서만 열어야 합니다. Render 환경의 실제 egress 주소를 확인해 방화벽 허용 목록을 구성하세요. 방화벽·라우터·클라우드 보안 그룹 설정은 Compose가 만들지 않습니다. 일반 TCP 6379는 계속 loopback 전용으로 유지하며 외부에 열지 않습니다. 포트 매핑은 기본 구성에도 있지만 `REDIS_TLS_ENABLED=false`이면 Redis는 TLS 포트에서 듣지 않습니다. TLS를 켠 채 인증서 파일이 없거나 비어 있으면 컨테이너가 명확한 오류로 종료됩니다.

```sh
# worker는 .env.docker의 redis://:PASSWORD@redis:6379/0 사용
docker compose --env-file .env.docker up -d redis worker
# Render의 CELERY_BROKER_URL 예시:
# rediss://:PASSWORD@redis.example.com:6380/0?ssl_cert_reqs=required
```

공개 DNS 이름과 신뢰 체인을 검사한 뒤 Render에서 TLS 연결을 확인합니다. 운영자 머신에서는 `redis-cli --tls -h redis.example.com -p 6380 --sni redis.example.com --cacert /path/to/ca.crt ping`을 사용할 수 있습니다(`REDISCLI_AUTH` 환경 변수로 비밀번호 전달). 갱신된 인증서를 반영하려면 Redis 컨테이너를 재시작하세요. worker는 Supabase DB/Storage로 나가는 연결도 필요합니다.

서비스 사이에 강제 `depends_on`이 없어 `worker`만 선택해도 Redis/프론트/API가 자동 시작되지 않습니다. Render에서 기존 Valkey/worker를 유지한다면 이 Docker worker도 동일한 broker에 연결해야 같은 작업을 처리합니다.

## 선택 서비스

```sh
# 먼저 .env.docker에 NEO4J_URI=bolt://neo4j:7687,
# NEO4J_USERNAME=neo4j, 강한 NEO4J_PASSWORD를 설정합니다.
docker compose --env-file .env.docker --profile neo4j up -d

# 먼저 .env.docker에 OLLAMA_BASE_URL=http://ollama:11434를 설정합니다.
docker compose --env-file .env.docker --profile ollama up -d
# 사용할 로컬 모델만 직접 다운로드합니다.
docker compose --env-file .env.docker exec ollama ollama pull <model>
```

프로필을 지정한 `up`은 기본 서비스도 함께 시작합니다. 선택 서비스 하나만 시작하려면 `up -d neo4j` 또는 `up -d ollama`처럼 서비스 이름을 지정합니다. `neo4j`, `ollama` 호스트 이름은 Compose 네트워크 안에서만 통합니다. 외부 Neo4j에는 TLS URI를 입력합니다. Ollama는 `OLLAMA_NO_CLOUD=1`과 영속 볼륨을 사용하며 모델을 자동 다운로드하지 않습니다. 앱의 임베딩 설정과 모델 출력은 1536차원으로 맞아야 합니다. `OLLAMA_BASE_URL`을 설정하면 앱의 Ollama provider가 켜집니다.

`docker compose --env-file .env.docker down`은 컨테이너만 내리고 데이터 볼륨을 보존합니다. `down -v`는 Redis·Neo4j·Ollama 데이터를 삭제합니다.
