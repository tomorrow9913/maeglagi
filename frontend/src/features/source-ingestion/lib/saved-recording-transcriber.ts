import type { MeetingUtterance } from "@/lib/api";

type Result = { isFinal: boolean; 0: { transcript: string } };
type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { results: ArrayLike<Result> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: (track: MediaStreamTrack) => void;
  stop: () => void;
  abort: () => void;
};
export type RecognitionConstructor = new () => Recognition;
export type RecordingProgress = {
  phase: "loading" | "transcribing" | "complete" | "partial";
  seconds: number;
  duration: number;
  utterances: MeetingUtterance[];
  interim: string;
  message?: string;
};

export function supportsSavedRecordingTranscript(
  userAgent: string,
  recognitionAvailable: boolean,
  captureAvailable: boolean,
): boolean {
  const desktop = !/Android|iPhone|iPad|iPod|Mobile/i.test(userAgent);
  const chromium = /\bEdg\/(\d+)/.exec(userAgent)
    ?? (!/\bOPR\//.test(userAgent) ? /\bChrome\/(\d+)/.exec(userAgent) : null);
  return desktop && Boolean(chromium && Number(chromium[1]) >= 135 && recognitionAvailable && captureAvailable);
}

/** The supplied track is required: calling start() without it would open the microphone. */
export class SavedRecordingTranscriber {
  private recognition?: Recognition;
  private stream?: MediaStream;
  private active = true;
  private reachedEnd = false;
  private finalText: string[] = [];
  private interim = "";
  private stopTimer?: ReturnType<typeof setTimeout>;
  private finishLoading?: () => void;

  constructor(
    private audio: HTMLAudioElement,
    private RecognitionClass: RecognitionConstructor,
    private onProgress: (progress: RecordingProgress) => void,
  ) {}

  private utterances(): MeetingUtterance[] {
    return this.finalText.map((text, index) => ({ id: `browser-${index + 1}`, speakerName: "화자 1", text }));
  }

  private emit(phase: RecordingProgress["phase"], message?: string) {
    if (!this.active) return;
    this.onProgress({
      phase,
      seconds: Number.isFinite(this.audio.currentTime) ? this.audio.currentTime : 0,
      duration: Number.isFinite(this.audio.duration) ? this.audio.duration : 0,
      utterances: this.utterances(),
      interim: this.interim,
      message,
    });
  }

  async start(url: string): Promise<void> {
    if (!this.active) return;
    this.audio.crossOrigin = "anonymous";
    this.audio.preload = "auto";
    this.emit("loading");
    try {
      await new Promise<void>((resolve, reject) => {
        const loaded = () => { cleanup(); resolve(); };
        const failed = () => { cleanup(); reject(new Error("저장된 녹음을 재생할 수 없습니다.")); };
        const cleanup = () => { this.finishLoading = undefined; this.audio.removeEventListener("canplay", loaded); this.audio.removeEventListener("error", failed); };
        this.finishLoading = loaded;
        this.audio.addEventListener("canplay", loaded, { once: true });
        this.audio.addEventListener("error", failed, { once: true });
        this.audio.src = url;
        this.audio.load();
        if (this.audio.readyState >= 3) loaded();
      });
      if (!this.active) return;
      this.audio.onerror = () => this.finish("partial", "녹음 재생이 중단됐습니다. 부분 대본은 저장되지 않습니다.");
      const captureStream = (this.audio as HTMLAudioElement & { captureStream?: () => MediaStream }).captureStream;
      if (typeof captureStream !== "function") throw new Error("이 브라우저는 녹음 오디오 캡처를 지원하지 않습니다.");
      this.stream = captureStream.call(this.audio);
      const track = this.stream.getAudioTracks()[0];
      if (!track || track.kind !== "audio" || track.readyState !== "live") throw new Error("녹음 오디오 트랙을 사용할 수 없습니다.");
      const recognition = new this.RecognitionClass();
      this.recognition = recognition;
      recognition.lang = "ko-KR";
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.onresult = (event) => {
        if (!this.active) return;
        const results = Array.from(event.results);
        this.finalText = results.filter((result) => result.isFinal).map((result) => result[0].transcript.trim()).filter(Boolean);
        this.interim = results.filter((result) => !result.isFinal).map((result) => result[0].transcript.trim()).filter(Boolean).join(" ");
        this.emit("transcribing");
      };
      recognition.onerror = (event) => this.finish("partial", `음성 인식이 중단됐습니다 (${event.error}). 저장되지 않은 부분 대본입니다.`);
      recognition.onend = () => {
        if (!this.active) return;
        if (this.reachedEnd && this.finalText.length && !this.interim) this.finish("complete");
        else this.finish("partial", this.reachedEnd ? "완성된 대본이 없습니다. 다시 시도해 주세요." : "녹음이 끝나기 전에 음성 인식이 중단됐습니다. 부분 대본은 저장되지 않습니다.");
      };
      this.audio.ontimeupdate = () => this.emit("transcribing");
      this.audio.onended = () => {
        if (!this.active) return;
        this.reachedEnd = true;
        this.stopTimer = setTimeout(() => this.finish("partial", "음성 인식 완료를 확인하지 못했습니다. 부분 대본은 저장되지 않습니다."), 5000);
        try { recognition.stop(); }
        catch { this.finish("partial", "음성 인식 완료를 확인하지 못했습니다. 부분 대본은 저장되지 않습니다."); return; }
      };
      recognition.start(track);
      await this.audio.play();
      if (this.active) this.emit("transcribing");
    } catch (error) {
      this.finish("partial", error instanceof Error ? error.message : "녹음 받아쓰기를 시작하지 못했습니다.");
    }
  }

  private finish(phase: "complete" | "partial", message?: string) {
    if (!this.active) return;
    this.emit(phase, message);
    this.cancel();
  }

  cancel() {
    if (!this.active) return;
    this.active = false;
    this.finishLoading?.();
    if (this.stopTimer) clearTimeout(this.stopTimer);
    this.audio.ontimeupdate = null;
    this.audio.onended = null;
    this.audio.onerror = null;
    this.audio.pause();
    this.audio.removeAttribute("src");
    this.audio.load();
    if (this.recognition) {
      this.recognition.onresult = null;
      this.recognition.onerror = null;
      this.recognition.onend = null;
      this.recognition.abort();
    }
    this.stream?.getTracks().forEach((track) => track.stop());
  }
}
