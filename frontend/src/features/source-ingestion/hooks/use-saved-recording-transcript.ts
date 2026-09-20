"use client";

import { useEffect, useRef, useState } from "react";
import { useApi } from "@/lib/api/context";
import { SavedRecordingTranscriber, supportsSavedRecordingTranscript, type RecordingProgress, type RecognitionConstructor } from "../lib/saved-recording-transcriber";

type RecognitionWindow = Window & {
  SpeechRecognition?: RecognitionConstructor;
  webkitSpeechRecognition?: RecognitionConstructor;
};

export function useSavedRecordingTranscript(sourceId?: string) {
  const api = useApi();
  const audioRef = useRef<HTMLAudioElement>(null);
  const session = useRef<SavedRecordingTranscriber | undefined>(undefined);
  const request = useRef<AbortController | undefined>(undefined);
  const generation = useRef(0);
  const [progress, setProgress] = useState<RecordingProgress>();
  const browser = typeof window === "undefined" ? undefined : window as RecognitionWindow;
  const RecognitionClass = browser?.SpeechRecognition ?? browser?.webkitSpeechRecognition;
  const supported = Boolean(browser && supportsSavedRecordingTranscript(
    browser.navigator.userAgent,
    Boolean(RecognitionClass),
    typeof HTMLMediaElement !== "undefined" && typeof (HTMLMediaElement.prototype as HTMLMediaElement & { captureStream?: () => MediaStream }).captureStream === "function",
  ));

  const cancel = () => {
    generation.current++;
    request.current?.abort();
    request.current = undefined;
    session.current?.cancel();
    session.current = undefined;
    setProgress(undefined);
  };

  useEffect(() => () => {
    generation.current++;
    request.current?.abort();
    session.current?.cancel();
  }, [sourceId]);

  const start = async () => {
    if (!sourceId || !supported || !RecognitionClass || !audioRef.current) return;
    cancel();
    const current = generation.current;
    const controller = new AbortController();
    request.current = controller;
    setProgress({ phase: "loading", seconds: 0, duration: 0, utterances: [], interim: "" });
    try {
      const playback = await api.getSourcePlaybackUrl(sourceId, controller.signal);
      if (controller.signal.aborted || generation.current !== current || !audioRef.current) return;
      const transcriber = new SavedRecordingTranscriber(audioRef.current, RecognitionClass, (next) => {
        if (generation.current === current) setProgress(next);
      });
      session.current = transcriber;
      await transcriber.start(playback.url);
    } catch (error) {
      if (!controller.signal.aborted && generation.current === current) setProgress({
        phase: "partial", seconds: 0, duration: 0, utterances: [], interim: "",
        message: error instanceof Error ? error.message : "저장된 녹음을 열지 못했습니다.",
      });
    }
  };

  return { audioRef, supported, progress, start, cancel };
}
