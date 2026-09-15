# Contracts

이 디렉터리는 팀 간 계약의 단일 진입점입니다. 계약 변경은 프론트·백엔드·기획이
함께 리뷰하고, 호환되지 않는 변경은 `version` 또는 `schema_version`을 올립니다.

## PoC v1 고정 계약

- `ontology/entities.yaml`: 허용하는 Entity 10종
- `ontology/relations.yaml`: 허용하는 Relation 10종과 Temporal 규칙
- `extraction-rules.md`: Decision, Task, Issue, Event 판정 및 근거 규칙
- `schemas/meeting-analysis.schema.json`: 회의 structured output
- `schemas/document-analysis.schema.json`: 문서 structured output
- `schemas/context.schema.json`: Context Store snapshot
- `schemas/common.schema.json`: 공통 source reference와 추출 항목
- `seeds/redis-adoption/`: end-to-end 데모 기준 입력과 기대 결과

PoC 중 Entity/Relation 종류를 추가하지 않습니다. 표현이 부족하면 우선 `RELATED_TO`와
속성으로 처리하고, 확장은 Phase 2에서 계약 버전을 올려 진행합니다.

`openapi.yaml`은 HTTP 계약의 진입점입니다. 실제 구현이 시작된 뒤에는 FastAPI가
생성한 `/openapi.json`을 기준으로 동기화하고 CI에서 차이를 검사합니다.
