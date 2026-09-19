# 데모 상태 스냅샷 복원 (TSK-49)

기존 `app.demo_smoke`는 입력을 업로드하고 실제 모델로 분석한다. 이 도구는 준비된
데모 워크스페이스의 원문, 처리된 청크와 실제 벡터, Timeline, Context Store, 그래프를
저장하고 새 워크스페이스로 복원한다. 복원 과정에서 LLM·임베딩 모델을 호출하지 않는다.

## 준비

분석이 모두 끝난 데모 워크스페이스와 서버용 PostgreSQL/Neo4j/Storage 접근 설정이
필요하다. 작업 중인 일반 워크스페이스 대신 변경이 멈춘 데모 전용 데이터를 사용한다.
연결 정보는 환경변수로 설정하며 이 도구는 `.env`를 읽거나 수정하지 않는다.
벡터를 만든 실제 embedding provider/model이 워크스페이스에 명시적으로 저장돼 있어야
한다. 모델을 모르는 기존 벡터를 다른 배포의 기본 모델과 섞어 복원하지 않는다.

- `DEMO_DATABASE_URL`: 서버 PostgreSQL 연결 URL
- `DEMO_NEO4J_URL`, `DEMO_NEO4J_USER`, `DEMO_NEO4J_PASSWORD`
- `DEMO_STORAGE_URL`, `DEMO_STORAGE_KEY`: Supabase URL과 서버용 Storage 키

각 변수 이름은 `--database-url-env` 등 CLI 옵션으로 변경할 수 있다. 키 값이나
연결 문자열을 명령행 인수·채팅·실행 보고서에 넣지 않는다.

## 저장 및 복원

```bash
cd backend
# 계획 확인: 네트워크 연결이나 쓰기 없이 실행한다.
uv run python -m app.demo_snapshot export \
  --owner <사용자-UUID> --source-workspace <데모-workspace-UUID> \
  --artifact /안전한/경로/demo.json

# 준비된 데모를 한 번 저장한다.
uv run python -m app.demo_snapshot export \
  --owner <사용자-UUID> --source-workspace <데모-workspace-UUID> \
  --artifact /안전한/경로/demo.json --execute

# 장애 시 저장본을 검사하고 새 워크스페이스로 복원한다.
uv run python -m app.demo_snapshot restore \
  --owner <동일한-사용자-UUID> --artifact /안전한/경로/demo.json --execute
```

`--execute` 없이 restore를 실행하면 저장본 무결성과 소유자를 검증하고 계획만
출력한다. 복원 결과의 workspace ID를 사용해 앱에서 확인한다. 기존 워크스페이스를
덮어쓰지 않으며 동일 복원 대상이 이미 존재하면 중단한다.

저장본에는 원문과 음성 등 업무 데이터가 들어 있으므로 접근을 제한해야 한다.
Provider API 키·Vault secret은 포함하지 않는다. 복원 후 새 워크스페이스에 BYOK 키를
등록해야 Ask 등 실제 모델 호출이 가능하다. 모델 설정과 벡터 데이터는 보존한다.

## 검증 및 한계

TSK-49의 60초 조건은 실제 저장소에서 측정해야 한다. 자동 테스트 통과는 원격 환경의
복원 시간이나 발표 준비 완료를 뜻하지 않는다. 복원 후 다음을 확인한다.

1. 소스 개수와 원문·청크가 저장본과 같다.
2. Timeline, Graph, 현재 맥락의 근거가 복원된 소스로 연결된다.
3. BYOK 등록 후 기존 임베딩 모델로 검색하고 근거 포함 Ask 응답을 확인한다.
4. 전체 복원 소요 시간과 후속 키 등록 시간을 구분해 기록한다.

PostgreSQL·Neo4j·Storage 사이에는 단일 분산 트랜잭션이 없다. 실패 시 생성한 데이터를
정리하지만 네트워크 장애로 정리가 실패할 수 있으므로 잔여 리소스 보고를 확인한다.
SQL commit 중 오류가 나면 실제 반영 여부가 불확실할 수 있다. 이때 별도 연결로 새
워크스페이스의 반영을 확인한다. 이미 반영된 경우에는 `commit_verified_after_error`를
보고하고 그래프와 Storage 객체를 보존한다. 별도 조회에서 보이지 않는 것만으로는 진행 중인
commit의 실패를 증명할 수 없다. 원래 SQL 트랜잭션을 종료한 뒤 별도 트랜잭션에서 같은
워크스페이스 ID의 예약 행 삽입이 성공하면, 그 트랜잭션을 유지하면서 이번 시도의 그래프와
Storage 객체를 정리한다. 예약이 실패하거나 결과가 불명확하면 외부 데이터를 보존해 조사한다.
SQL commit에도 남은 60초 제한을 적용한다. 제한 뒤 commit 반영이 확인되면 데이터를
보존하고 `deadline_exceeded`를 보고하며, 제한 뒤 성공적으로 끝난 commit은 시간 초과
오류와 함께 이미 반영된 데이터가 보존되었음을 알린다.
실제 복원 실행과 시간 측정은 아직 수행하지 않았다.
