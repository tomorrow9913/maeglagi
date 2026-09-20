/**
 * 답변 본문을 화면에 그릴 조각으로 나눕니다.
 *
 * LLM이 쓰는 표기 가운데 `**굵게**`, `` `코드` ``, `- `/`1. ` 목록만 다루고 나머지는
 * 글자 그대로 둡니다. HTML을 만들지 않고 구조만 돌려주므로, 본문에 태그가 들어 있어도
 * React가 텍스트로 그립니다. 인용 번호 `[n]`은 굵은 글씨와 목록 안에서도 그대로 살립니다.
 */

export type InlineNode =
  | { type: "text"; text: string }
  | { type: "code"; text: string }
  | { type: "bold"; children: InlineNode[] }
  /** 본문의 `[n]`. `offset`은 전체 본문에서의 위치로, 렌더링 key로 씁니다. */
  | { type: "citation"; index: number; raw: string; offset: number };

export type AnswerBlock =
  | { type: "paragraph"; children: InlineNode[] }
  | { type: "list"; ordered: boolean; start: number; items: InlineNode[][] };

/** 코드 → 굵게 → 인용 순서로 먼저 맞는 것을 고릅니다. 코드 안의 `[1]`은 인용이 아닙니다. */
const INLINE = /`([^`\n]+)`|\*\*(?=\S)([^\n]*?\S)\*\*|\[(\d+)\]/g;
const BULLET = /^\s*[-*]\s+(.*)$/;
const ORDERED = /^\s*(\d{1,3})[.)]\s+(.*)$/;

function pushText(nodes: InlineNode[], text: string) {
  if (!text) return;
  const last = nodes[nodes.length - 1];
  if (last?.type === "text") last.text += text;
  else nodes.push({ type: "text", text });
}

/** 한 줄 또는 한 문단 안의 표기를 나눕니다. `base`는 전체 본문에서 이 조각이 시작하는 위치입니다. */
export function parseInline(text: string, base = 0, allowBold = true): InlineNode[] {
  const nodes: InlineNode[] = [];
  const pattern = new RegExp(INLINE.source, "g");
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    const [raw, code, bold, citation] = match;
    if (bold !== undefined && !allowBold) {
      // 굵게 안의 굵게는 다루지 않습니다. 여는 표시만 글자로 남기고 그 뒤부터 다시 봅니다.
      pattern.lastIndex = match.index + 2;
      continue;
    }
    pushText(nodes, text.slice(cursor, match.index));
    if (code !== undefined) {
      nodes.push({ type: "code", text: code });
    } else if (bold !== undefined) {
      nodes.push({ type: "bold", children: parseInline(bold, base + match.index + 2, false) });
    } else {
      nodes.push({ type: "citation", index: Number(citation), raw, offset: base + match.index });
    }
    cursor = match.index + raw.length;
  }
  pushText(nodes, text.slice(cursor));
  return nodes;
}

/** 본문 전체를 문단과 목록으로 나눕니다. 빈 줄은 문단을 가릅니다. */
export function parseAnswer(text: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = [];
  let paragraph: { start: number; lines: string[] } | undefined;
  let offset = 0;

  const flush = () => {
    if (!paragraph) return;
    blocks.push({
      type: "paragraph",
      children: parseInline(paragraph.lines.join("\n"), paragraph.start),
    });
    paragraph = undefined;
  };

  for (const line of text.split("\n")) {
    const lineStart = offset;
    offset += line.length + 1;

    const bullet = BULLET.exec(line);
    const ordered = bullet ? null : ORDERED.exec(line);
    const content = bullet ? bullet[1] : ordered ? ordered[2] : undefined;

    if (content !== undefined) {
      flush();
      const isOrdered = Boolean(ordered);
      const item = parseInline(content, lineStart + (line.length - content.length));
      const last = blocks[blocks.length - 1];
      if (last?.type === "list" && last.ordered === isOrdered) last.items.push(item);
      else {
        blocks.push({
          type: "list",
          ordered: isOrdered,
          start: ordered ? Number(ordered[1]) : 1,
          items: [item],
        });
      }
    } else if (line.trim() === "") {
      flush();
    } else if (paragraph) {
      paragraph.lines.push(line);
    } else {
      paragraph = { start: lineStart, lines: [line] };
    }
  }
  flush();
  return blocks;
}
