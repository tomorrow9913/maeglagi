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

  const recorderRef = useRef<MediaRecorder>(null);
  const streamRef = useRef<MediaStream>(null);
  const chunksRef = useRef<Blob[]>([]);
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
  useEffect(() => releaseMic, [releaseMic]);

  const start = useCallback(async () => {
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

    setStatus("requesting");
    setErrorMessage(undefined);

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
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

    const recorder = new MediaRecorder(stream, { mimeType: pickMimeType() });
    chunksRef.current = [];

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    });

    recorder.addEventListener("stop", () => {
      const audio = new Blob(chunksRef.current, { type: recorder.mimeType });
      chunksRef.current = [];
      releaseMic();

      setElapsedSeconds((seconds) => {
        // 정지 시점의 경과 시간을 그대로 넘기고 표시는 0으로 되돌립니다.
        completeRef.current(audio, seconds);
        return 0;
      });
      setStatus("idle");
    });

    recorderRef.current = recorder;
    streamRef.current = stream;

    recorder.start();
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
