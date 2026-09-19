"use client";

import { useEffect, useId, useRef } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { TranscriptTurn } from "../lib/transcript-draft";

export type SpeakerOption = { id: string; name: string };

const speakerColors = [
  "text-[var(--chart-2-hex)]",
  "text-[var(--chart-4-hex)]",
  "text-[var(--chart-1-hex)]",
  "text-[var(--chart-3-hex)]",
  "text-[var(--chart-5-hex)]",
];

function speakerColor(speaker: string) {
  const code = [...speaker].reduce((total, character) => total + character.charCodeAt(0), 0);
  return speakerColors[code % speakerColors.length];
}

function timestamp(seconds?: number | null) {
  if (seconds == null) return "";
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** Shared compact editor for live recognition and server transcript review. */
export function TranscriptEditor({
  rows,
  speakers,
  activeSpeaker,
  disabled = false,
  listening = false,
  onChange,
  onDelete,
  onAdd,
}: {
  rows: TranscriptTurn[];
  speakers: SpeakerOption[];
  activeSpeaker: string;
  disabled?: boolean;
  listening?: boolean;
  onChange: (id: number, values: Partial<TranscriptTurn>) => void;
  onDelete: (id: number) => void;
  onAdd: () => number;
}) {
  const editorId = useId();
  const pendingFocus = useRef<number | null>(null);
  useEffect(() => {
    if (pendingFocus.current === null) return;
    document.getElementById(`${editorId}-${pendingFocus.current}`)?.focus();
    pendingFocus.current = null;
  }, [rows, editorId]);
  const addAndFocus = () => {
    pendingFocus.current = onAdd();
  };
  return (
    <div className="space-y-2">
      {rows.length === 0 && <p className="text-sm text-muted-foreground">발언이 표시되면 화자와 내용을 수정할 수 있습니다.</p>}
      <div role="group" aria-label="발언 목록">
        {rows.map((row, index) => (
          <div key={row.id} className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-start gap-x-3 py-0.5 sm:grid-cols-[8rem_minmax(0,1fr)]">
            <div className="min-w-0">
              <select
                aria-label={`발언 ${index + 1} 화자`}
                className={`w-full min-w-0 rounded-sm bg-transparent py-0.5 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring ${speakerColor(row.speaker)}`}
                value={row.speaker}
                disabled={disabled}
                onChange={(event) => onChange(row.id, { speaker: event.target.value, edited: true })}
              >
                {!speakers.some((speaker) => speaker.id === row.speaker) && <option value={row.speaker}>{row.speaker || "화자 선택"}</option>}
                {speakers.map((speaker) => <option key={speaker.id} value={speaker.id}>{speaker.name}</option>)}
              </select>
              {row.startSeconds != null && <span className="block font-mono text-[10px] text-muted-foreground">{timestamp(row.startSeconds)}{row.endSeconds != null ? `–${timestamp(row.endSeconds)}` : ""}</span>}
            </div>
            <div className="flex min-w-0 items-start gap-1">
              <textarea
                ref={(element) => { if (element) { element.style.height = "auto"; element.style.height = `${element.scrollHeight}px`; } }}
                id={`${editorId}-${row.id}`}
                rows={1}
                onKeyDown={(event) => {
                  if (event.key === "Tab" && event.shiftKey && index > 0) {
                    event.preventDefault();
                    document.getElementById(`${editorId}-${rows[index - 1].id}`)?.focus();
                  } else if (event.key === "Tab" && !event.shiftKey && !event.ctrlKey && !event.altKey && !event.metaKey && !event.nativeEvent.isComposing && index === rows.length - 1 && row.text.trim() && !disabled) {
                    event.preventDefault();
                    addAndFocus();
                  }
                }}
                aria-label={`발언 ${index + 1} 내용`}
                title={row.edited ? "직접 수정됨" : row.isFinal ? "인식 확정" : listening ? "인식 중" : "최종 확인 필요"}
                className="block min-h-6 min-w-0 flex-1 resize-none overflow-hidden bg-transparent py-0.5 text-sm leading-relaxed text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={row.text}
                disabled={disabled}
                onChange={(event) => {
                  event.target.style.height = "auto";
                  event.target.style.height = `${event.target.scrollHeight}px`;
                  onChange(row.id, { text: event.target.value, edited: true });
                }}
              />
              <button type="button" className="flex size-7 shrink-0 items-center justify-center rounded-sm text-muted-foreground opacity-50 hover:bg-accent hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" aria-label={`발언 ${index + 1} 삭제`} title="발언 삭제" disabled={disabled} onClick={() => onDelete(row.id)}><X className="size-3.5" aria-hidden /></button>
            </div>
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">마지막 발언에서 Tab: 다음 발언 추가 · Shift+Tab: 이전 항목 이동. 새 발언에는 현재 선택한 화자가 적용됩니다.</p>
      <Button variant="outline" size="sm" disabled={disabled} onClick={addAndFocus}>발언 추가 (Tab){activeSpeaker && speakers.length ? ` · ${speakers.find((item) => item.id === activeSpeaker)?.name ?? ""}` : ""}</Button>
    </div>
  );
}
