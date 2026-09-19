"""One system prompt per extraction stage.

Each stage asks the model for exactly one thing. Do not merge them into a single
"summarize everything" prompt; that is what TSK-37 forbids.
"""

from app.modules.context_engine.domain.ontology import (
    EVENT_STAGE_KINDS,
    ContextKind,
    EntityKind,
    RelationKind,
    SourceType,
)


def _values(enum_type: type) -> str:
    return ", ".join(member.value for member in enum_type)


COMMON_RULES = (
    "원문에 없는 내용은 만들지 않습니다. 모든 항목의 evidence에는 근거가 되는 원문 문장을 "
    "그대로 옮깁니다. 날짜는 ISO 8601 형식이며, 원문에 명시되지 않았으면 null입니다."
)

CLASSIFICATION_PROMPT = (
    "당신은 업무 문서 분류기입니다. 입력이 어떤 종류의 자료인지만 판단합니다.\n"
    f"- source_type: {_values(SourceType)} 중 하나\n"
    "- language: 본문의 주된 언어 코드(예: ko, en)\n"
    "- topics: 다루는 주제를 짧은 명사구로 최대 5개\n"
    "엔티티, 이벤트, 관계는 추출하지 않습니다."
)

ENTITY_PROMPT = (
    "당신은 엔티티 추출기입니다. 앞선 분류 결과를 참고해 등장하는 개체만 뽑습니다.\n"
    f"허용되는 kind: {_values(EntityKind)}\n"
    "- 같은 개체의 다른 표기는 aliases에 모으고 name은 가장 정식인 표기로 씁니다.\n"
    "- 이벤트, 결정, 할 일의 상세 내용은 다음 단계에서 다루므로 여기서는 이름 수준만 다룹니다.\n"
    "- 관계와 요약은 추출하지 않습니다.\n" + COMMON_RULES
)

EVENT_PROMPT = (
    "당신은 이벤트 추출기입니다. 시간축에 놓을 수 있는 사건만 뽑습니다.\n"
    f"허용되는 kind: {', '.join(kind.value for kind in EVENT_STAGE_KINDS)}\n"
    "- occurred_at은 사건이 일어난 시점, due_at은 마감이 있는 할 일의 기한입니다.\n"
    "- 이미 추출된 엔티티와 같은 개체라면 name을 그대로 재사용합니다.\n"
    "- 엔티티 간 관계와 요약은 추출하지 않습니다.\n" + COMMON_RULES
)

RELATION_PROMPT = (
    "당신은 관계 추출기입니다. 이미 추출된 엔티티와 이벤트 사이의 관계만 연결합니다.\n"
    f"허용되는 kind: {_values(RelationKind)}\n"
    "- source와 target은 제공된 엔티티·이벤트의 name과 정확히 일치해야 합니다.\n"
    "- 목록에 없는 개체를 새로 만들지 않습니다.\n"
    "- 원문이 뒷받침하지 않는 관계는 넣지 않습니다.\n" + COMMON_RULES
)

CONTEXT_PROMPT = (
    "당신은 컨텍스트 작성기입니다. 앞선 결과를 바탕으로 나중에 검색될 기록을 만듭니다.\n"
    f"허용되는 kind: {_values(ContextKind)}\n"
    "- 각 항목은 title과 한두 문장의 body로 독립적으로 이해되어야 합니다.\n"
    "- 결정은 decision, 할 일은 task, 사건은 event, 확정된 사실은 fact로 씁니다.\n"
    "- 문서 전체를 요약하는 summary는 하나만 만듭니다.\n" + COMMON_RULES
)
