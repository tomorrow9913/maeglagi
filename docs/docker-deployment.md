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

### 소스 상태 SSE (PGMQ)

`source-events`는 PostgreSQL의 `pgmq` 확장과 전용 `LISTEN` 연결을 사용합니다. 먼저 DB에서 `pgmq` 확장 설치 권한과 `pgmq.create` 권한을 확인한 다음 `202609260003` migration을 적용하세요. 이 migration은 `sources`의 삽입 및 작업 상태 변경을 같은 트랜잭션에서 PGMQ `source_events` 큐에 기록하고, 커밋 때 API 프로세스에 `NOTIFY`를 전달합니다. HTTP, worker, MCP에서 발생한 변경 모두 같은 DB 트리거를 거칩니다. 확장을 설치할 수 없으면 migration이 실패합니다. 큐와 트리거 없이 예전 Source 테이블 폴링으로 돌아가지 않습니다.

Migration은 이 큐의 테이블·시퀀스에 대한 `PUBLIC`/브라우저 역할 권한만 회수해 기존의 다른 PGMQ 큐 권한을 유지하고, 고정된 `search_path`의 트리거 함수를 사용합니다. migration 역할과 API DB 역할이 다르면 API 역할에 `pgmq` 스키마 사용 및 `pgmq.q_source_events` 조회·삭제 권한을 별도로 부여해야 합니다. `render.yaml`은 migration을 먼저 적용한 뒤 배포하는 구성에서 SSE를 활성화합니다.

