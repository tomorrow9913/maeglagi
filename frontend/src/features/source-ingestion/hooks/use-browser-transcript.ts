"use client";

import { useEffect, useRef, useState } from "react";
import type { TranscriptSegment } from "../lib/transcript-draft";

type RecognitionResult = { isFinal: boolean; 0: { transcript: string } };
type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { results: ArrayLike<RecognitionResult> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
};
type RecognitionWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};

/** Web Speech API 오류 코드를 사용자가 읽을 사유로 바꿉니다. 코드 원문은 화면에 내보내지 않습니다. */
export function speechErrorMessage(code: string): string {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "마이크 또는 받아쓰기 권한이 없습니다. 브라우저에서 마이크를 허용한 뒤 다시 시도해 주세요.";
    case "audio-capture":
      return "마이크를 찾지 못했습니다. 마이크 연결을 확인해 주세요.";
    case "no-speech":
      return "음성이 감지되지 않았습니다. 마이크를 확인해 주세요.";
    case "network":
      return "네트워크 연결이 끊겨 받아쓰기가 중단됐습니다. 받아쓴 내용은 편집할 수 있습니다.";
    case "language-not-supported":
      return "이 브라우저는 한국어 받아쓰기를 지원하지 않습니다. 직접 작성해 주세요.";
    default:
      return "받아쓰기가 중단됐습니다. 받아쓴 내용은 편집할 수 있습니다.";
  }
}

export function useBrowserTranscript(
  onComplete: (lines: string[], duration: number) => void,
  onUpdate?: (segments: TranscriptSegment[]) => void,
) {
  const [status, setStatus] = useState<"idle" | "listening" | "stopping">("idle");
  const [lines, setLines] = useState<string[]>([]);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string>();
  const [elapsed, setElapsed] = useState(0);
  // 서버 렌더 결과와 어긋나지 않도록 마운트한 뒤에 확인합니다.
  const [supported, setSupported] = useState(true);
  const recognitionRef = useRef<Recognition | null>(null);
  const completeRef = useRef(onComplete);
  completeRef.current = onComplete;
  const updateRef = useRef(onUpdate);
  updateRef.current = onUpdate;
  const nextIdRef = useRef(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      const recognition = recognitionRef.current;
      if (recognition) {
        recognition.onend = null;
        recognition.onresult = null;
        recognition.onerror = null;
        recognition.abort();
      }
      if (timer.current) clearInterval(timer.current);
      if (stopTimer.current) clearTimeout(stopTimer.current);
    },
    [],
  );

  useEffect(() => {
    const browser = window as RecognitionWindow;
    setSupported(Boolean(browser.SpeechRecognition ?? browser.webkitSpeechRecognition));
  }, []);

  const start = () => {
    if (recognitionRef.current) return false;
    const browser = window as RecognitionWindow;
    const Constructor = browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
    if (!Constructor) {
      setSupported(false);
      setError("이 브라우저는 받아쓰기를 지원하지 않습니다. 직접 작성하거나 녹음 파일을 올려 주세요.");
      return false;
    }
    const recognition = new Constructor();
    recognition.lang = "ko-KR";
    recognition.continuous = true;
    recognition.interimResults = true;
    const resultIds: number[] = [];
    const resultStarts: number[] = [];
    let finalLines: string[] = [];
    let pending = "";
    const startedAt = Date.now();
    setError(undefined);
    setLines([]);
    setInterim("");
    setElapsed(0);
    recognition.onresult = (event) => {
      // The API returns the whole session; replace the interim tail instead of appending duplicates.
      finalLines = [];
      const partial: string[] = [];
      for (const result of Array.from(event.results)) {
        const text = result[0].transcript.trim();
        if (text) (result.isFinal ? finalLines : partial).push(text);
      }
      pending = partial.join(" ");
      setLines([...finalLines]);
      setInterim(pending);
      const segments = Array.from(event.results)
        .map((result, index) => {
          if (resultIds[index] === undefined) resultIds[index] = nextIdRef.current++;
          if (resultStarts[index] === undefined) resultStarts[index] = Math.max(0, (Date.now() - startedAt) / 1000);
          return {
            id: resultIds[index],
            text: result[0].transcript.trim(),
            isFinal: result.isFinal,
            startSeconds: resultStarts[index],
            endSeconds: result.isFinal ? Math.max(resultStarts[index], (Date.now() - startedAt) / 1000) : null,
          };
        })
        .filter((segment) => segment.text);
      updateRef.current?.(segments);
    };
    recognition.onerror = (event) => {
      // 종료 버튼 뒤에 직접 abort한 경우의 "aborted"는 오류가 아닙니다.
      if (event.error === "aborted" && stopTimer.current) return;
      setError(speechErrorMessage(event.error));
    };
    recognition.onend = () => {
      if (recognitionRef.current !== recognition) return;
      recognitionRef.current = null;
      if (stopTimer.current) clearTimeout(stopTimer.current);
      stopTimer.current = null;
      if (timer.current) clearInterval(timer.current);
      timer.current = null;
      setStatus("idle");
      const captured = pending ? [...finalLines, pending] : finalLines;
      // Keep even the last tentative phrase for the user's review; never upload automatically.
      completeRef.current(captured, (Date.now() - startedAt) / 1000);
    };
    recognitionRef.current = recognition;
    try {
      recognition.start();
      setStatus("listening");
      timer.current = setInterval(
        () => setElapsed(Math.floor((Date.now() - startedAt) / 1000)),
        1000,
      );
      return true;
    } catch {
      recognitionRef.current = null;
      setError("받아쓰기를 시작하지 못했습니다. 다시 시도해 주세요.");
      return false;
    }
  };

  const stop = () => {
    if (recognitionRef.current && !stopTimer.current) {
      setStatus("stopping");
      const recognition = recognitionRef.current;
      try { recognition.stop(); } catch { recognition.abort(); recognition.onend?.(); return; }
      stopTimer.current = setTimeout(() => {
        if (recognitionRef.current !== recognition) return;
        recognition.abort();
        recognition.onend?.();
      }, 3000);
    }
  };
  return { status, lines, interim, error, elapsed, supported, start, stop };
}
