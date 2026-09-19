import re
from collections.abc import AsyncIterator
from typing import Any

from app.modules.context_engine.application.provider import (
    ChatMessage,
    ChatRequest,
    ProviderAdapter,
)
from app.modules.context_engine.domain.context_store import ContextStoreState
from app.modules.context_engine.infrastructure.provider_adapters import ProviderError
from app.modules.retrieval.application.hybrid import RetrievalResult
from app.modules.retrieval.domain.answer import (
    done_event,
    error_event,
    sources_event,
    token_event,
)

NO_EVIDENCE = "질문과 관련된 근거를 찾지 못했습니다. 회의나 문서를 올린 뒤 다시 물어봐 주세요."
EMPTY_ANSWER = "모델이 답변을 만들지 못했습니다. 잠시 후 다시 시도해 주세요."

SYSTEM_PROMPT = (
    "당신은 '맥락이'입니다. 팀의 회의와 문서에서 뽑은 근거만으로 질문에 답합니다.\n"
    "규칙:\n"
    "1. 아래 [근거]에 적힌 내용으로만 답합니다. 근거에 없는 사실, 담당자, 날짜, 이유는 만들지 "
    "않습니다. 근거가 부족하면 부족하다고 말합니다.\n"
    "2. 근거를 인용할 때마다 문장 끝에 [1]처럼 근거 번호를 붙입니다. 목록에 없는 번호는 "
    "쓰지 않습니다.\n"
    "3. [현재 상황]의 '유효한 결정'에 없는 결정, 또는 '대체됨'으로 표시된 결정은 지금의 방침이라고 "
    "단정하지 않습니다. 이후 바뀌었을 수 있다고 밝히고, 무엇으로 대체됐는지 근거가 있으면 "
    "함께 말합니다.\n"
    "4. [현재 상황]과 [관계]는 방향을 잡는 참고일 뿐입니다. 사실 주장은 반드시 [근거]로 "
    "뒷받침합니다.\n"
    "5. 한국어로, 짧고 분명하게 답합니다."
)


def _format_time(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = int(seconds)
    return f", {total // 60:02d}:{total % 60:02d}"


def _store_section(store: ContextStoreState | None) -> str:
    if store is None or not (store.current_state or store.decisions or store.open_issues):
        return "(아직 정리된 현재 상황이 없습니다.)"
    lines = [f"프로젝트: {store.subject}"]
    if store.current_state:
        lines.append(f"현재 상태: {store.current_state}")
    lines.append("유효한 결정: " + (", ".join(d.title for d in store.decisions) or "없음"))
    lines.append("열린 이슈: " + (", ".join(i.title for i in store.open_issues) or "없음"))
    lines.append("다음 할 일: " + (", ".join(a.title for a in store.next_actions) or "없음"))
    return "\n".join(lines)


def _facts_section(retrieval: RetrievalResult) -> str:
    if not retrieval.facts:
        return "(찾은 관계가 없습니다.)"
    lines = []
    for fact in retrieval.facts:
        note = f" (대체됨: {', '.join(fact.superseded)})" if fact.superseded else ""
        lines.append(f"- {fact.source} -{fact.kind}-> {fact.target}{note}")
    return "\n".join(lines)


def build_messages(
    question: str, retrieval: RetrievalResult, store: ContextStoreState | None
) -> list[ChatMessage]:
    evidence = "\n\n".join(
        f"[{item.source.index}] ({'회의' if item.source.kind == 'meeting' else '문서'}: "
        f"{item.source.title}{_format_time(item.source.timestamp)})\n{item.text}"
        for item in retrieval.evidence
    )
    user = (
        f"[현재 상황]\n{_store_section(store)}\n\n"
        f"[관계]\n{_facts_section(retrieval)}\n\n"
        f"[근거]\n{evidence}\n\n"
        f"질문: {question}"
    )
    return [
        ChatMessage(role="system", content=SYSTEM_PROMPT),
        ChatMessage(role="user", content=user),
    ]


class CitationFilter:
    """Drops `[n]` citations that point at evidence that does not exist.

    Tokens arrive in arbitrary pieces (`"[", "1", "]"`), so a possible citation is held back until
    it is complete. `[1, 9]` keeps only the numbers that exist; text that merely starts with `[`
    (like `[참고]`) passes through unchanged.
    """

    _MAX_PENDING = 16

    def __init__(self, valid: set[int]) -> None:
        self.valid = valid
        self.pending = ""

    def feed(self, text: str) -> str:
        out: list[str] = []
        for char in text:
            if self.pending:
                self.pending += char
                if char == "]":
                    out.append(self._resolve(self.pending))
                    self.pending = ""
                elif char == "[":  # the earlier "[" was plain text; this one may start a citation
                    out.append(self.pending[:-1])
                    self.pending = char
                elif not (char.isdigit() or char in ", ") or len(self.pending) > self._MAX_PENDING:
                    out.append(self.pending)  # not a citation after all
                    self.pending = ""
            elif char == "[":
                self.pending = char
            else:
                out.append(char)
        return "".join(out)

    def flush(self) -> None:
        """End of stream: a half-written `[1` is dropped rather than shown broken."""
        self.pending = ""

    def _resolve(self, candidate: str) -> str:
        numbers = re.findall(r"\d+", candidate)
        if not numbers:
            return candidate  # "[]" or "[ ]": leave as written
        kept = [n for n in numbers if int(n) in self.valid]
        if len(kept) == len(numbers):
            return candidate
        return f"[{', '.join(kept)}]" if kept else ""


async def _generate(
    adapter: ProviderAdapter, api_key: str, request: ChatRequest
) -> AsyncIterator[str]:
    """Stream from the provider; a provider without streaming answers in one piece."""
    try:
        async for piece in adapter.stream(request, api_key):
            yield piece
    except NotImplementedError:
        response = await adapter.chat(request, api_key)
        yield response.text


async def answer_events(
    *,
    adapter: ProviderAdapter,
    api_key: str,
    model: str,
    question: str,
    retrieval: RetrievalResult,
    store: ContextStoreState | None,
) -> AsyncIterator[dict[str, Any]]:
    """`sources` first, then `token`s, then `done`; anything unanswerable ends in one `error`.

    With no evidence the model is never called: it would only make something up.
    """
    if not retrieval.evidence:
        yield error_event(NO_EVIDENCE)
        return

    yield sources_event([item.source for item in retrieval.evidence])

    request = ChatRequest(
        messages=build_messages(question, retrieval, store),
        model=model,
        temperature=0.2,
    )
    citations = CitationFilter({item.source.index for item in retrieval.evidence})
    produced = False
    try:
        async for piece in _generate(adapter, api_key, request):
            text = citations.feed(piece)
            if text:
                produced = True
                yield token_event(text)
        citations.flush()
    except ProviderError as exc:
        yield error_event(str(exc))
        return

    if not produced:
        yield error_event(EMPTY_ANSWER)
        return
    yield done_event()
