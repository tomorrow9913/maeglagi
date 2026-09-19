# Context data model

Supabase Auth의 `auth.users`가 사용자 원장입니다. 애플리케이션 테이블은 사용자
프로필을 중복하지 않고 모두 `owner_id`로 Auth user를 참조합니다.

```text
auth.users
    └── workspaces ── context_stores (프로젝트의 현재 상황, 워크스페이스당 1행)
          └── sources ── object_path ──> Supabase Storage
                └── chunks ── embedding ──> pgvector
                      └── contexts
```

- `chunks`는 `(source_id, position)`이 유일하며 문서 구간 또는 오디오 시간 구간과
  1536차원 embedding을 저장합니다.
- `contexts`는 event, decision, task, fact, summary를 저장하며 항상 `source_id`,
  선택적으로 `chunk_id`, `occurred_at`을 가져 근거로 되돌아갈 수 있습니다.
- 모든 PostgreSQL 테이블은 `workspace_id`와 `owner_id`를 보유하고 RLS로 소유권을
  검사합니다.
- Neo4j의 Entity와 Relation에는 원문을 복제하지 않습니다. 최소 식별 속성과
  `source_id`, `chunk_id`, `timestamp`만 저장해 PostgreSQL/Storage의 근거를 참조합니다.
- 같은 개체의 다른 표기는 하나의 Entity 노드로 병합합니다. 노드는 대표 `name`과 다른 표기
  `aliases`, 정규화된 병합 키 `keys`, 근거가 된 `source_ids`를 가집니다. 노드 id는
  `workspace + kind + 정규화된 이름`에서 결정되어 같은 소스를 다시 처리해도 upsert됩니다.
- 이름만으로는 동명이인을 구분할 수 없으므로 이메일 등 원문에 적힌 식별 정보를 `identifiers`로
  함께 저장합니다. 식별 정보가 겹치면 이름이 달라도 같은 노드, 이름이 같아도 식별 정보가 서로
  다르면 다른 노드입니다. 식별 정보가 있는 노드의 id는 식별 정보에서 결정됩니다. 식별 정보 없이
  이름이 같은 후보가 여럿이면 추측하지 않고 합치지 않은 채 경고합니다.

스키마의 실행 가능한 기준은 `supabase/migrations`이며 Python 측 계약은 SQLModel과
`GraphEntity`/`GraphRelation` 모델입니다.

## Temporal 규칙

- Relation은 `valid_from`/`valid_to`를 가집니다. 원문이 시작을 밝히지 않으면 `valid_from`은 소스
  날짜이고, `valid_to`는 원문이 종료를 명시한 경우에만 기록합니다(비어 있으면 종료가 확인되지
  않은 상태). 종료가 시작보다 빠르면 `valid_to`를 버리고 경고합니다.
- 같은 관계(출발·도착·종류)의 유효 기간은 겹치지 않습니다. 새 기간이 저장된 기간과 겹치면 하나로
  합치며, 알려진 시작 중 가장 이른 값과 명시된 종료를 씁니다. 그래서 나중 소스가 종료를 밝히면
  열려 있던 관계가 닫힙니다. 종료 뒤에 다시 시작한 관계는 별도 기간으로 남습니다.
- 새 결정이 이전 결정을 명시적으로 대체한다고 원문이 밝힐 때만, 이전 Decision 노드의
  `superseded_by`가 새 Decision의 id를 가리킵니다. 대체되는 결정은 입력의 `known_decisions`
  이름과 정확히 일치해야 하며 이미 다른 결정으로 대체된 결정은 다시 대체하지 않습니다.
  다시 처리해도 `superseded_by`는 지워지지 않습니다.
- `TemporalQueries`가 결정 이력, 현재 유효한 결정, 특정 시점에 유효한 관계를 조회합니다.

## Context Store

Graph가 업무 세계의 **구조**라면 Context Store는 프로젝트의 **현재 상황**을 담당합니다. 워크스페이스마다
`context_stores` 한 행이 있고, 새 소스가 분석될 때마다 갱신됩니다.

- 필드: `subject`, `summary`, `current_state`, `open_issues`, `decisions`, `next_actions`,
  `updated_at`, `source_ids`(각 항목은 자신의 `source_refs` 원문 인용을 가집니다).
- 새 소스의 결정·이슈·할 일은 정규화한 이름을 키로 병합하고, 같은 소스를 다시 처리해도 중복되지
  않습니다. 명시적으로 대체된 결정은 `decisions`에서 빠집니다(이력은 `contexts`와 Graph에 남습니다).
- 모델은 `summary`와 `current_state` 서술을 쓰고, 소스가 끝났다고 **원문 그대로 인용해** 밝힌 이슈·
  할 일만 닫을 수 있습니다. 항목을 조용히 지울 수는 없습니다.
- 소스별 타임라인(`contexts`)은 구조화된 이벤트에서 만듭니다. 종류는 `decision`, `issue`, `task`,
  `event`이며, 결정 행은 자신이 대체하는 결정의 키를 `metadata.supersedes`로 가집니다.

## 모델 선택

서버는 모델 이름을 정하지 않습니다. 키를 등록하면 공급자에게 그 키로 쓸 수 있는 모델을 물어 용도별로
분류하고, 사용자가 고른 (공급자, 모델)을 `workspaces.model_settings`에 저장합니다.

- 용도: `answer`(답변), `extraction`(회의·문서 분석과 그래프 추출), `embedding`(검색 색인),
  `transcription`(녹음 받아쓰기). 각 용도는 그 공급자 API가 해당 기능을 지원할 때만 후보가 생깁니다.
- 어떤 기능이 되고 안 되는지는 공급자 이름이 아니라 **그 키가 제공하는 모델**로 정해집니다. 후보가
  하나도 없는 용도만 사용자에게 알립니다.
- 후보는 가벼운 모델과 별칭(날짜 스냅샷이 아닌 것)을 앞에 둡니다. 품질 순위가 아니라 미리 선택될
  값을 정하는 안정적인 순서입니다.
- **임베딩 모델은 워크스페이스를 만들 때 정하고 이후 바꿀 수 없습니다.** 모델마다 벡터가 달라 서로 섞어
  검색할 수 없기 때문입니다. PoC에서는 재색인 마이그레이션 대신 변경을 막습니다. 선택 없이 이미
  색인된 옛 워크스페이스는 배포 기본 모델을 기록하는 것만 허용합니다.
- 답변·분석(추출)·녹음 받아쓰기 모델은 저장된 데이터와 호환성 문제가 없어 자유롭게 바꿀 수 있습니다.
- 선택이 없는 워크스페이스는 배포 환경의 기본값(`*_model` 설정)으로 물러납니다.
- 질문 임베딩은 한 번만 만들어 일반 검색과 그래프 범위 검색이 함께 씁니다.

