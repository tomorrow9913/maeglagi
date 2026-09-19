"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAudioRecorder } from "../hooks/use-audio-recorder";
import { useBrowserTranscript } from "../hooks/use-browser-transcript";
import { mergeTranscript, serializeTranscript, type TranscriptTurn } from "../lib/transcript-draft";
import { RecordingControls } from "./recording-controls";
import type { TranscriptSourceInput } from "@/lib/api";

const speakerColors = [
  "text-blue-700 dark:text-blue-300",
  "text-violet-700 dark:text-violet-300",
  "text-emerald-700 dark:text-emerald-300",
  "text-amber-700 dark:text-amber-300",
  "text-rose-700 dark:text-rose-300",
  "text-cyan-700 dark:text-cyan-300",
];
const speakerColor = (speaker: string | number) =>
  speakerColors[Number(speaker) % speakerColors.length];

export function MeetingCapture({
  onAudio,
  onTranscript,
  onBusyChange,
}: {
  onAudio: (audio: Blob, duration: number) => Promise<void>;
  onTranscript: (input: TranscriptSourceInput) => Promise<boolean>;
  onBusyChange?: (busy: boolean) => void;
}) {
  const editorId = useId();
  const pendingFocus = useRef<number | null>(null);
  const [mode, setMode] = useState<"text" | "audio">("text");
  const [draft, setDraft] = useState<TranscriptTurn[] | null>(null);
  const [duration, setDuration] = useState(0);
  const [title, setTitle] = useState("회의 대본");
  const [speakers, setSpeakers] = useState(["화자 1"]);
  const [currentSpeaker, setCurrentSpeaker] = useState("0");
  const speakerRef = useRef("0");
  const previousSegments = useRef<TranscriptTurn[]>([]);
  const deletedIds = useRef(new Set<number>());
  const manualId = useRef(-1);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const speech = useBrowserTranscript(
    (_lines, seconds) => {
      setDuration((value) => value + seconds);
      // Recognition events already populated the editable draft; do not replace users' corrections.
      setDraft((rows) => rows ?? []);
    },
    (segments) => {
      const speaker = speakerRef.current;
      setDraft((rows) =>
        mergeTranscript(
          rows ?? [],
          [...previousSegments.current, ...segments].filter(
            (segment) => !deletedIds.current.has(segment.id),
          ),
          speaker,
        ),
      );
    },
  );
  const recorder = useAudioRecorder({
    onComplete: (audio, seconds) => {
      void onAudio(audio, seconds);
    },
  });
  const active =
    speech.status !== "idle" || ["requesting", "recording", "stopping"].includes(recorder.status);
  useEffect(() => {
    onBusyChange?.(active || draft !== null || saving);
  }, [active, draft, saving, onBusyChange]);
  useEffect(() => {
    if (!active && draft === null && !saving) return;
    const preventLoss = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", preventLoss);
    return () => window.removeEventListener("beforeunload", preventLoss);
  }, [active, draft, saving]);
  const update = (id: number, values: Partial<TranscriptTurn>) =>
    setDraft((rows) => rows?.map((row) => (row.id === id ? { ...row, ...values } : row)) ?? null);
  const grow = (element: HTMLTextAreaElement) => {
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  };
  const addTurn = () => {
    const row = {
      id: manualId.current--,
      speaker: speakerRef.current,
      text: "",
      isFinal: true,
      edited: true,
    };
    pendingFocus.current = row.id;
    setDraft((rows) => [...(rows ?? []), row]);
  };
  useEffect(() => {
    if (pendingFocus.current === null) return;
    document.getElementById(`${editorId}-${pendingFocus.current}`)?.focus();
    pendingFocus.current = null;
  }, [draft, editorId]);
  const start = () => {
    previousSegments.current = draft ?? [];
    if (speech.start()) setDraft((rows) => rows ?? []);
  };
  const submit = async () => {
    if (active || savingRef.current || !draft?.some((row) => row.text.trim())) return;
    savingRef.current = true;
    setSaving(true);
    try {
      if (
        await onTranscript({
          title: title.trim() || "회의 대본",
          text: serializeTranscript(draft, speakers),
          durationSeconds: duration,
        })
      ) {
        setDraft(null);
        setDuration(0);
        previousSegments.current = [];
        deletedIds.current.clear();
      }
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };
  return (
    <div className="space-y-4">
      <fieldset
        disabled={active || saving || draft !== null}
        className="flex flex-wrap gap-4 text-sm"
      >
        <legend className="mb-2 font-medium">회의 저장 방식</legend>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="meeting-mode"
            checked={mode === "text"}
            onChange={() => setMode("text")}
          />
          브라우저 STT · 텍스트만 업로드
        </label>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="meeting-mode"
            checked={mode === "audio"}
            onChange={() => setMode("audio")}
          />
          오디오 업로드 · 서버 STT
        </label>
      </fieldset>
      {mode === "audio" ? (
        <>
          <RecordingControls
            {...recorder}
            onStart={() => {
              void recorder.start();
            }}
            onStop={recorder.stop}
          />
          <p className="text-xs text-muted-foreground">
            정지하면 오디오 한 개를 업로드하고 서버에서 대본을 생성합니다.
          </p>
        </>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            참여자를 미리 등록하고 현재 화자를 선택하세요. 받아쓰기 중에도 각 발언의 화자와 문장을
            수정할 수 있습니다. 앱에는 확인한 텍스트만 업로드하며, 브라우저 음성 인식 서비스가
            사용될 수 있습니다.
          </p>
          <fieldset disabled={saving} className="space-y-2">
            <legend className="mb-2 text-sm font-medium">참여자</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {speakers.map((name, index) => (
                <Input
                  key={index}
                  className="border-border"
                  aria-label={`화자 ${index + 1} 이름`}
                  value={name}
                  maxLength={80}
                  onChange={(event) =>
                    setSpeakers((values) =>
                      values.map((value, i) => (i === index ? event.target.value : value)),
                    )
                  }
                />
              ))}
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setSpeakers((values) => [...values, `화자 ${values.length + 1}`])}
            >
              화자 추가
            </Button>
          </fieldset>
          <div className="sticky top-0 z-10 space-y-2 rounded-lg border bg-background p-3">
            <p className="text-xs font-medium">현재 화자 · 새 발언에 적용</p>
            <div role="group" aria-label="현재 화자" className="flex flex-wrap gap-2">
              {speakers.map((name, index) => (
                <Button
                  key={index}
                  size="sm"
                  variant="outline"
                  className={`${speakerColor(index)} ${currentSpeaker === String(index) ? "ring-2 ring-current ring-offset-2" : ""}`}
                  disabled={saving}
                  aria-pressed={currentSpeaker === String(index)}
                  onClick={() => {
                    speakerRef.current = String(index);
                    setCurrentSpeaker(String(index));
                  }}
                >
                  {name || `화자 ${index + 1}`}
                </Button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              자동 화자 구분은 지원하지 않습니다. 이미 표시된 발언의 화자는 해당 발언에서 바로 바꿀
              수 있습니다.
            </p>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground" role="status">
                {speech.status === "idle"
                  ? draft
                    ? "받아쓰기 일시 종료 · 편집 가능"
                    : "받아쓰기 준비"
                  : `받아쓰기 ${Math.floor(duration) + speech.elapsed}초`}
              </span>
              {speech.status === "idle" ? (
                <div className="flex gap-2">
                  {!draft && (
                    <Button variant="ghost" disabled={saving} onClick={addTurn}>
                      대본 직접 작성
                    </Button>
                  )}
                  <Button disabled={saving} onClick={start}>
                    {draft ? "이어서 받아쓰기" : "받아쓰기 시작"}
                  </Button>
                </div>
              ) : (
                <Button
                  variant="outline"
                  disabled={speech.status === "stopping"}
                  onClick={speech.stop}
                >
                  받아쓰기 종료
                </Button>
              )}
            </div>
          </div>
          {speech.error && (
            <p role="alert" className="text-sm text-destructive">
              {speech.error}
            </p>
          )}
          {draft && (
            <section aria-label="대본 편집" className="space-y-4">
              <h3 className="font-medium">
                {active ? "실시간 대본 · 바로 편집" : "대본 검토 및 편집"}
              </h3>
              <p className="text-xs text-muted-foreground">
                직접 수정한 문장은 이후 인식 결과가 덮어쓰지 않습니다. 인식 중인 문장은 아직 바뀔 수
                있으므로 확정된 뒤 수정하면 더 편합니다.
              </p>
              <label className="block space-y-1 text-sm">
                제목
                <Input
                  value={title}
                  maxLength={255}
                  disabled={saving}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
              {draft.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  말씀하시면 문장이 여기에 표시됩니다. 화자를 선택한 뒤 발언해 주세요.
                </p>
              )}
              <div className="space-y-1" role="group" aria-label="발언 목록">
                {draft.map((row, index) => (
                  <div
                    key={row.id}
                    className="group grid grid-cols-[5.5rem_minmax(0,1fr)] items-start gap-x-3 py-1.5 sm:grid-cols-[8rem_minmax(0,1fr)]"
                  >
                    <select
                      aria-label={`발언 ${index + 1} 화자`}
                      className={`w-full min-w-0 rounded-sm bg-transparent py-1 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring ${speakerColor(row.speaker)}`}
                      value={row.speaker}
                      disabled={saving}
                      onChange={(event) => update(row.id, { speaker: event.target.value })}
                    >
                      {speakers.map((name, i) => (
                        <option key={i} value={i}>
                          {name || `화자 ${i + 1}`}
                        </option>
                      ))}
                    </select>
                    <div className="min-w-0">
                      <textarea
                        ref={(element) => {
                          if (element) grow(element);
                        }}
                        id={`${editorId}-${row.id}`}
                        rows={1}
                        onKeyDown={(event) => {
                          if (event.key === "Tab" && event.shiftKey && index > 0) {
                            event.preventDefault();
                            document.getElementById(`${editorId}-${draft[index - 1].id}`)?.focus();
                            return;
                          }
                          if (
                            event.key === "Tab" &&
                            !event.shiftKey &&
                            !event.ctrlKey &&
                            !event.altKey &&
                            !event.metaKey &&
                            !event.nativeEvent.isComposing &&
                            index === draft.length - 1 &&
                            row.text.trim() &&
                            !saving
                          ) {
                            event.preventDefault();
                            addTurn();
                          }
                        }}
                        aria-label={`발언 ${index + 1} 내용`}
                        className="block min-h-7 w-full resize-none overflow-hidden bg-transparent py-1 text-sm leading-relaxed text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        value={row.text}
                        disabled={saving}
                        onChange={(event) => {
                          grow(event.target);
                          update(row.id, { text: event.target.value, edited: true });
                        }}
                      />
                      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                        <span>
                          {row.edited
                            ? "수정됨"
                            : row.isFinal
                              ? "인식 확정"
                              : active
                                ? "인식 중…"
                                : "확인 필요"}
                        </span>
                        <button
                          type="button"
                          className="rounded-sm underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                          disabled={saving}
                          onClick={() => {
                            deletedIds.current.add(row.id);
                            setDraft((rows) => rows?.filter((item) => item.id !== row.id) ?? null);
                          }}
                        >
                          발언 삭제
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                마지막 발언에서 Tab: 다음 발언 추가 · Shift+Tab: 이전 항목 이동. 새 발언에는 현재
                선택한 화자가 적용됩니다.
              </p>
              <Button variant="outline" size="sm" disabled={saving} onClick={addTurn}>
                발언 추가 (Tab)
              </Button>
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={active || saving || !draft.some((row) => row.text.trim())}
                  onClick={() => void submit()}
                >
                  {saving ? "업로드 중…" : "검토한 텍스트 업로드"}
                </Button>
                <Button
                  variant="ghost"
                  disabled={active || saving}
                  onClick={() => {
                    if (window.confirm("편집한 대본을 버릴까요?")) {
                      setDraft(null);
                      setDuration(0);
                      previousSegments.current = [];
                      deletedIds.current.clear();
                    }
                  }}
                >
                  대본 버리기
                </Button>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
