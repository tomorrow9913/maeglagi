import { ACCEPTED_DOCUMENT_EXTENSIONS } from "./validate-file";

export const ACCEPTED_AUDIO_EXTENSIONS = [".webm", ".mp4", ".m4a", ".wav", ".mp3", ".ogg", ".flac"] as const;
export const MAX_AUDIO_BYTES = 50 * 1024 * 1024;

const audioMimeByExtension: Record<string, string> = {
  ".webm": "audio/webm",
  ".mp4": "audio/mp4",
  ".m4a": "audio/x-m4a",
  ".wav": "audio/wav",
  ".mp3": "audio/mpeg",
  ".ogg": "audio/ogg",
  ".flac": "audio/flac",
};

export type SourceFile =
  | { kind: "document"; file: File }
  | { kind: "audio"; file: File }
  | { kind: "unsupported"; reason: string };

export function classifySourceFile(file: File): SourceFile {
  const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (ACCEPTED_DOCUMENT_EXTENSIONS.some((item) => item === extension)) return { kind: "document", file };
  if (file.type.toLowerCase().startsWith("video/")) return { kind: "unsupported", reason: "동영상은 지원하지 않습니다. 오디오 파일을 선택해 주세요." };
  const expectedMime = audioMimeByExtension[extension];
  if (!expectedMime) return { kind: "unsupported", reason: "지원하지 않는 형식입니다. 문서 또는 WebM, MP4, M4A, WAV, MP3, OGG, FLAC 오디오를 선택해 주세요." };
  if (file.size === 0) return { kind: "unsupported", reason: "빈 파일입니다." };
  if (file.size > MAX_AUDIO_BYTES) return { kind: "unsupported", reason: "오디오는 50 MB를 넘을 수 없습니다." };

  const mime = file.type.split(";", 1)[0].trim().toLowerCase();
  const allowed = extension === ".m4a" ? ["audio/x-m4a", "audio/m4a", "audio/mp4"]
    : extension === ".wav" ? ["audio/wav", "audio/x-wav"]
    : extension === ".mp3" ? ["audio/mpeg", "audio/mp3"]
    : extension === ".flac" ? ["audio/flac", "audio/x-flac"]
    : extension === ".webm" ? ["audio/webm", "audio/mp4"]
    : [expectedMime];
  if (mime && mime !== "application/octet-stream" && !allowed.includes(mime)) {
    return { kind: "unsupported", reason: "오디오 형식과 파일 확장자가 일치하지 않습니다." };
  }
  // Browser pickers sometimes omit MIME. The recording endpoint validates the bytes again.
  const audio = mime && mime !== "application/octet-stream" ? file : new File([file], file.name, { type: expectedMime, lastModified: file.lastModified });
  return { kind: "audio", file: audio };
}
