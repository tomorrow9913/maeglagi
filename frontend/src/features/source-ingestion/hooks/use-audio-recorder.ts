"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type RecorderStatus =
  "idle" | "requesting" | "recording" | "stopping" | "denied" | "unsupported" | "error";

export type UseAudioRecorderOptions = {
  /** 녹음이 끝나 오디오가 만들어지면 호출됩니다. */
  onComplete: (audio: Blob, durationSeconds: number) => void;
};

/** 브라우저가 지원하는 것 중 앞에 있는 컨테이너를 씁니다. Safari는 mp4만 됩니다. */
const PREFERRED_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];

function pickMimeType(): string | undefined {
  return PREFERRED_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

/**
 * 브라우저 마이크로 회의를 녹음합니다.
 *
 * 권한 거부·미지원 같은 실패를 status로 구분해 화면이 안내 문구를 고를 수
 * 있게 합니다. 화면을 벗어나면 마이크 트랙을 반드시 정리합니다.
 */
export function useAudioRecorder({ onComplete }: UseAudioRecorderOptions) {
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string>();

  const startedAtRef = useRef(0);
  const activeRef = useRef(false);
  const mountedRef = useRef(true);
  const recorderRef = useRef<MediaRecorder>(null);
  const streamRef = useRef<MediaStream>(null);
  const timerRef = useRef<ReturnType<typeof setInterval>>(null);

  // 콜백이 바뀌어도 진행 중인 녹음이 끊기지 않게 참조로만 들고 있습니다.
  const completeRef = useRef(onComplete);
  completeRef.current = onComplete;

  const releaseMic = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  }, []);

  // 녹음 중에 페이지를 벗어나면 마이크가 켜진 채로 남지 않게 합니다.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activeRef.current = false;
      const recorder = recorderRef.current;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      releaseMic();
    };
  }, [releaseMic]);

  const start = useCallback(async () => {
    if (activeRef.current) return;
    if (typeof window === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setStatus("unsupported");
      setErrorMessage("이 브라우저는 녹음을 지원하지 않습니다.");
      return;
    }

    if (typeof MediaRecorder === "undefined" || !pickMimeType()) {
      setStatus("unsupported");
      setErrorMessage("이 브라우저에서 지원하는 녹음 형식이 없습니다.");
      return;
    }

    activeRef.current = true;
    setStatus("requesting");
    setErrorMessage(undefined);

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      activeRef.current = false;
      if (!mountedRef.current) return;
      const name = error instanceof DOMException ? error.name : "";

      if (name === "NotAllowedError" || name === "SecurityError") {
        setStatus("denied");
        setErrorMessage(
          "마이크 권한이 거부됐습니다. 브라우저 주소창의 자물쇠 아이콘에서 마이크를 허용한 뒤 다시 시도해 주세요.",
        );
      } else if (name === "NotFoundError") {
        setStatus("error");
        setErrorMessage("사용할 수 있는 마이크를 찾지 못했습니다.");
      } else {
        setStatus("error");
        setErrorMessage("마이크를 열지 못했습니다.");
      }
      return;
    }

    if (!mountedRef.current) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    streamRef.current = stream;
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType: pickMimeType() });
    } catch {
      releaseMic();
      activeRef.current = false;
      setStatus("error");
      setErrorMessage("녹음을 시작하지 못했습니다.");
      return;
    }
    const chunks: Blob[] = [];

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    });

    recorder.addEventListener("stop", () => {
      if (recorderRef.current !== recorder) return;
      const audio = new Blob(chunks, { type: recorder.mimeType });
      releaseMic();

      const shouldComplete = activeRef.current && mountedRef.current;
      activeRef.current = false;
      recorderRef.current = null;
      if (!shouldComplete) return;
      const seconds = Math.max(0, (Date.now() - startedAtRef.current) / 1000);
      setElapsedSeconds(0);
      setStatus("idle");
      completeRef.current(audio, seconds);
    });

    recorderRef.current = recorder;
    streamRef.current = stream;

    recorder.addEventListener("error", () => {
      if (recorderRef.current !== recorder || !mountedRef.current) return;
      recorderRef.current = null;
      activeRef.current = false;
      if (recorder.state !== "inactive") {
        try { recorder.stop(); } catch { /* the recorder is already unusable */ }
      }
      releaseMic();
      setStatus("error");
      setErrorMessage("녹음 중 오류가 발생했습니다. 다시 시도해 주세요.");
    });
    try {
      recorder.start();
    } catch {
      activeRef.current = false;
      recorderRef.current = null;
      releaseMic();
      setStatus("error");
      setErrorMessage("녹음을 시작하지 못했습니다.");
      return;
    }
    startedAtRef.current = Date.now();
    setElapsedSeconds(0);
    setStatus("recording");
    timerRef.current = setInterval(() => setElapsedSeconds((value) => value + 1), 1000);
  }, [releaseMic]);

  const stop = useCallback(() => {
    if (recorderRef.current?.state !== "recording") return;
    setStatus("stopping");
    recorderRef.current.stop();
  }, []);

  return { status, elapsedSeconds, errorMessage, start, stop };
}
