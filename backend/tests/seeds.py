"""Four demo seeds from the PoC v1 contract scenario ("Redis 도입" 이유 추적).

These are placeholders for contracts/seeds/redis-adoption/, which is not in the repo yet.
Each seed carries the source text and the stage outputs a correct model is expected to return.
Every source_ref is a verbatim sentence from that seed's text.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Seed:
    name: str
    kind: str  # "meeting" or "document"
    title: str
    text: str
    responses: dict[str, Any] = field(default_factory=dict)


def entity(
    name: str,
    kind: str,
    refs: list[str],
    aliases: list[str] | None = None,
    identifiers: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "kind": kind,
        "aliases": aliases or [],
        "identifiers": identifiers or [],
        "source_refs": refs,
    }


def event(
    name: str,
    kind: str,
    description: str,
    refs: list[str],
    occurred_at: str | None = None,
    due_at: str | None = None,
    supersedes: str | None = None,
) -> dict:
    return {
        "name": name,
        "kind": kind,
        "description": description,
        "occurred_at": occurred_at,
        "due_at": due_at,
        "supersedes": supersedes,
        "source_refs": refs,
    }


def relation(
    source: str,
    target: str,
    kind: str,
    refs: list[str],
    valid_from: str | None = None,
    valid_to: str | None = None,
) -> dict:
    return {
        "source": source,
        "target": target,
        "kind": kind,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "source_refs": refs,
    }


def context(kind: str, title: str, body: str, refs: list[str], at: str | None = None) -> dict:
    return {"kind": kind, "title": title, "body": body, "occurred_at": at, "source_refs": refs}


def responses(
    source_type: str,
    entities: list[dict],
    events: list[dict],
    relations: list[dict],
    contexts: list[dict],
    planning: dict | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "classification": {"source_type": source_type, "language": "ko", "topics": ["캐시"]},
        "entity": {"entities": entities},
        "event": {"events": events},
        "relation": {"relations": relations},
        "context": {"contexts": contexts},
    }
    if planning is not None:
        out["planning"] = planning
    return out


PLAN_TEXT = """API 성능 개선 기획서 (2026-09-01)
프로젝트: API 성능 개선
목표: 조회 API의 p95 응답 시간을 500ms 이하로 낮춘다.
담당: 박지훈
초기에는 캐시를 두지 않고 기준 성능을 측정한다.
일정: 9/05 성능 회의, 9/12 아키텍처 회의에서 구조를 확정한다.
연관 시스템: PostgreSQL, Redis
"""

PERF_MEETING_TEXT = """2026-09-05 성능 회의
참석: 박지훈, 최서연
서연: 측정해 보니 조회 API의 p95가 1.8초입니다. 목표인 500ms를 크게 넘습니다.
지훈: 응답 지연이 가장 큰 문제입니다. 캐시 도입 가능성을 검토해야 합니다.
결론적으로 박지훈이 9/08까지 Redis 캐시 PoC를 진행하기로 했습니다.
"""

POC_TEXT = """Redis 캐시 PoC 결과 (2026-09-08)
작성: 박지훈
Redis 캐시를 조회 API 앞단에 적용해 측정했다.
결과: p95 응답 시간이 320ms로 목표 500ms를 달성했다.
운영 도입 여부는 아키텍처 회의에서 결정한다.
"""

ARCH_MEETING_TEXT = """2026-09-12 아키텍처 회의
참석: 박지훈, 최서연, 이도윤
도윤: PoC 결과 p95가 320ms로 목표를 달성했으니 Redis를 도입합시다.
서연: 다만 데이터 정합성 문제가 생기지 않게 재생성 가능한 캐시로만 사용해야 합니다.
Redis 도입을 결정했고, 재생성 가능한 캐시로만 사용하기로 합의했습니다.
다음 주까지 최서연이 캐시 무효화 규칙 초안을 작성하기로 했습니다.
"""

SEEDS = [
    Seed(
        name="plan-0901",
        kind="document",
        title="API 성능 개선 기획서",
        text=PLAN_TEXT,
        responses=responses(
            "plan",
            [
                entity("API 성능 개선", "Project", ["프로젝트: API 성능 개선"]),
                entity("박지훈", "Person", ["담당: 박지훈"]),
                entity("Redis", "Technology", ["연관 시스템: PostgreSQL, Redis"]),
                entity("PostgreSQL", "Technology", ["연관 시스템: PostgreSQL, Redis"]),
            ],
            [
                event(
                    "성능 회의",
                    "Meeting",
                    "성능 측정 결과 공유",
                    ["일정: 9/05 성능 회의, 9/12 아키텍처 회의에서 구조를 확정한다."],
                    "2026-09-05",
                )
            ],
            [relation("박지훈", "API 성능 개선", "WORKS_ON", ["담당: 박지훈"])],
            [
                context(
                    "summary",
                    "API 성능 개선 기획",
                    "조회 API p95를 500ms 이하로 낮추는 계획이다.",
                    ["목표: 조회 API의 p95 응답 시간을 500ms 이하로 낮춘다."],
                )
            ],
            planning={
                "project": "API 성능 개선",
                "goal": "조회 API의 p95 응답 시간을 500ms 이하로 낮춘다.",
                "owners": ["박지훈"],
                "schedule": [
                    {"milestone": "성능 회의", "date": "2026-09-05"},
                    {"milestone": "아키텍처 회의", "date": "2026-09-12"},
                ],
                "related_systems": ["PostgreSQL", "Redis"],
                "source_refs": ["연관 시스템: PostgreSQL, Redis"],
            },
        ),
    ),
    Seed(
        name="meeting-0905",
        kind="meeting",
        title="성능 회의",
        text=PERF_MEETING_TEXT,
        responses=responses(
            "meeting",
            [
                entity("박지훈", "Person", ["참석: 박지훈, 최서연"]),
                entity("최서연", "Person", ["참석: 박지훈, 최서연"], aliases=["서연"]),
            ],
            [
                event(
                    "성능 회의",
                    "Meeting",
                    "조회 API 성능 점검",
                    ["2026-09-05 성능 회의"],
                    "2026-09-05",
                ),
                event(
                    "조회 API 응답 지연",
                    "Issue",
                    "p95가 1.8초로 목표 500ms를 넘는다.",
                    ["측정해 보니 조회 API의 p95가 1.8초입니다."],
                ),
                event(
                    "Redis 캐시 PoC 진행",
                    "Task",
                    "Redis 캐시 PoC를 수행한다.",
                    ["결론적으로 박지훈이 9/08까지 Redis 캐시 PoC를 진행하기로 했습니다."],
                    due_at="2026-09-08",
                ),
            ],
            [
                relation("박지훈", "성능 회의", "PARTICIPATED_IN", ["참석: 박지훈, 최서연"]),
                relation("최서연", "성능 회의", "PARTICIPATED_IN", ["참석: 박지훈, 최서연"]),
                relation(
                    "Redis 캐시 PoC 진행",
                    "박지훈",
                    "ASSIGNED_TO",
                    ["결론적으로 박지훈이 9/08까지 Redis 캐시 PoC를 진행하기로 했습니다."],
                ),
            ],
            [
                context(
                    "summary",
                    "성능 회의 요약",
                    "p95 1.8초 지연을 확인하고 Redis 캐시 PoC를 진행하기로 했다.",
                    ["측정해 보니 조회 API의 p95가 1.8초입니다."],
                )
            ],
        ),
    ),
    Seed(
        name="poc-0908",
        kind="document",
        title="Redis 캐시 PoC 결과",
        text=POC_TEXT,
        responses=responses(
            "report",
            [
                entity("박지훈", "Person", ["작성: 박지훈"]),
                entity("Redis", "Technology", ["Redis 캐시를 조회 API 앞단에 적용해 측정했다."]),
            ],
            [
                event(
                    "Redis 캐시 PoC 완료",
                    "Event",
                    "p95 320ms 달성",
                    ["결과: p95 응답 시간이 320ms로 목표 500ms를 달성했다."],
                    "2026-09-08",
                )
            ],
            [relation("박지훈", "Redis 캐시 PoC 완료", "CREATED", ["작성: 박지훈"])],
            [
                context(
                    "fact",
                    "PoC 결과",
                    "Redis 캐시 적용 후 p95가 320ms로 목표를 달성했다.",
                    ["결과: p95 응답 시간이 320ms로 목표 500ms를 달성했다."],
                    "2026-09-08",
                ),
                context(
                    "summary",
                    "Redis PoC 요약",
                    "Redis 캐시가 목표 성능을 달성했다.",
                    ["결과: p95 응답 시간이 320ms로 목표 500ms를 달성했다."],
                ),
            ],
        ),
    ),
    Seed(
        name="meeting-0912",
        kind="meeting",
        title="아키텍처 회의",
        text=ARCH_MEETING_TEXT,
        responses=responses(
            "meeting",
            [
                entity("박지훈", "Person", ["참석: 박지훈, 최서연, 이도윤"]),
                entity("최서연", "Person", ["참석: 박지훈, 최서연, 이도윤"], aliases=["서연"]),
                entity("이도윤", "Person", ["참석: 박지훈, 최서연, 이도윤"], aliases=["도윤"]),
                entity("Redis", "Technology", ["Redis 도입을 결정했고"]),
            ],
            [
                event(
                    "아키텍처 회의",
                    "Meeting",
                    "캐시 도입 여부 결정",
                    ["2026-09-12 아키텍처 회의"],
                    "2026-09-12",
                ),
                event(
                    "Redis 도입 결정",
                    "Decision",
                    "재생성 가능한 캐시로만 사용한다.",
                    ["Redis 도입을 결정했고, 재생성 가능한 캐시로만 사용하기로 합의했습니다."],
                    "2026-09-12",
                ),
                event(
                    "캐시 무효화 규칙 초안 작성",
                    "Task",
                    "캐시 무효화 규칙 초안을 작성한다.",
                    ["다음 주까지 최서연이 캐시 무효화 규칙 초안을 작성하기로 했습니다."],
                ),
            ],
            [
                relation(
                    "박지훈", "아키텍처 회의", "PARTICIPATED_IN", ["참석: 박지훈, 최서연, 이도윤"]
                ),
                relation(
                    "최서연", "아키텍처 회의", "PARTICIPATED_IN", ["참석: 박지훈, 최서연, 이도윤"]
                ),
                relation(
                    "이도윤", "아키텍처 회의", "PARTICIPATED_IN", ["참석: 박지훈, 최서연, 이도윤"]
                ),
                relation(
                    "Redis 도입 결정",
                    "아키텍처 회의",
                    "DECIDED_IN",
                    ["Redis 도입을 결정했고, 재생성 가능한 캐시로만 사용하기로 합의했습니다."],
                ),
                relation(
                    "캐시 무효화 규칙 초안 작성",
                    "최서연",
                    "ASSIGNED_TO",
                    ["다음 주까지 최서연이 캐시 무효화 규칙 초안을 작성하기로 했습니다."],
                ),
            ],
            [
                context(
                    "decision",
                    "Redis 도입",
                    "PoC 결과를 근거로 Redis를 재생성 가능한 캐시로만 도입한다.",
                    ["Redis 도입을 결정했고, 재생성 가능한 캐시로만 사용하기로 합의했습니다."],
                    "2026-09-12",
                ),
                context(
                    "summary",
                    "아키텍처 회의 요약",
                    "Redis 도입을 결정했다.",
                    ["Redis 도입을 결정했고, 재생성 가능한 캐시로만 사용하기로 합의했습니다."],
                ),
            ],
        ),
    ),
]
