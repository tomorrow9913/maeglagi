"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError, type MeetingReview, type MeetingUtterance, type ProcessingJob, type WorkspacePerson, type WorkspaceProject } from "@/lib/api";
import { useApi } from "@/lib/api/context";
import { reviewUtterances, unresolvedReviewPeople, type TranscriptTurn } from "../lib/transcript-draft";
import { TranscriptEditor, type SpeakerOption } from "./transcript-editor";

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
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string>();
  const [job, setJob] = useState<ProcessingJob>();
  const idMap = useRef(new Map<number, string>());
  const nextId = useRef(-1);
  const openId = useRef(sourceId);
  openId.current = sourceId;
  const load = useCallback(async (id: string, silent = false) => {
    if (!silent) setLoading(true);
    setLoadError(undefined);
    try {
      const [data, roster, projectList] = await Promise.all([api.getMeetingReview(workspaceId, id), api.listPeople(workspaceId), api.listProjects(workspaceId)]);
      if (openId.current !== id) return;
      const currentJob = data.reviewState === "confirmed" ? await api.getJob(id).catch(() => undefined) : undefined;
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
    } catch (error) { if (openId.current === id) setLoadError(error instanceof Error ? error.message : "대본을 불러오지 못했습니다."); }
    finally { if (openId.current === id) setLoading(false); }
  }, [api, workspaceId]);
  useEffect(() => { if (sourceId) void load(sourceId); else { setReview(undefined); setRows([]); setJob(undefined); setLoadError(undefined); } }, [sourceId, load]);
  useEffect(() => {
    if (!sourceId || review?.reviewState !== "transcribing" || review.status === "failed") return;
    const timer = window.setInterval(() => void load(sourceId, true), 3000);
    return () => window.clearInterval(timer);
  }, [sourceId, review?.reviewState, review?.status, load]);
  const invalidPersonRows = unresolvedReviewPeople(rows, people);
  const utterances = (): MeetingUtterance[] => reviewUtterances(rows, people, speakers, idMap.current);
  const retryTranscription = async () => {
    if (!sourceId || busy || review?.reviewState !== "transcribing" || review.status !== "failed") return;
    setBusy(true);
    try {
      const job = await api.retryMeetingTranscription(workspaceId, sourceId);
      await load(sourceId);
      onRetried?.(job);
      window.dispatchEvent(new Event("maeglagi:sources-changed"));
      toast.success("저장된 녹음으로 음성 인식을 다시 시작했습니다.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) await load(sourceId);
      toast.error(error instanceof Error ? error.message : "음성 인식을 다시 시작하지 못했습니다.");
    } finally { setBusy(false); }
  };
  const save = async () => {
    if (!sourceId || !review || busy || invalidPersonRows.length) return;
    setBusy(true);
    try {
      const next = await api.saveMeetingReview(workspaceId, sourceId, { revision: review.revision, projectId: projectId || null, projectIds, utterances: utterances() });
      setReview(next); setDirty(false); setConflict(false); toast.success("대본 초안을 저장했습니다.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) { setConflict(true); toast.error("다른 곳에서 대본이 수정됐습니다. 내용을 확인한 뒤 다시 불러와 주세요."); }
      else toast.error(error instanceof Error ? error.message : "대본을 저장하지 못했습니다.");
    } finally { setBusy(false); }
  };
  const confirm = async (retry = false) => {
    if (!sourceId || !review || busy || (!retry && (dirty || invalidPersonRows.length || !rows.some((row) => row.text.trim())))) return;
    setBusy(true);
    try { const job = await api.confirmMeetingReview(workspaceId, sourceId, review.revision); onConfirmed?.(job); toast.success("회의 대본을 확인했습니다. 분석을 시작합니다."); onClose(); }
    catch (error) {
      if (error instanceof ApiError && error.status === 409) setConflict(true);
      if (error instanceof ApiError && error.status === 503) {
        toast.error("대본은 확인됐지만 분석 대기열에 연결하지 못했습니다. 다시 시도할 수 있습니다.");
        await load(sourceId);
        window.dispatchEvent(new Event("maeglagi:sources-changed"));
      } else toast.error(error instanceof Error ? error.message : "확인하지 못했습니다.");
    }
    finally { setBusy(false); }
  };
  const replaceFromRaw = () => {
    if (!review?.rawUtterances.length || !window.confirm("현재 편집 중인 대본을 서버 음성 인식 원문으로 바꿀까요?")) return;
    const options = speakers.filter((speaker) => !speaker.id.startsWith("raw-")); const named = new Map<string, string>();
    for (const item of review.rawUtterances) if (!item.personId && !named.has(item.speakerName)) { const id = `raw-${named.size}`; named.set(item.speakerName, id); options.push({ id, name: item.speakerName }); }
    setSpeakers(options);
    idMap.current.clear();
    setRows(review.rawUtterances.map((item, index) => { idMap.current.set(index + 1, item.id); return { id: index + 1, speaker: item.personId || named.get(item.speakerName) || options[0].id, text: item.text, isFinal: true, startSeconds: item.startSeconds, endSeconds: item.endSeconds }; }));
    setDirty(true);
  };
  return <Dialog open={Boolean(sourceId)} onOpenChange={(open) => { if (!open && !busy && (!dirty || window.confirm("저장하지 않은 변경을 버릴까요?"))) onClose(); }}><DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl"><DialogHeader><DialogTitle>회의 대본 검토</DialogTitle><DialogDescription>{review?.reviewState === "confirmed" ? "확인된 대본과 프로젝트 정보는 유지됩니다." : "프로젝트와 화자·내용을 저장한 뒤 확인하면 분석과 색인을 시작합니다."}</DialogDescription></DialogHeader>
    {loading ? <p className="text-sm text-muted-foreground">대본을 불러오는 중…</p> : loadError ? <div role="alert" className="space-y-2 rounded-md border border-destructive p-3 text-sm"><p>{loadError}</p><Button size="sm" variant="outline" onClick={() => sourceId && void load(sourceId)}>다시 불러오기</Button></div> : !review ? <p className="text-sm text-muted-foreground">대본을 불러올 수 없습니다.<Button size="sm" variant="outline" onClick={() => sourceId && void load(sourceId)}>다시 시도</Button></p> : <div className="space-y-4">
      <p className="text-sm font-medium">{review.title} · {review.reviewState === "transcribing" ? review.status === "failed" ? "음성 인식 실패" : "서버 음성 인식 중" : review.reviewState === "confirmed" ? "확인됨" : "검토 필요"}</p>
      {review.reviewState === "transcribing" ? review.status === "failed" ? <div role="alert" className="space-y-2 rounded-md border border-destructive p-3 text-sm"><p>서버 음성 인식이 완료되지 않았습니다. 업로드한 녹음{review.utterances.length ? "과 실시간 대본 초안은" : "은"} 저장돼 있습니다.</p>{review.errorMessage && <p className="text-muted-foreground">{review.errorMessage}</p>}<div className="flex gap-2"><Button size="sm" disabled={busy} onClick={() => void retryTranscription()}>{busy ? "다시 시도 중…" : "저장된 녹음으로 다시 시도"}</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => sourceId && void load(sourceId)}>상태 새로고침</Button></div></div> : <div className="space-y-2"><p className="text-sm text-muted-foreground">음성 인식이 끝나면 대본이 자동으로 갱신됩니다. 소스 목록에서도 다시 열 수 있습니다.</p><Button size="sm" variant="outline" onClick={() => sourceId && void load(sourceId, true)}>지금 새로고침</Button></div> : <>
        {conflict && <div role="alert" className="rounded-md border border-destructive p-3 text-sm">대본 버전이 달라졌습니다. 현재 편집 내용을 보관하려면 복사한 뒤 다시 불러와 주세요.<Button size="sm" variant="outline" className="ml-2" onClick={() => sourceId && void load(sourceId)}>다시 불러오기</Button></div>}
        <fieldset className="space-y-1 text-sm"><legend className="font-medium">회의 프로젝트</legend><div className="flex flex-wrap gap-3">{projects.filter((item) => !item.archivedAt || projectIds.includes(item.id)).map((item) => <label key={item.id} className="flex items-center gap-1"><input type="checkbox" checked={projectIds.includes(item.id)} disabled={busy || review.reviewState === "confirmed" || Boolean(item.archivedAt)} onChange={(event) => { const next = event.target.checked ? [...projectIds, item.id] : projectIds.filter((id) => id !== item.id); setProjectIds(next); setProjectId(next[0] ?? ""); setDirty(true); }} />{item.name}{item.archivedAt ? " (보관됨)" : ""}</label>)}</div><p className="text-xs text-muted-foreground">프로젝트를 선택하지 않아도 대본은 확인할 수 있습니다.</p></fieldset>
        {(review.suggestedParticipants?.length ?? 0) > 0 && <p className="text-xs text-muted-foreground">선택한 프로젝트의 등록 참여자: {review.suggestedParticipants!.map((person) => person.name).join(", ")}. 실제 회의 발언자는 대본에서 직접 지정해 주세요.</p>}
        <div className="space-y-2"><p className="text-sm font-medium">새 발언 화자</p><div className="flex flex-wrap gap-1.5">{speakers.map((speaker) => <Button key={speaker.id} size="sm" variant="outline" disabled={review.reviewState === "confirmed"} aria-pressed={activeSpeaker === speaker.id} className={activeSpeaker === speaker.id ? "ring-2 ring-current" : ""} onClick={() => setActiveSpeaker(speaker.id)}>{speaker.name}</Button>)}</div><Button size="sm" variant="ghost" disabled={review.reviewState === "confirmed"} onClick={() => { const name = window.prompt("새 화자 이름"); if (name?.trim()) { const id = `local-${Date.now()}`; setSpeakers((values) => [...values, { id, name: name.trim() }]); setActiveSpeaker(id); } }}>미등록 화자 추가</Button></div>
        {speakers.filter((item) => item.id.startsWith("local-")).map((speaker) => <Input key={speaker.id} aria-label={`${speaker.name} 이름`} value={speaker.name} disabled={busy || review.reviewState === "confirmed"} onChange={(event) => { setSpeakers((values) => values.map((item) => item.id === speaker.id ? { ...item, name: event.target.value } : item)); setDirty(true); }} />)}
        <TranscriptEditor rows={rows} speakers={speakers} activeSpeaker={activeSpeaker} disabled={busy || review.reviewState === "confirmed"} onChange={(id, values) => { setRows((items) => items.map((item) => item.id === id ? { ...item, ...values } : item)); setDirty(true); }} onDelete={(id) => { setRows((items) => items.filter((item) => item.id !== id)); setDirty(true); }} onAdd={() => { const id = nextId.current--; setRows((items) => [...items, { id, speaker: activeSpeaker, text: "", isFinal: true, edited: true }]); setDirty(true); return id; }} />
        {invalidPersonRows.length > 0 && review.reviewState === "awaiting_review" && <p role="alert" className="text-sm text-destructive">보관됐거나 목록에 없는 참여자가 {invalidPersonRows.length}개 발언에 연결돼 있습니다. 해당 발언에서 활성 참여자 또는 미등록 화자를 다시 선택해 주세요.</p>}
        {review.rawTranscriptText && <details className="rounded-lg border p-3 text-xs"><summary className="cursor-pointer font-medium">{review.transcriptSource === "server" ? "서버 음성 인식 원문 보기" : "업로드한 원문 보기"}</summary><pre className="mt-2 whitespace-pre-wrap font-sans">{review.rawTranscriptText}</pre>{review.reviewState === "awaiting_review" && review.rawUtterances.length > 0 && <Button size="sm" variant="outline" className="mt-2" onClick={replaceFromRaw}>원문으로 편집 초안 바꾸기</Button>}</details>}
        {review.reviewState === "awaiting_review" && <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy || !dirty || conflict || invalidPersonRows.length > 0} onClick={() => void save()}>{busy ? "저장 중…" : "초안 저장"}</Button><Button disabled={busy || dirty || conflict || invalidPersonRows.length > 0 || !rows.some((row) => row.text.trim()) || projectIds.some((id) => Boolean(projects.find((item) => item.id === id)?.archivedAt))} onClick={() => void confirm()}>확인하고 분석 시작</Button>{dirty && <span className="self-center text-xs text-muted-foreground">확인 전에 변경 내용을 저장해 주세요.</span>}</div>}
        {review.reviewState === "confirmed" && job?.status === "failed" && <div className="flex flex-wrap items-center gap-2 rounded-md border border-destructive p-3 text-sm"><span>대본은 확인됐지만 분석을 시작하지 못했습니다. 저장된 대본과 프로젝트 정보는 유지됩니다.</span><Button size="sm" disabled={busy} onClick={() => void confirm(true)}>분석 다시 시도</Button></div>}
      </>}
    </div>}
  </DialogContent></Dialog>;
}