API에 `SOURCE_EVENTS_ENABLED=true`를 설정하세요. 프로세스마다 한 개의 **직접 연결 또는 세션 풀러 연결**을 유지하며, 기본적으로 `DATABASE_URL`을 사용합니다. 일반 DB 연결이 transaction pooler라면 별도의 `SOURCE_EVENTS_LISTENER_DATABASE_URL`을 설정해 같은 DB의 직접/세션 URL로 덮어쓰세요. Supabase에서는 Dashboard의 Connect에서 직접 URL(접속 가능한 환경일 때) 또는 shared **Session pooler** URL을 그대로 복사하세요. `:6543` transaction pooler는 `LISTEN/NOTIFY`를 지원하지 않아 거부됩니다. URL은 서버 비밀 값으로 보관하고 프론트 변수에 넣지 마세요. [Supabase 연결 모드](https://supabase.com/docs/guides/database/connecting-to-postgres)와 [PGMQ SQL API](https://supabase.com/docs/guides/queues/pgmq)를 참고하세요.

각 API 프로세스는 같은 큐의 메시지를 독립적으로 조회해 해당 프로세스의 인증된 SSE 연결에 전달합니다. 메시지를 선점하는 `pgmq.read`는 사용하지 않으므로 프로세스나 클라이언트끼리 이벤트를 빼앗지 않습니다. 연결이 끊기거나 구독 버퍼가 넘치면 스트림을 닫고 브라우저가 다시 연결하며, 재연결 시 소스 테이블에서 현재 상태를 다시 읽습니다. 큐 행은 API가 시작할 때와 이후 최대 한 시간마다 24시간 이전 기록을 정리합니다. 기능이 꺼져 있거나 리스너를 시작할 수 없으면 SSE는 명시적으로 503을 반환합니다. migration 후 API를 활성화하기 전에도 트리거는 이벤트를 기록하므로 활성화를 오래 미룰 경우 큐 크기를 확인하세요.

## PostgreSQL 실행기만 사용하는 PoC

먼저 migration을 적용하고 API 환경에 `PROCESSING_EXECUTOR=postgres`를 설정합니다. 기존 Supabase PostgreSQL에 작업을 저장하고 API 프로세스가 실행하므로 Redis 주소와 별도 Celery worker는 필요하지 않습니다. 같은 자료를 서로 다른 실행기로 처리하지 않도록 전환 전 기존 작업을 정리하고 worker를 중지합니다. 이미 실패한 자료는 화면에서 재시도합니다.

실행기가 시작될 때 이전에 접수됐지만 작업 큐 행이 없는 자료도 복구합니다. 대기·처리·접수 중인 문서와 이미 확정했거나 음성 변환 중인 회의만 대상입니다. 검토 중인 초안은 확정 전까지 분석하지 않으며, 기존 작업의 재시도 횟수와 실패 상태는 초기화하지 않습니다.

사용자가 편집하고 확정한 회의록은 저장된 텍스트로 분석합니다. 녹음 파일 다운로드나 STT를 다시 실행하지 않습니다. 임베딩 연결을 설정하지 않은 워크스페이스는 텍스트 검색과 LLM 그래프 추출을 사용할 수 있습니다. 이미 선택한 임베딩 연결이 사라졌거나 기존 벡터가 있는 경우에는 오류를 표시하고 기존 벡터를 보존합니다. 원문은 분석 완료 여부와 관계없이 저장된 발언에서 조회합니다.

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

# 시작 후 앱의 API 연결 설정에서 Ollama와 http://ollama:11434를 등록합니다.
docker compose --env-file .env.docker --profile ollama up -d
# 사용할 로컬 모델만 직접 다운로드합니다.
docker compose --env-file .env.docker exec ollama ollama pull <model>
```

프로필을 지정한 `up`은 기본 서비스도 함께 시작합니다. 선택 서비스 하나만 시작하려면 `up -d neo4j` 또는 `up -d ollama`처럼 서비스 이름을 지정합니다. `neo4j`, `ollama` 호스트 이름은 Compose 네트워크 안에서만 통합니다. 외부 Neo4j에는 TLS URI를 입력합니다. Ollama는 `OLLAMA_NO_CLOUD=1`과 영속 볼륨을 사용하며 모델을 자동 다운로드하지 않습니다. 앱의 임베딩 설정과 모델 출력은 1536차원으로 맞아야 합니다.

Ollama는 항상 provider 목록에 표시됩니다. 계정의 API 연결 화면에서 서버 주소와 선택적 키를 등록하면 주소는 DB, 키는 Supabase Vault에 저장됩니다. 같은 계정의 워크스페이스에서는 연결을 재사용하며, 각 워크스페이스의 답변·추출·임베딩·음성 모델 선택은 별도로 저장됩니다. 주소만 변경할 때 키를 다시 입력할 필요가 없고, 키 교체·삭제는 별도로 선택합니다. 같은 모델이 여러 서버에 있어도 연결별로 선택됩니다.

Compose의 `DEPLOYMENT_MODE` 기본값은 `self_hosted`로 내부망·Docker 주소를 허용합니다. 호스트의 Ollama에는 `http://host.docker.internal:11434`를 사용합니다. API와 worker에 호스트 게이트웨이 매핑이 함께 적용됩니다. `localhost`는 해당 백엔드 컨테이너 자신을 가리킵니다. API와 worker가 서로 다른 머신에 있다면 둘 다 도달 가능한 같은 주소를 등록해야 합니다.

공용 SaaS 배포는 `DEPLOYMENT_MODE=saas`로 실행하며 기본적으로 공개 HTTPS 주소만 허용합니다. 따라서 Render API에서 개인 Ollama를 쓰려면 API와 worker 모두 접근할 수 있는 HTTPS 주소를 등록합니다. 운영자가 관리하는 사설 연결만 `OLLAMA_ALLOWED_PRIVATE_HOSTS`에 정확한 호스트를 지정해 예외를 부여할 수 있습니다. 온프레미스 모드는 워크스페이스 사용자에게 내부 Ollama 주소 등록 권한을 주므로 신뢰하는 사용자에게 서비스를 제공할 때 사용합니다. 메타데이터·링크 로컬 주소 차단, DNS 대상 고정, 리다이렉트 금지는 두 모드에 공통으로 적용됩니다. `OLLAMA_BASE_URL`은 주소가 없는 기존 DB 연결에만 사용하는 호환 설정입니다.

Render의 SaaS API와 외부 Docker worker를 함께 사용하면 worker의 `.env.docker`에도 반드시 `DEPLOYMENT_MODE=saas`를 설정합니다. API와 worker는 같은 주소 허용 정책을 사용해야 하며, worker도 매 요청 시 DNS와 주소를 다시 검증합니다. Compose 기본값 `self_hosted`는 전체 서비스를 신뢰하는 내부 사용자에게 설치하는 경우를 위한 값입니다.

`docker compose --env-file .env.docker down`은 컨테이너만 내리고 데이터 볼륨을 보존합니다. `down -v`는 Redis·Neo4j·Ollama 데이터를 삭제합니다.
