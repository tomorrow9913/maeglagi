/** PoC에서 받는 문서 포맷. 백엔드 파서가 지원하는 범위와 같습니다. */
export const ACCEPTED_DOCUMENT_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"] as const;

/** 해커톤 데모 기준 상한. 서버도 같은 값으로 막습니다. */
export const MAX_DOCUMENT_BYTES = 20 * 1024 * 1024;

export type FileRejection = { file: File; reason: string };

export type ValidationResult = {
  accepted: File[];
  rejected: FileRejection[];
};

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * 확장자와 크기로 업로드 대상을 걸러냅니다.
 *
 * 확장자는 신뢰할 수 없는 값이라 서버가 MIME signature까지 다시 검증합니다.
 * 여기서 막는 이유는 명백히 잘못된 파일을 올리기 전에 알려주기 위해서입니다.
 */
export function validateDocuments(files: File[]): ValidationResult {
  const accepted: File[] = [];
  const rejected: FileRejection[] = [];

  for (const file of files) {
    const extension = extensionOf(file.name);

    if (
      !ACCEPTED_DOCUMENT_EXTENSIONS.includes(
        extension as (typeof ACCEPTED_DOCUMENT_EXTENSIONS)[number],
      )
    ) {
      rejected.push({
        file,
        reason: `지원하지 않는 형식입니다 (${ACCEPTED_DOCUMENT_EXTENSIONS.join(", ")}만 가능)`,
      });
      continue;
    }

    if (file.size === 0) {
      rejected.push({ file, reason: "빈 파일입니다" });
      continue;
    }

    if (file.size > MAX_DOCUMENT_BYTES) {
      rejected.push({ file, reason: `${formatBytes(MAX_DOCUMENT_BYTES)}를 넘습니다` });
      continue;
    }

    accepted.push(file);
  }

  return { accepted, rejected };
}
