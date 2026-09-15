---
source_id: 00000000-0000-4000-8000-000000000003
authored_at: 2026-09-08T18:00:00+09:00
author: 이지은
type: report
---

# Context 캐시 PoC 결과

최근 Context 조회 결과를 Redis에 5분간 캐시한 결과 p95 응답 시간이 1.8초에서
320ms로 감소했다. 캐시 미스 시에는 기존 PostgreSQL 조회를 사용하며, Context가
갱신되면 해당 워크스페이스 캐시 키를 무효화했다.

