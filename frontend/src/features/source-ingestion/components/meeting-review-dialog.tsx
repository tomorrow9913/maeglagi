"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ErrorState, ListSkeleton } from "@/components/common/state-views";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError, type MeetingReview, type MeetingUtterance, type ProcessingJob, type WorkspacePerson, type WorkspaceProject } from "@/lib/api";
import { useApi } from "@/lib/api/context";
import { reviewUtterances, unresolvedReviewPeople, type TranscriptTurn } from "../lib/transcript-draft";
import { reviewConfirmationCopy, reviewDisplayState } from "../lib/source-presentation";
import { TranscriptEditor, type SpeakerOption } from "./transcript-editor";
import { SavedRecordingRecovery } from "./saved-recording-recovery";
import { toUserMessage } from "@/lib/api/error-message";

const isReadOnlyReview = (review: MeetingReview) => reviewDisplayState(review).readOnly;

/** 한 번에 하나만 진행됩니다. 어떤 버튼이 눌렸는지 구분해 그 버튼에만 진행 표시를 붙입니다. */
type PendingAction = "save" | "confirm" | "retryAnalysis" | "retryTranscription";

export function MeetingReviewDialog({ workspaceId, sourceId, onClose, onConfirmed, onRetried }: {
  workspaceId: string;
  sourceId?: string;
  onClose: () => void;
  onConfirmed?: (job: ProcessingJob) => void;
  onRetried?: (job: ProcessingJob) => void;
}) {
  const api = useApi();
  const [review, setReview] = useState<MeetingReview>();
  const [people, setPeople] = useState<WorkspacePerson[]>([]);
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [rows, setRows] = useState<TranscriptTurn[]>([]);
  const [projectId, setProjectId] = useState("");
  const [projectIds, setProjectIds] = useState<string[]>([]);
  const [speakers, setSpeakers] = useState<SpeakerOption[]>([{ id: "local-1", name: "화자 1" }]);
  const [activeSpeaker, setActiveSpeaker] = useState("local-1");
  const [pendingAction, setPendingAction] = useState<PendingAction>();
  const busy = pendingAction !== undefined;
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<Error>();
  const [refreshing, setRefreshing] = useState(false);
  /** 받아쓰기를 기다리며 조용히 상태를 확인하다 실패한 경우. 화면을 갈아엎지 않고 한 줄로만 알립니다. */
  const [statusCheckFailed, setStatusCheckFailed] = useState(false);
  const [job, setJob] = useState<ProcessingJob>();
  const idMap = useRef(new Map<number, string>());
  const nextId = useRef(-1);
  const openId = useRef(sourceId);
  openId.current = sourceId;
  const load = useCallback(async (id: string, silent = false) => {
    if (!silent) { setLoading(true); setLoadError(undefined); }
    try {
      const [data, roster, projectList] = await Promise.all([api.getMeetingReview(workspaceId, id), api.listPeople(workspaceId), api.listProjects(workspaceId)]);
      if (openId.current !== id) return;
      const currentJob = isReadOnlyReview(data) ? await api.getJob(id).catch(() => undefined) : undefined;
      if (openId.current !== id) return;
      setJob(currentJob);
      setReview(data); setPeople(roster); setProjects(projectList);
      const suggested = new Set(data.suggestedParticipants?.map((item) => item.id) ?? []);
      const options: SpeakerOption[] = [...roster].sort((left, right) => Number(suggested.has(right.id)) - Number(suggested.has(left.id))).map((item) => ({ id: item.id, name: `${item.name}${item.archivedAt ? " (보관됨)" : suggested.has(item.id) ? " · 프로젝트 참여자" : ""}` }));
      data.utterances.forEach((item) => {
        if (item.personId && !roster.some((person) => person.id === item.personId) && !options.some((speaker) => speaker.id === item.personId)) options.push({ id: item.personId, name: `${item.speakerName} (목록에 없음)` });
      });
      const assigned = new Map<string, string>();
      data.utterances.forEach((item) => { if (!item.personId && item.speakerName && !assigned.has(item.speakerName)) assigned.set(item.speakerName, `local-${assigned.size + 1}`); });
      assigned.forEach((id, name) => options.push({ id, name }));
      if (!options.length) options.push({ id: "local-1", name: "화자 1" });
      setSpeakers(options); setActiveSpeaker(options[0].id);
      idMap.current.clear();
      setRows(data.utterances.map((item, index) => { idMap.current.set(index + 1, item.id); return { id: index + 1, speaker: item.personId || assigned.get(item.speakerName) || options[0].id, personId: item.personId, text: item.text, isFinal: true, startSeconds: item.startSeconds, endSeconds: item.endSeconds }; }));
      const selectedProjects = data.projectIds ?? (data.projectId ? [data.projectId] : []);
      setProjectIds(selectedProjects); setProjectId(selectedProjects[0] ?? ""); setDirty(false); setConflict(false);
      setLoadError(undefined); setStatusCheckFailed(false);
    } catch (error) {
      if (openId.current !== id) return;
      // 조용한 확인이 실패해도 이미 보여준 대본과 안내를 오류 상자로 바꾸지 않습니다.
      if (silent) setStatusCheckFailed(true);
      else setLoadError(error instanceof Error ? error : new Error(String(error)));
    }
    finally { if (openId.current === id && !silent) setLoading(false); }
  }, [api, workspaceId]);
  useEffect(() => {
    setStatusCheckFailed(false); setRefreshing(false);
    if (sourceId) void load(sourceId);
    else { setReview(undefined); setRows([]); setJob(undefined); setLoadError(undefined); }
  }, [sourceId, load]);
  useEffect(() => {
    if (!sourceId || review?.reviewState !== "transcribing" || review.status === "failed") return;
    const timer = window.setInterval(() => void load(sourceId, true), 3000);
    return () => window.clearInterval(timer);
  }, [sourceId, review?.reviewState, review?.status, load]);
  const refreshStatus = async () => {
    if (!sourceId || refreshing) return;
    const id = sourceId;
    setRefreshing(true);
    try { await load(id, true); }
    finally { if (openId.current === id) setRefreshing(false); }
  };
  const invalidPersonRows = unresolvedReviewPeople(rows, people);
  const utterances = (): MeetingUtterance[] => reviewUtterances(rows, people, speakers, idMap.current);
  const retryTranscription = async () => {
    if (!sourceId || busy || review?.analysisMode === "agent" || review?.reviewState !== "transcribing" || review.status !== "failed") return;
    setPendingAction("retryTranscription");
    try {
      const job = await api.retryMeetingTranscription(workspaceId, sourceId);
      await load(sourceId);
      onRetried?.(job);
      window.dispatchEvent(new Event("maeglagi:sources-changed"));
      toast.success("저장된 녹음으로 받아쓰기를 다시 시작했습니다.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) await load(sourceId);
      toast.error(toUserMessage(error, "받아쓰기를 다시 시작하지 못했습니다."));
    } finally { setPendingAction(undefined); }
  };
  const save = async () => {
    if (!sourceId || !review || busy || invalidPersonRows.length) return;
    setPendingAction("save");
    try {
      const next = await api.saveMeetingReview(workspaceId, sourceId, { revision: review.revision, projectId: projectId || null, projectIds, utterances: utterances() });
      setReview(next); setDirty(false); setConflict(false); toast.success("대본 초안을 저장했습니다.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) { setConflict(true); toast.error("다른 곳에서 대본이 수정돼 저장하지 못했습니다. 편집한 내용은 이 화면에 남아 있습니다."); }
      else toast.error(toUserMessage(error, "대본을 저장하지 못했습니다."));
    } finally { setPendingAction(undefined); }
  };
  const confirm = async (retry = false) => {
    if (!sourceId || !review || busy || (!retry && (dirty || invalidPersonRows.length || !rows.some((row) => row.text.trim())))) return;
    setPendingAction(retry ? "retryAnalysis" : "confirm");
    try { const job = await api.confirmMeetingReview(workspaceId, sourceId, review.revision); onConfirmed?.(job); toast.success(reviewConfirmationCopy(job.status === "awaiting_agent" ? "agent" : job.analysisMode ?? review.analysisMode).success); onClose(); }
    catch (error) {
      if (error instanceof ApiError && error.status === 409) setConflict(true);
      if (review.analysisMode !== "agent" && error instanceof ApiError && error.status === 503) {
        toast.error("대본은 확인됐지만 분석을 시작하지 못했습니다. 다시 시도할 수 있습니다.");
        await load(sourceId);
        window.dispatchEvent(new Event("maeglagi:sources-changed"));
      } else toast.error(toUserMessage(error, "대본을 확인하지 못했습니다."));
    }
    finally { setPendingAction(undefined); }
  };
  /** 충돌이 났을 때 내 편집본을 잃지 않도록 "화자: 발언" 형태의 텍스트로 복사합니다. */
  const copyMyEdits = async () => {
    const text = utterances().filter((item) => item.text.trim()).map((item) => `${item.speakerName}: ${item.text.trim()}`).join("\n\n");
    if (!text) { toast.info("복사할 발언이 없습니다."); return; }
    try {
      await navigator.clipboard.writeText(text);
      toast.success("내 편집본을 복사했습니다.");
    } catch {
      toast.error("복사하지 못했습니다. 발언을 직접 선택해 복사해 주세요.");
    }
  };
  const reloadAfterConflict = () => {
    if (!sourceId || busy) return;
    if (dirty && !window.confirm("최신 대본을 불러오면 지금 편집한 내용이 사라집니다. 불러올까요?")) return;
    void load(sourceId);
  };
  const replaceFromRaw = () => {
    if (!review?.rawUtterances.length || !window.confirm("현재 편집 중인 대본을 원문으로 바꿀까요?")) return;
    const options = speakers.filter((speaker) => !speaker.id.startsWith("raw-")); const named = new Map<string, string>();
    for (const item of review.rawUtterances) if (!item.personId && !named.has(item.speakerName)) { const id = `raw-${named.size}`; named.set(item.speakerName, id); options.push({ id, name: item.speakerName }); }
    setSpeakers(options);
    idMap.current.clear();
    setRows(review.rawUtterances.map((item, index) => { idMap.current.set(index + 1, item.id); return { id: index + 1, speaker: item.personId || named.get(item.speakerName) || options[0].id, text: item.text, isFinal: true, startSeconds: item.startSeconds, endSeconds: item.endSeconds }; }));
    setDirty(true);
  };
  const display = review ? reviewDisplayState({ ...review, status: job?.status ?? review.status }) : undefined;
  const readOnly = review ? isReadOnlyReview(review) : false;
  const hasText = rows.some((row) => row.text.trim());
  const hasArchivedProject = projectIds.some((id) => Boolean(projects.find((item) => item.id === id)?.archivedAt));
  // "확인" 버튼이 왜 눌리지 않는지 한 줄로 알려줍니다. 위에 있는 것이 먼저 풀어야 할 이유입니다.
  const confirmBlockedReason = conflict ? "최신 대본을 불러온 뒤 확인할 수 있습니다."
    : invalidPersonRows.length > 0 ? "참여자를 다시 선택한 뒤 확인할 수 있습니다."
    : dirty ? "확인 전에 변경 내용을 저장해 주세요."
    : !hasText ? "대본에 내용이 없습니다. 발언을 추가해 주세요."
    : hasArchivedProject ? "보관된 프로젝트가 선택돼 있습니다. 선택을 해제한 뒤 저장해 주세요."
    : undefined;
  const statusLabel = !review ? ""
    : review.status === "awaiting_agent" ? "에이전트 작업 대기"
    : review.reviewState === "transcribing" ? (review.status === "failed" ? "받아쓰기 실패" : "자동 받아쓰기 중")
    : readOnly ? "확인됨" : "검토 필요";
  const statusCheckNote = statusCheckFailed && (
    <p role="status" className="text-xs text-muted-foreground">상태를 새로 확인하지 못했습니다. 연결을 확인한 뒤 새로고침해 주세요.</p>
  );

  return (
    <Dialog open={Boolean(sourceId)} onOpenChange={(open) => { if (!open && !busy && (!dirty || window.confirm("저장하지 않은 변경을 버릴까요?"))) onClose(); }}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>회의 대본 검토</DialogTitle>
          <DialogDescription>
            {display?.readOnly
              ? display.waitingForAgent ? "확인된 대본입니다. 연결한 에이전트가 분석 결과를 저장할 때까지 기다립니다." : "확인된 대본과 프로젝트 정보는 유지됩니다."
              : reviewConfirmationCopy(review?.analysisMode).description}
          </DialogDescription>
        </DialogHeader>
        {loading ? (
          <ListSkeleton count={4} className="h-9" label="대본을 불러오는 중" />
        ) : loadError ? (
          <ErrorState compact error={loadError} title="대본을 불러오지 못했습니다" onRetry={() => sourceId && void load(sourceId)} />
        ) : !review ? (
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <span>대본을 불러오지 못했습니다.</span>
            <Button size="sm" variant="outline" onClick={() => sourceId && void load(sourceId)}>다시 시도</Button>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-sm font-medium">{review.title} · {statusLabel}</p>
            {review.reviewState === "transcribing" ? (
              review.status === "failed" ? (
                <>
                  <div role="alert" className="space-y-2 rounded-md border border-destructive p-3 text-sm">
                    <p>자동 받아쓰기를 끝내지 못했습니다. 올린 녹음{review.utterances.length ? "과 실시간 대본 초안은" : "은"} 저장돼 있습니다.</p>
                    {review.errorMessage && <p className="text-muted-foreground">{review.errorMessage}</p>}
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" pending={pendingAction === "retryTranscription"} pendingLabel="다시 시작하는 중…" disabled={busy || review.analysisMode === "agent"} onClick={() => void retryTranscription()}>저장된 녹음으로 다시 시도</Button>
                      <Button size="sm" variant="outline" pending={refreshing} pendingLabel="확인하는 중…" disabled={busy} onClick={() => void refreshStatus()}>새로고침</Button>
                    </div>
                  </div>
                  {statusCheckNote}
                  {sourceId && review.analysisMode !== "agent" && <SavedRecordingRecovery key={sourceId} workspaceId={workspaceId} sourceId={sourceId} review={review} onSaved={(next) => { setReview(next); void load(sourceId); }} />}
                </>
              ) : (
                <div className="space-y-2">
                  <p className="text-sm text-muted-foreground">받아쓰기가 끝나면 대본이 여기에 나타납니다. 소스 목록에서도 다시 열 수 있습니다.</p>
                  <Button size="sm" variant="outline" pending={refreshing} pendingLabel="확인하는 중…" onClick={() => void refreshStatus()}>새로고침</Button>
                  {statusCheckNote}
                </div>
              )
            ) : (
              <>
                {conflict && (
                  <div role="alert" className="space-y-2 rounded-md border border-destructive p-3 text-sm">
                    <p>다른 곳에서 대본이 먼저 수정됐습니다. 최신 대본을 불러와야 저장하거나 확인할 수 있습니다. 불러오면 이 화면의 대본은 최신 내용으로 바뀌니, 필요하면 먼저 복사해 주세요.</p>
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" variant="outline" onClick={() => void copyMyEdits()}>내 편집본 복사</Button>
                      <Button size="sm" variant="outline" disabled={busy} onClick={reloadAfterConflict}>최신 대본 불러오기</Button>
                    </div>
                  </div>
                )}
                <fieldset className="space-y-1 text-sm">
                  <legend className="font-medium">회의 프로젝트</legend>
                  {projects.length === 0 ? (
                    <p className="text-xs text-muted-foreground">아직 프로젝트가 없습니다. 참여자·프로젝트에서 만들어 보세요.</p>
                  ) : (
                    <div className="flex flex-wrap gap-3">
                      {projects.filter((item) => !item.archivedAt || projectIds.includes(item.id)).map((item) => (
                        <label key={item.id} className="flex items-center gap-1">
                          <input
                            type="checkbox"
                            checked={projectIds.includes(item.id)}
                            disabled={busy || readOnly || (Boolean(item.archivedAt) && !projectIds.includes(item.id))}
                            onChange={(event) => { const next = event.target.checked ? [...projectIds, item.id] : projectIds.filter((id) => id !== item.id); setProjectIds(next); setProjectId(next[0] ?? ""); setDirty(true); }}
                          />
                          {item.name}{item.archivedAt ? " (보관됨)" : ""}
                        </label>
                      ))}
                    </div>
                  )}
                  <p className="text-xs text-muted-foreground">프로젝트를 선택하지 않아도 대본은 확인할 수 있습니다.</p>
                </fieldset>
                {(review.suggestedParticipants?.length ?? 0) > 0 && <p className="text-xs text-muted-foreground">선택한 프로젝트의 등록 참여자: {review.suggestedParticipants!.map((person) => person.name).join(", ")}. 실제 회의 발언자는 대본에서 직접 지정해 주세요.</p>}
                <div className="space-y-2">
                  <p className="text-sm font-medium">새 발언 화자</p>
                  <div className="flex flex-wrap gap-1.5">
                    {speakers.map((speaker) => <Button key={speaker.id} size="sm" variant="outline" disabled={readOnly} aria-pressed={activeSpeaker === speaker.id} className={activeSpeaker === speaker.id ? "ring-2 ring-current" : ""} onClick={() => setActiveSpeaker(speaker.id)}>{speaker.name}</Button>)}
                  </div>
                  <Button size="sm" variant="ghost" disabled={readOnly} onClick={() => { const name = window.prompt("새 화자 이름"); if (name?.trim()) { const id = `local-${Date.now()}`; setSpeakers((values) => [...values, { id, name: name.trim() }]); setActiveSpeaker(id); } }}>미등록 화자 추가</Button>
                </div>
                {speakers.filter((item) => item.id.startsWith("local-")).map((speaker) => <Input key={speaker.id} aria-label={`${speaker.name} 이름`} value={speaker.name} disabled={busy || readOnly} onChange={(event) => { setSpeakers((values) => values.map((item) => item.id === speaker.id ? { ...item, name: event.target.value } : item)); setDirty(true); }} />)}
                <TranscriptEditor rows={rows} speakers={speakers} activeSpeaker={activeSpeaker} disabled={busy || readOnly} onChange={(id, values) => { setRows((items) => items.map((item) => item.id === id ? { ...item, ...values } : item)); setDirty(true); }} onDelete={(id) => { setRows((items) => items.filter((item) => item.id !== id)); setDirty(true); }} onAdd={() => { const id = nextId.current--; setRows((items) => [...items, { id, speaker: activeSpeaker, text: "", isFinal: true, edited: true }]); setDirty(true); return id; }} />
                {invalidPersonRows.length > 0 && review.reviewState === "awaiting_review" && <p role="alert" className="text-sm text-destructive">보관됐거나 목록에 없는 참여자가 {invalidPersonRows.length}개 발언에 연결돼 있습니다. 해당 발언에서 활성 참여자 또는 미등록 화자를 다시 선택해 주세요.</p>}
                {review.rawTranscriptText && (
                  <details className="rounded-lg border p-3 text-xs">
                    <summary className="cursor-pointer font-medium">{review.transcriptSource === "server" ? "자동 받아쓰기 결과 보기" : review.transcriptSource === "agent" ? "에이전트가 올린 대본 원문 보기" : "올린 원문 보기"}</summary>
                    <pre className="mt-2 whitespace-pre-wrap font-sans">{review.rawTranscriptText}</pre>
                    {review.reviewState === "awaiting_review" && review.rawUtterances.length > 0 && <Button size="sm" variant="outline" className="mt-2" onClick={replaceFromRaw}>원문으로 편집 초안 바꾸기</Button>}
                  </details>
                )}
                {review.reviewState === "awaiting_review" && (
                  <div className="space-y-1.5">
                    <div className="flex flex-wrap gap-2">
                      <Button variant="outline" pending={pendingAction === "save"} pendingLabel="저장하는 중…" disabled={busy || !dirty || conflict || invalidPersonRows.length > 0} onClick={() => void save()}>초안 저장</Button>
                      <Button pending={pendingAction === "confirm"} pendingLabel="확인하는 중…" disabled={busy || Boolean(confirmBlockedReason)} aria-describedby={confirmBlockedReason ? "review-confirm-blocked" : undefined} onClick={() => void confirm()}>{reviewConfirmationCopy(review.analysisMode).button}</Button>
                    </div>
                    {confirmBlockedReason && <p id="review-confirm-blocked" className="text-xs text-muted-foreground">{confirmBlockedReason}</p>}
                  </div>
                )}
                {display?.showServerRetry && (
                  <div role="alert" className="flex flex-wrap items-center gap-2 rounded-md border border-destructive p-3 text-sm">
                    <span>대본은 확인됐지만 분석을 시작하지 못했습니다. 저장된 대본과 프로젝트 정보는 유지됩니다.</span>
                    <Button size="sm" pending={pendingAction === "retryAnalysis"} pendingLabel="다시 시작하는 중…" disabled={busy} onClick={() => void confirm(true)}>분석 다시 시도</Button>
                  </div>
                )}
                {display?.showAgentFailure && <p role="alert" className="rounded-md border border-destructive p-3 text-sm">에이전트 분석에 실패했습니다. 저장된 대본은 유지됩니다. 연결한 에이전트에서 상태를 확인하고 다시 처리해 주세요.</p>}
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
