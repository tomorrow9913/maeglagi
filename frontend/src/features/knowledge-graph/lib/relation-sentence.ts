import type { EntityType, RelationType } from "@/lib/api";

import { relationLabel } from "./graph-style";

/**
 * 상세 패널의 연결을 `←참여` 같은 기호 대신 문장으로 풉니다.
 *
 * 한국어는 "{이름}{조사} {서술어}" 순서라서 이름 뒤에 붙일 꼬리만 만들어 돌려줍니다.
 * 화면은 이름을 말줄임하고 꼬리는 항상 보이게 그립니다. 서술어는 캔버스의 엣지 라벨과
 * 같은 `relationLabel`을 써서 두 화면의 말이 어긋나지 않게 합니다.
 */

/** 앞이 받침 있는 말 뒤, 뒤가 받침 없는 말 뒤에 오는 꼴입니다. */
type Josa = "이/가" | "을/를" | "과/와" | "으로/로";

/** 숫자로 끝나는 이름은 읽는 소리(영·일·이…)의 받침을 따릅니다. */
const DIGIT_FINAL: Record<string, "none" | "rieul" | "other"> = {
  "0": "other",
  "1": "rieul",
  "2": "none",
  "3": "other",
  "4": "none",
  "5": "none",
  "6": "other",
  "7": "rieul",
  "8": "rieul",
  "9": "none",
};

function finalSound(word: string): "none" | "rieul" | "other" | "unknown" {
  // 닫는 괄호·따옴표·공백은 소리가 없으므로 그 앞 글자를 봅니다.
  const last = word.replace(/[\s)\]}"'”’.,!?]+$/u, "").at(-1);
  if (!last) return "unknown";
  if (last in DIGIT_FINAL) return DIGIT_FINAL[last];

  const code = last.charCodeAt(0);
  if (code < 0xac00 || code > 0xd7a3) return "unknown";
  const final = (code - 0xac00) % 28;
  if (final === 0) return "none";
  return final === 8 ? "rieul" : "other";
}

/** 받침에 맞는 조사를 고릅니다. 영문처럼 소리를 알 수 없으면 `이(가)` 식으로 둘 다 적습니다. */
export function josa(word: string, kind: Josa): string {
  const sound = finalSound(word);
  const [withFinal, withoutFinal] = kind.split("/");

  if (sound === "unknown") {
    return kind === "으로/로" ? "(으)로" : `${withFinal}(${withoutFinal})`;
  }
  if (kind === "으로/로") return sound === "other" ? "으로" : "로";
  return sound === "none" ? withoutFinal : withFinal;
}

export type RelationSentenceInput = {
  relation: RelationType;
  /** `out`: 보고 있는 노드에서 나가는 관계, `in`: 상대 노드에서 들어오는 관계 */
  direction: "out" | "in";
  /** 관계의 출발 노드 종류. `decided`는 누가 출발점이냐에 따라 뜻이 달라집니다. */
  sourceType: EntityType;
  /** 상대 노드의 이름 */
  otherLabel: string;
};

/** 이름 뒤에 붙는 꼬리. 예: "이 참여", "에 참여", "와 관련" */
export function relationTail({
  relation,
  direction,
  sourceType,
  otherLabel,
}: RelationSentenceInput): string {
  const verb = relationLabel[relation];
  const subject = josa(otherLabel, "이/가");
  const object = josa(otherLabel, "을/를");

  switch (relation) {
    // 사람 → 이벤트·프로젝트
    case "participates_in":
      return direction === "out" ? `에 ${verb}` : `${subject} ${verb}`;
    // 업무 → 사람
    case "assigned_to":
      return direction === "out" ? `${subject} ${verb}` : `${object} ${verb}`;
    // 막는 쪽 → 막히는 쪽
    case "blocks":
      return direction === "out" ? `${object} ${verb}` : `${subject} ${verb}`;
    // 새 결정 → 이전 결정
    case "supersedes":
      return direction === "out" ? `${object} ${verb}` : `${josa(otherLabel, "으로/로")} ${verb}됨`;
    case "decided":
      // 서버는 "결정 → 결정이 나온 회의", 예전 데이터는 "사람 → 결정"으로 보냅니다.
      if (sourceType === "decision") {
        return direction === "out" ? "에서 결정됨" : `${object} 결정함`;
      }
      return direction === "out" ? `${object} ${verb}` : `${subject} ${verb}`;
    // 방향에 뜻이 없는 관계
    case "relates_to":
      return `${josa(otherLabel, "과/와")} ${verb}`;
  }
}

/** 스크린리더와 테스트용 한 문장. 예: "홍길동이 참여" */
export function relationSentence(input: RelationSentenceInput): string {
  return `${input.otherLabel}${relationTail(input)}`;
}
