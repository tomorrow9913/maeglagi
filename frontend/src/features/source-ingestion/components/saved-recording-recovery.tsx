"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import type { MeetingReview } from "@/lib/api";
import { useApi } from "@/lib/api/context";
import { useSavedRecordingTranscript } from "../hooks/use-saved-recording-transcript";
import { toUserMessage } from "@/lib/api/error-message";

export function SavedRecordingRecovery({ workspaceId, sourceId, review, onSaved }: {
  workspaceId: string;
  sourceId: string;
  review: MeetingReview;
  onSaved: (review: MeetingReview) => void;
}) {
  const api = useApi();
  const { audioRef, supported, progress, start, cancel } = useSavedRecordingTranscript(sourceId);
  const [saving, setSaving] = useState(false);
  const saveRequest = useRef<AbortController | undefined>(undefined);
  useEffect(() => () => saveRequest.current?.abort(), [sourceId]);
  const active = progress?.phase === "loading" || progress?.phase === "transcribing";
  const save = async () => {
    if (saving || progress?.phase !== "complete" || !progress.utterances.some((item) => item.text.trim())) return;
    if (review.utterances.length && !window.confirm("기존 대본 초안을 브라우저 받아쓰기 결과로 바꿀까요? 기존 초안은 되돌릴 수 없습니다.")) return;
    const controller = new AbortController();
    saveRequest.current = controller;
    setSaving(true);
    try {
      const next = await api.submitBrowserTranscript(workspaceId, sourceId, { revision: review.revision, utterances: progress.utterances }, controller.signal);
      if (controller.signal.aborted) return;
      onSaved(next);
      window.dispatchEvent(new Event("maeglagi:sources-changed"));
      toast.success("받아쓰기 결과를 대본 초안으로 저장했습니다. 검토한 뒤 확인해 주세요.");
    } catch (error) {
      if (!controller.signal.aborted) toast.error(toUserMessage(error, "받아쓰기 결과를 저장하지 못했습니다."));
    } finally {
      if (!controller.signal.aborted) setSaving(false);
    }
  };

  return <div className="space-y-2 rounded-md border p-3 text-sm">
    <p className="font-medium">저장된 녹음으로 브라우저 받아쓰기</p>
    <p className="text-xs text-muted-foreground">시작하면 녹음이 재생되고 브라우저의 받아쓰기 서비스로 전송될 수 있습니다. 마이크는 사용하지 않습니다. 끝까지 받아쓴 대본만 저장할 수 있고, 저장하면 기존 대본 초안이 바뀝니다. 저장한 뒤 검토와 확인이 필요합니다.</p>
    {!supported && <p role="status" className="text-xs text-muted-foreground">이 기능은 데스크톱 Chrome 또는 Edge 135 이상에서만 사용할 수 있습니다. 다른 브라우저에서는 위의 “저장된 녹음으로 다시 시도”를 사용해 주세요.</p>}
    <audio ref={audioRef} className="hidden" aria-hidden="true" />
    <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" variant="outline" disabled={!supported || active || saving} onClick={() => void start()}>{progress ? "처음부터 다시 받아쓰기" : "녹음 재생하며 받아쓰기"}</Button>
      {active && <Button size="sm" variant="ghost" onClick={cancel}>취소</Button>}
      {progress?.phase === "complete" && <Button size="sm" pending={saving} pendingLabel="저장하는 중…" disabled={!progress.utterances.some((item) => item.text.trim())} onClick={() => void save()}>대본 초안으로 저장</Button>}
    </div>
    {progress && <div role="status" className="space-y-1 text-xs text-muted-foreground">
      <p>{progress.phase === "loading" ? "녹음 여는 중…" : progress.phase === "transcribing" ? "녹음을 재생하며 받아쓰는 중…" : progress.phase === "complete" ? "녹음을 끝까지 받아썼습니다. 결과를 확인하고 저장해 주세요." : "받아쓰기를 끝내지 못했습니다. 부분 대본은 저장할 수 없습니다."} {Math.floor(progress.seconds)}초{progress.duration > 0 ? ` / ${Math.floor(progress.duration)}초` : ""}</p>
      {progress.duration > 0 && <progress aria-label="저장된 녹음 받아쓰기 진행률" max={progress.duration} value={progress.seconds} className="w-full" />}
      {progress.message && <p role="alert">{progress.message}</p>}
      {(progress.utterances.length > 0 || progress.interim) && <p className="max-h-32 overflow-y-auto whitespace-pre-wrap text-foreground">{progress.utterances.map((item) => item.text).join(" ")}{progress.interim ? ` ${progress.interim}` : ""}</p>}
    </div>}
  </div>;
}
