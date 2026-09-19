# PoC 분석 실행기와 Airflow 이전 계획

현재 PoC는 `PROCESSING_EXECUTOR=postgres`로 PostgreSQL에 저장된 작업을 비동기로 실행합니다. `PG_EXECUTOR_ENABLED=true`이면 기존 API 프로세스가 처리하며, 별도 worker를 운영할 때는 API에 `PG_EXECUTOR_ENABLED=false`를 설정합니다. 작업은 Supabase PostgreSQL에 남기므로 Redis나 별도 Celery 서버가 필요하지 않습니다. 기존 Celery 경로는 `PROCESSING_EXECUTOR=celery`로 유지하며, 이전 설치의 기본값도 Celery입니다. 두 실행기를 동시에 같은 자료에 사용하지 않습니다.

## 처리 흐름

- 업로드 완료·분석 재시도·회의록 확정 시 자료 상태와 작업 등록을 같은 DB 트랜잭션에 저장합니다.
- 실행기는 작업을 선점하고 임대 기간(lease)을 갱신합니다. 재시작 후 만료된 작업은 다시 가져옵니다. 완료·실패 기록은 선점한 실행기만 변경합니다.
- 자료·워크스페이스 잠금과 기존 분석 체크포인트를 함께 사용합니다. 외부 공급자 호출 직후 프로세스가 중단된 경우 호출 자체의 중복까지 보장할 수는 없으며, 저장된 체크포인트 이후 단계는 재사용합니다.
- 녹음은 STT가 끝나면 `awaiting_review`에서 멈춥니다. 사용자가 화자·발언·프로젝트를 검토하고 확정하면 후속 분석을 별도 작업으로 등록합니다.
- 공급자 처리 실패는 제한된 횟수로 재시도하며, DB 장애와 프로세스 중단은 미완료 작업 복구로 처리합니다. 상태는 기존 자료·작업 조회 API에서 확인합니다.

요청 핸들러는 분석 완료를 기다리지 않고 작업 등록 커밋 후 `202 Accepted`를 반환합니다. 커밋 후 HTTP 응답이 끊겨도 작업은 남고, 같은 회의록 확정 요청을 다시 보내면 이미 등록된 상태를 반환합니다. 커밋 자체가 실패하면 작업도 저장되지 않으며 요청을 다시 시도해야 합니다.

## 적용 순서

1. 새 코드를 배포하기 전에 DB migration `202609240001`을 검토하고 `alembic upgrade head`를 실행합니다. 새 `processing_jobs` 테이블은 RLS를 켜고 브라우저 접근 정책을 만들지 않습니다.
2. 기존 Celery 작업이 있다면 완료 상태를 확인하고 worker를 중지합니다. Celery broker의 미처리 메시지를 자동으로 가져오는 전환은 지원하지 않습니다.
3. Render API에 `PROCESSING_EXECUTOR=postgres`와 `PG_EXECUTOR_ENABLED=true`를 설정하고 새 버전을 배포합니다. 별도 worker를 준비했다면 API의 `PG_EXECUTOR_ENABLED`를 `false`로 설정합니다. 프론트 환경변수 변경은 없습니다.
4. 짧은 녹음으로 STT → 검토·편집 → 확정 → 분석을 확인합니다. 이미 실패한 자료는 화면에서 다시 시도합니다.

Docker에서는 [선택 실행 구성](docker-deployment.md#postgresql-실행기만-사용하는-poc)으로 API와 프론트만 실행할 수 있습니다. 원본 파일은 계속 Supabase Storage를 사용합니다.

기본값은 프로세스당 동시 실행 1건, lease 120초(`PG_EXECUTOR_LEASE_SECONDS`), 최초 조회 간격 2초(`PG_EXECUTOR_POLL_SECONDS`)입니다. 작업이 없으면 조회 간격을 최대 60초까지 늘리고, 같은 API 프로세스에서 작업을 등록하면 즉시 깨웁니다. 정상 종료는 실행 중 작업을 다시 대기 상태로 돌리고, 강제 종료는 lease 만료 후 복구합니다.

## 무료 Render의 실행 범위

무료 Web Service는 외부 요청 없이 15분이 지나면 잠들고, 다음 요청에 다시 기동합니다. 대기 작업은 DB에 남지만 잠든 동안 계속 처리된다는 보장은 없습니다. 재시작·재배포 때도 로컬 파일은 유지되지 않습니다. 임의 keep-alive나 유료 서비스 추가, 리전 변경은 하지 않습니다. STT·LLM 공급자 사용료는 서버 플랜과 별개입니다.

근거: [Render 무료 서비스 문서](https://render.com/docs/free), 2026-09-19 확인.

## PoC 이후 Airflow

Airflow 도입은 이번 범위에 포함하지 않습니다. 실행기와 분석 진입점을 분리해 두고, PoC 종료 후 다음 순서로 옮깁니다.

1. `원본 읽기 → 문서 파싱 또는 STT → 검토 대기`와 `확정된 회의록 → 청크·임베딩 → 관계 추출 → 그래프·컨텍스트 저장`을 독립 작업으로 나눕니다. 사람의 검토가 끝나기까지 worker를 점유하지 않고, 확정 이벤트가 후속 실행을 시작하도록 합니다.
2. DAG에는 source ID, 확정된 revision, 실행 ID처럼 작은 참조만 전달합니다. 원본·대본·추출 결과·체크포인트는 DB/Storage에 두고 API 키는 전달하지 않습니다.
3. 각 단계의 재실행·중복 적용 방지·체크포인트 계약을 먼저 고정한 뒤 Airflow에서 순서, 재시도, 제한 시간, 관측을 관리합니다.
4. PostgreSQL 실행기와 Airflow가 동시에 같은 revision을 처리하지 않도록 전환 중 소유권을 하나로 유지합니다. 기존 작업을 마친 뒤 신규 작업부터 전환합니다.

Airflow DAG는 작업 순서와 의존성을 관리하므로 도메인 분석 로직을 DAG 파일 안으로 옮길 필요는 없습니다. [Airflow DAG 문서](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dags.html)
