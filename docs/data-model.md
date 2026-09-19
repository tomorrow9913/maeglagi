# Context data model

Supabase Auth의 `auth.users`가 사용자 원장입니다. 애플리케이션 테이블은 사용자
프로필을 중복하지 않고 모두 `owner_id`로 Auth user를 참조합니다.

```text
auth.users
    └── workspaces
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

스키마의 실행 가능한 기준은 `supabase/migrations`이며 Python 측 계약은 SQLModel과
`GraphEntity`/`GraphRelation` 모델입니다.
