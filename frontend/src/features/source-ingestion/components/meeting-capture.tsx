"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApi, useWorkspacePath } from "@/lib/api/context";
import type { MeetingUtterance, TranscriptSourceInput, WorkspacePerson, WorkspaceProject } from "@/lib/api";
import { useAudioRecorder } from "../hooks/use-audio-recorder";
import { useBrowserTranscript } from "../hooks/use-browser-transcript";
import { mergeTranscript, type TranscriptTurn } from "../lib/transcript-draft";
import { addRoster, meetingUtterances, nextLocalSpeakerName, projectRoster, removeSpeaker } from "../lib/meeting-roster";
import { RecordingControls } from "./recording-controls";
import { TranscriptEditor, type SpeakerOption } from "./transcript-editor";
import { toUserMessage } from "@/lib/api/error-message";

const speakerColors = ["var(--chart-2-hex)", "var(--chart-4-hex)", "var(--chart-1-hex)", "var(--chart-3-hex)", "var(--chart-5-hex)"];
function speakerColor(id: string) {
  return speakerColors[[...id].reduce((total, character) => total + character.charCodeAt(0), 0) % speakerColors.length];
}

export function MeetingCapture({ workspaceId, onAudio, onTranscript, onBusyChange }: {
  workspaceId: string;
  onAudio: (audio: Blob, duration: number, liveDraft?: { utterances: MeetingUtterance[] }, projectId?: string, projectIds?: string[]) => Promise<void>;
  onTranscript: (input: TranscriptSourceInput, projectId?: string) => Promise<boolean>;
  onBusyChange?: (busy: boolean) => void;
}) {
  const api = useApi();
  const workspacePath = useWorkspacePath();
  const [mode, setMode] = useState<"text" | "audio">("audio");
  const [draft, setDraft] = useState<TranscriptTurn[] | null>(null);
  const draftRef = useRef<TranscriptTurn[] | null>(null);
  const commitDraft = (next: TranscriptTurn[] | null) => { draftRef.current = next; setDraft(next); };
  const [duration, setDuration] = useState(0);
  const [title, setTitle] = useState("회의 대본");
  const [people, setPeople] = useState<WorkspacePerson[]>([]);
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [directoryLoading, setDirectoryLoading] = useState(true);
  const [directoryLoadError, setDirectoryLoadError] = useState(false);
  const [projectIds, setProjectIds] = useState<string[]>([]);
  const projectId = projectIds[0] ?? "";
  const [speakers, setSpeakers] = useState<SpeakerOption[]>([{ id: "local-1", name: "화자 1" }]);
  const [localName, setLocalName] = useState("");
  const [rosterNotice, setRosterNotice] = useState("");
  const [currentSpeaker, setCurrentSpeaker] = useState("local-1");
  const speakerRef = useRef("local-1");
  const previousSegments = useRef<TranscriptTurn[]>([]);
  const deletedIds = useRef(new Set<number>());
  const manualId = useRef(-1);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [audioStarted, setAudioStarted] = useState(false);
  const [speechFinalized, setSpeechFinalized] = useState(true);
  const [recordingFailed, setRecordingFailed] = useState(false);
  const stopRequested = useRef(false);
  const pendingAudio = useRef<{ blob: Blob; seconds: number } | null>(null);
  const [pendingAudioReady, setPendingAudioReady] = useState(false);
  const [audioUploadError, setAudioUploadError] = useState<string>();
  const [failedFile, setFailedFile] = useState<File>();
  const [fileUploadError, setFileUploadError] = useState<string>();
  const speech = useBrowserTranscript(
    (_lines, seconds) => {
      setDuration((value) => value + seconds);
      commitDraft(draftRef.current ?? []);
      setSpeechFinalized(true);
    },
    (segments) => {
      const speaker = speakerRef.current;
      const timed = segments.map((segment) => ({ ...segment, startSeconds: segment.startSeconds == null ? null : segment.startSeconds + duration, endSeconds: segment.endSeconds == null ? null : segment.endSeconds + duration }));
      commitDraft(mergeTranscript(draftRef.current ?? [], [...previousSegments.current, ...timed].filter((segment) => !deletedIds.current.has(segment.id)), speaker));
    },
  );
  const recorder = useAudioRecorder({ onComplete: (blob, seconds) => { pendingAudio.current = { blob, seconds }; setPendingAudioReady(true); } });
  const active = speech.status !== "idle" || ["requesting", "recording", "stopping"].includes(recorder.status);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([api.listPeople(workspaceId), api.listProjects(workspaceId)]).then(([roster, options]) => {
      if (cancelled) return;
      setPeople(roster);
      setProjects(options);
      setDirectoryLoading(false);
      setDirectoryLoadError(false);
    }).catch(() => { if (!cancelled) { setDirectoryLoading(false); setDirectoryLoadError(true); } });
    return () => { cancelled = true; };
  }, [api, workspaceId]);
  useEffect(() => {
    if (mode !== "audio" || recorder.status !== "recording" || audioStarted) return;
    setAudioStarted(true);
    previousSegments.current = draftRef.current ?? [];
    setSpeechFinalized(false);
    if (speech.start()) commitDraft(draftRef.current ?? []);
    else setSpeechFinalized(true);
  }, [mode, recorder.status, audioStarted, speech]);
  useEffect(() => {
    if (mode !== "audio" || recorder.status !== "recording" || !audioStarted || stopRequested.current || speech.status !== "idle" || speech.error) return;
    const timer = window.setTimeout(() => {
      if (stopRequested.current) return;
      previousSegments.current = draftRef.current ?? [];
      setSpeechFinalized(false);
      if (!speech.start()) setSpeechFinalized(true);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [mode, recorder.status, audioStarted, speech.status, speech.error, speech]);
  useEffect(() => {
    if (!pendingAudioReady || !speechFinalized || speech.status !== "idle" || savingRef.current || !pendingAudio.current) return;
    const pending = pendingAudio.current;
    pendingAudio.current = null;
    setPendingAudioReady(false);
    savingRef.current = true;
    setSaving(true);
    setAudioUploadError(undefined);
    void onAudio(pending.blob, pending.seconds, { utterances: meetingUtterances(draftRef.current ?? [], speakers, people) }, projectId || undefined, projectIds)
      .then(() => { commitDraft(null); setDuration(0); previousSegments.current = []; deletedIds.current.clear(); setAudioStarted(false); setRecordingFailed(false); })
      .catch((error) => { setAudioUploadError(toUserMessage(error, "오디오를 올리지 못했습니다.")); pendingAudio.current = pending; })
      .finally(() => { savingRef.current = false; setSaving(false); });
  }, [pendingAudioReady, speechFinalized, speech.status, onAudio, speakers, people, projectId, projectIds]);
  useEffect(() => {
    if (!audioStarted || stopRequested.current || !["error", "denied", "unsupported"].includes(recorder.status)) return;
    stopRequested.current = true;
    setRecordingFailed(true);
    speech.stop();
  }, [audioStarted, recorder.status, speech]);
  useEffect(() => { onBusyChange?.(active || draft !== null || saving || pendingAudioReady || Boolean(audioUploadError)); }, [active, draft, saving, pendingAudioReady, audioUploadError, onBusyChange]);
  useEffect(() => {
    if (!active && draft === null && !saving && !pendingAudioReady && !audioUploadError) return;
    const preventLoss = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", preventLoss);
    return () => window.removeEventListener("beforeunload", preventLoss);
  }, [active, draft, saving, pendingAudioReady, audioUploadError]);

  const update = (id: number, values: Partial<TranscriptTurn>) => commitDraft(draftRef.current?.map((row) => row.id === id ? { ...row, ...values } : row) ?? null);
  const addTurn = () => {
    const id = manualId.current--;
    commitDraft([...(draftRef.current ?? []), { id, speaker: speakerRef.current, text: "", isFinal: true, edited: true }]);
    return id;
  };
  const stopAudio = () => { stopRequested.current = true; speech.stop(); recorder.stop(); };
  const submit = async () => {
    if (active || savingRef.current || !draft?.some((row) => row.text.trim())) return;
    savingRef.current = true;
    setSaving(true);
    try {
      const utterances = meetingUtterances(draft, speakers, people);
      const text = utterances.filter((item) => item.text.trim()).map((item) => `${item.speakerName}: ${item.text.trim()}`).join("\n\n");
      const accepted = await onTranscript({ title: title.trim() || "회의 대본", text, durationSeconds: duration, utterances, projectIds }, projectId || undefined);
      if (accepted) { commitDraft(null); setDuration(0); previousSegments.current = []; deletedIds.current.clear(); setRecordingFailed(false); setAudioStarted(false); }
    } finally { savingRef.current = false; setSaving(false); }
  };
  const addPerson = (person: WorkspacePerson) => {
    if (speakers.some((item) => item.id === person.id)) return;
    setSpeakers((items) => addRoster(items, [person], people));
  };
  const retryDirectoryLoad = () => {
    setDirectoryLoading(true);
    void Promise.all([api.listPeople(workspaceId), api.listProjects(workspaceId)]).then(([roster, options]) => {
      setPeople(roster);
      setProjects(options);
      setDirectoryLoading(false);
      setDirectoryLoadError(false);
    }).catch(() => { setDirectoryLoading(false); setDirectoryLoadError(true); });
  };
  const loadProjectPeople = () => {
    const roster = projectRoster(projectIds, projects, people);
    setSpeakers((items) => addRoster(items, roster, people));
    setRosterNotice(`${roster.length}명의 프로젝트 참여자를 확인했습니다. 이미 선택한 참여자는 중복 추가하지 않았습니다.`);
  };
  const addLocalSpeaker = () => {
    const name = localName.trim() || nextLocalSpeakerName(speakers);
    setSpeakers((items) => [...items, { id: `local-${crypto.randomUUID()}`, name }]);
    setLocalName("");
    setRosterNotice("");
  };
  const deleteSpeaker = (id: string) => {
    const name = speakers.find((item) => item.id === id)?.name ?? "화자";
    const result = removeSpeaker(speakers, draftRef.current ?? [], speakerRef.current, id, `local-${crypto.randomUUID()}`);
    setSpeakers(result.speakers);
    commitDraft(draftRef.current === null ? null : result.rows);
    const replacement = result.replacement;
    if (replacement) previousSegments.current = previousSegments.current.map((row) => row.speaker === id ? { ...row, speaker: replacement.id, personId: null } : row);
    speakerRef.current = result.currentSpeaker;
    setCurrentSpeaker(result.currentSpeaker);
    setRosterNotice(result.reassigned > 0
      ? `${name}을(를) 제거했습니다. 기존 발언 ${result.reassigned}개는 내용 그대로 새 임시 화자 ${result.replacement?.name}에게 옮겼습니다.`
      : result.replacement
        ? `${name}을(를) 제거하고 새 임시 화자 ${result.replacement.name}을(를) 현재 화자로 선택했습니다.`
        : `${name}을(를) 제거했습니다.`);
  };
  const discardFailedCapture = () => {
    if (!window.confirm("녹음과 편집 중인 대본을 버릴까요?")) return;
    pendingAudio.current = null;
    setPendingAudioReady(false);
    setAudioUploadError(undefined);
    setRecordingFailed(false);
    setAudioStarted(false);
    setSpeechFinalized(true);
    commitDraft(null);
    setDuration(0);
    previousSegments.current = [];
    deletedIds.current.clear();
  };
  const cannotStartAudio = saving || pendingAudioReady || Boolean(pendingAudio.current) || Boolean(audioUploadError) || Boolean(failedFile) || recordingFailed;
  const uploadAudioFile = async (file: File) => {
    if (active || savingRef.current || pendingAudio.current) return;
    savingRef.current = true;
    setSaving(true);
    setFileUploadError(undefined);
    try { await onAudio(file, 0, undefined, projectId || undefined, projectIds); setFailedFile(undefined); }
    catch (error) { setFailedFile(file); setFileUploadError(toUserMessage(error, "파일을 올리지 못했습니다.")); }
    finally { savingRef.current = false; setSaving(false); }
  };
  return <div className="space-y-4">
    <fieldset disabled={active || saving || draft !== null} className="flex flex-wrap gap-4 text-sm">
      <legend className="mb-2 font-medium">회의 저장 방식</legend>
      <label className="flex items-center gap-2"><input type="radio" name="meeting-mode" checked={mode === "audio"} onChange={() => setMode("audio")} />오디오 녹음 + 실시간 받아쓰기</label>
      <label className="flex items-center gap-2"><input type="radio" name="meeting-mode" checked={mode === "text"} onChange={() => setMode("text")} />텍스트만 작성</label>
    </fieldset>
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex items-center justify-between"><p className="text-sm font-medium">회의 프로젝트</p><Link href={workspacePath(workspaceId, "directory")} className="text-xs underline">프로젝트·참여자 관리</Link></div>
      <div className="flex flex-wrap gap-3">{projects.filter((item) => !item.archivedAt || projectIds.includes(item.id)).map((project) => <label key={project.id} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={projectIds.includes(project.id)} disabled={saving || (Boolean(project.archivedAt) && !projectIds.includes(project.id))} onChange={(event) => setProjectIds((current) => event.target.checked ? [...current, project.id] : current.filter((id) => id !== project.id))} />{project.name}{project.archivedAt ? " (보관됨)" : ""}</label>)}</div>
      <div className="flex flex-wrap items-center gap-2"><Button size="sm" variant="outline" disabled={!projectIds.length || saving || directoryLoading || directoryLoadError} onClick={loadProjectPeople}>선택한 프로젝트 참여자 불러오기</Button><p className="text-xs text-muted-foreground">프로젝트를 선택한 뒤 불러오세요. 회의 프로젝트는 최종 검토에서 변경할 수 있습니다.</p></div>
      {directoryLoading && <p role="status" className="text-xs text-muted-foreground">참여자·프로젝트 목록을 불러오는 중입니다.</p>}
      {directoryLoadError && <div role="alert" className="flex items-center gap-2 text-xs text-destructive"><span>참여자·프로젝트 목록을 불러오지 못했습니다.</span><Button size="sm" variant="outline" disabled={saving} onClick={retryDirectoryLoad}>다시 시도</Button></div>}
    </div>
    <div className="space-y-2">
      <p className="text-sm font-medium">참여자 · 현재 화자</p>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="현재 화자 선택과 참여자 제거">{speakers.map((item) => <span key={item.id} className={`group inline-flex items-center rounded-full border bg-background text-sm ${currentSpeaker === item.id ? "ring-2 ring-ring" : ""}`} style={{ color: speakerColor(item.id) }}><button type="button" disabled={saving} aria-label={`${item.name} 현재 화자로 선택`} aria-pressed={currentSpeaker === item.id} className="rounded-l-full px-3 py-1.5 font-medium hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring" onClick={() => { speakerRef.current = item.id; setCurrentSpeaker(item.id); }}>{item.name}</button><button type="button" disabled={saving} aria-label={`${item.name} 참여자 제거`} title={`${item.name} 제거`} className="rounded-r-full p-2.5 opacity-100 hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring [@media(hover:hover)_and_(pointer:fine)]:opacity-0 [@media(hover:hover)_and_(pointer:fine)]:group-hover:opacity-100 [@media(hover:hover)_and_(pointer:fine)]:focus-visible:opacity-100" onClick={() => deleteSpeaker(item.id)}><X className="size-3.5" aria-hidden /></button></span>)}</div>
      <div className="flex flex-wrap gap-2"><select aria-label="전체 작업공간에서 참여자 추가" defaultValue="" disabled={saving || directoryLoading || directoryLoadError} onChange={(event) => { const person = people.find((item) => item.id === event.target.value); if (person) addPerson(person); event.target.value = ""; }} className="rounded-md border bg-background px-2 py-1 text-sm"><option value="">전체 작업공간에서 참여자 추가</option>{people.filter((item) => !item.archivedAt && !speakers.some((speaker) => speaker.id === item.id)).map((item) => <option key={item.id} value={item.id}>{item.name}{item.role ? ` · ${item.role}` : ""}</option>)}</select><Input aria-label="이번 회의 임시 화자 이름" placeholder="이번 회의 임시 화자 이름" value={localName} maxLength={80} className="w-48" disabled={saving} onChange={(event) => setLocalName(event.target.value)} onKeyDown={(event) => {
        if (event.key !== "Enter" || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return;
        event.preventDefault();
        addLocalSpeaker();
      }} /><Button size="sm" variant="outline" disabled={saving} onClick={addLocalSpeaker}>임시 화자 추가</Button></div>
      <div className="grid gap-2 sm:grid-cols-2">{speakers.filter((item) => item.id.startsWith("local-")).map((item) => <Input key={item.id} aria-label={`${item.name} 이름`} value={item.name} maxLength={80} disabled={saving} onChange={(event) => setSpeakers((items) => items.map((speaker) => speaker.id === item.id ? { ...speaker, name: event.target.value } : speaker))} />)}</div>
      {rosterNotice && <p role="status" className="text-xs text-muted-foreground">{rosterNotice}</p>}
    </div>
    {mode === "audio" ? <><RecordingControls {...recorder} disableStart={cannotStartAudio} onStart={() => { if (cannotStartAudio) return; stopRequested.current = false; setRecordingFailed(false); setAudioStarted(false); void recorder.start(); }} onStop={stopAudio} /><label className="block space-y-1 text-sm">기존 오디오 파일 업로드<Input type="file" accept="audio/*,.mp3,.m4a,.wav,.webm,.ogg" disabled={active || saving || Boolean(pendingAudio.current) || Boolean(failedFile)} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadAudioFile(file); event.target.value = ""; }} /></label>{failedFile && <div role="alert" className="space-x-2 text-sm text-destructive"><span>{failedFile.name}: {fileUploadError} 파일은 이 화면에 남아 있습니다.</span><Button size="sm" variant="outline" disabled={saving} onClick={() => void uploadAudioFile(failedFile)}>파일 업로드 다시 시도</Button><Button size="sm" variant="ghost" disabled={saving} onClick={() => { setFailedFile(undefined); setFileUploadError(undefined); }}>파일 선택 취소</Button></div>}<p className="text-xs text-muted-foreground">녹음과 동시에 브라우저 받아쓰기를 시도합니다. 지원되지 않거나 권한이 없어도 오디오 녹음은 계속됩니다. 오디오 파일도 서버 대본을 검토하고 명시적으로 확인해야 분석됩니다.</p>{speech.error && <p role="status" className="text-xs text-muted-foreground">실시간 받아쓰기: {speech.error}</p>}{pendingAudioReady && <p role="status" className="text-xs text-muted-foreground">마지막 받아쓰기 결과를 기다린 뒤 오디오와 초안을 올립니다.</p>}{audioUploadError && <p role="alert" className="space-x-2 text-sm text-destructive"><span>{audioUploadError} 오디오와 편집 내용은 이 화면에 남아 있습니다.</span><Button size="sm" variant="outline" disabled={saving} onClick={() => setPendingAudioReady(true)}>업로드 다시 시도</Button><Button size="sm" variant="ghost" disabled={saving} onClick={discardFailedCapture}>녹음 버리기</Button></p>}{recordingFailed && !audioUploadError && <div role="alert" className="space-x-2 text-sm text-destructive"><span>녹음 오류로 오디오를 올리지 못했습니다. 받아쓴 대본은 유지됩니다.</span>{draft?.some((row) => row.text.trim()) && <Button size="sm" variant="outline" disabled={speech.status !== "idle" || saving} onClick={() => void submit()}>텍스트 초안 업로드</Button>}<Button size="sm" variant="ghost" disabled={speech.status !== "idle" || saving} onClick={discardFailedCapture}>초안 버리기</Button></div>}</> : <div className="flex gap-2">{speech.status === "idle" ? <><Button variant="outline" onClick={addTurn}>직접 작성</Button><Button onClick={() => { previousSegments.current = draftRef.current ?? []; if (speech.start()) commitDraft(draftRef.current ?? []); }}>받아쓰기 시작</Button></> : <Button variant="outline" onClick={speech.stop}>받아쓰기 종료</Button>}</div>}
    {draft && <section aria-label="대본 편집" className="space-y-3"><h3 className="font-medium">{active ? "실시간 대본 · 바로 편집" : "대본 초안"}</h3><p className="text-xs text-muted-foreground">직접 수정한 내용은 이후 인식 결과가 덮어쓰지 않습니다. 서버 대본은 업로드 후 별도로 보존됩니다.</p><label className="block space-y-1 text-sm">제목<Input value={title} maxLength={255} disabled={saving} onChange={(event) => setTitle(event.target.value)} /></label><TranscriptEditor rows={draft} speakers={speakers} activeSpeaker={currentSpeaker} disabled={saving} listening={active} onChange={update} onDelete={(id) => { deletedIds.current.add(id); commitDraft(draftRef.current?.filter((item) => item.id !== id) ?? null); }} onAdd={addTurn} />{mode === "text" && <Button disabled={active || saving || !draft.some((row) => row.text.trim())} onClick={() => void submit()}>{saving ? "업로드 중…" : "대본 초안 업로드 · 검토로 이동"}</Button>}</section>}
  </div>;
}
