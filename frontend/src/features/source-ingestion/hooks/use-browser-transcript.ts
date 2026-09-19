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

export function useBrowserTranscript(
  onComplete: (lines: string[], duration: number) => void,
  onUpdate?: (segments: TranscriptSegment[]) => void,
) {
  const [status, setStatus] = useState<"idle" | "listening" | "stopping">("idle");
  const [lines, setLines] = useState<string[]>([]);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string>();
  const [elapsed, setElapsed] = useState(0);
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

  const start = () => {
    if (recognitionRef.current) return false;
    const browser = window as RecognitionWindow;
    const Constructor = browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
    if (!Constructor) {
      setError(
        "이 브라우저는 받아쓰기를 지원하지 않습니다. 지원 브라우저를 사용하거나 오디오 업로드를 선택해 주세요.",
      );
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
      const message =
        event.error === "not-allowed" || event.error === "service-not-allowed"
          ? "마이크 또는 음성 인식 권한을 허용해 주세요."
          : event.error === "no-speech"
            ? "음성이 감지되지 않았습니다. 마이크를 확인해 주세요."
            : `받아쓰기가 중단됐습니다 (${event.error}). 수집된 텍스트는 편집할 수 있습니다.`;
      setError(message);
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
  return { status, lines, interim, error, elapsed, start, stop };
}
