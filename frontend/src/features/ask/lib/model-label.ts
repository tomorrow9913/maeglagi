/**
 * 답변 모델 선택지에 붙이는 연결 이름입니다.
 *
 * 연결 id나 서버 주소는 사용자가 붙인 이름이 아니므로 보여주지 않습니다. 같은 이름의
 * 연결이 둘 이상일 때만 key 끝자리로 구분합니다.
 */
export type ConnectionSummary = { id: string; label: string; keyHint?: string | null };

/** 로컬 연결처럼 key가 없는 경우 서버가 끝자리 대신 넣는 값입니다. */
const NO_HINT = new Set(["", "none", "local"]);

export function connectionLabels(connections: ConnectionSummary[]): Map<string, string> {
  const counts = new Map<string, number>();
  for (const connection of connections) {
    counts.set(connection.label, (counts.get(connection.label) ?? 0) + 1);
  }
  const seen = new Map<string, number>();
  return new Map(
    connections.map((connection) => {
      if ((counts.get(connection.label) ?? 0) < 2) return [connection.id, connection.label];
      const order = (seen.get(connection.label) ?? 0) + 1;
      seen.set(connection.label, order);
      const hint = connection.keyHint?.trim() ?? "";
      // key가 없는 연결은 끝자리가 없으므로 등록 순서로 구분합니다.
      const suffix = NO_HINT.has(hint) ? `${order}` : `끝자리 ${hint}`;
      return [connection.id, `${connection.label} (${suffix})`];
    }),
  );
}

export function modelOptionLabel(
  option: { provider: string; model: string; credentialId?: string | null },
  providerName: (id: string) => string,
  labels: Map<string, string>,
): string {
  const connection = option.credentialId ? labels.get(option.credentialId) : undefined;
  return [providerName(option.provider), option.model, connection].filter(Boolean).join(" · ");
}
