"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, Loader2, Mic } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useAsync } from "@/hooks/use-async";
import { useApi, useDemoMode } from "@/lib/api/context";
import type { Source, SourceAssociation, WorkspacePerson, WorkspaceProject } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * 소스 원문 뷰어입니다.
 *
 * Timeline·Graph·Ask에서 넘어온 청크를 강조하고 그 위치로 스크롤합니다.
 * 답변이 어디서 나왔는지 원문에서 직접 확인시켜 주는 것이 목적입니다.
 */
/** 초를 `분:초`로. 회의 녹음에서 그 구간이 나오는 위치를 알려줍니다. */
function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

const speakerTextColors = [
  "text-[var(--chart-2-hex)]",
  "text-[var(--chart-4-hex)]",
  "text-[var(--chart-1-hex)]",
  "text-[var(--chart-3-hex)]",
  "text-[var(--chart-5-hex)]",
];

function speakerColor(name: string): string {
  const index = [...name].reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return speakerTextColors[index % speakerTextColors.length];
}

const PLAYBACK_REFRESH_LEAD_MS = 30_000;

type PlaybackUrl = { url: string; expiresAt: string };
type AssociationRole = SourceAssociation["role"];
type PersonRoles = Record<string, AssociationRole[]>;

function rolesByPerson(associations: SourceAssociation[]): PersonRoles {
  const roles: PersonRoles = {};
  for (const { personId, role } of associations) {
    if (!roles[personId]) roles[personId] = [];
    if (!roles[personId].includes(role)) roles[personId].push(role);
  }
  return roles;
}

function associationPeople(roles: PersonRoles): SourceAssociation[] {
  return Object.entries(roles).flatMap(([personId, selected]) => selected.map((role) => ({ personId, role })));
}

function playbackNeedsRefresh(playback: PlaybackUrl, now = Date.now()): boolean {
  const expiresAt = Date.parse(playback.expiresAt);
  return !Number.isFinite(expiresAt) || expiresAt - now <= PLAYBACK_REFRESH_LEAD_MS;
}

export function SourceViewer({
  workspaceId,
  sourceId,
  highlightChunkId,
  onClose,
}: {
  workspaceId: string;
  sourceId: string | undefined;
  highlightChunkId?: string;
  onClose: () => void;
}) {
  const highlightRef = useRef<HTMLLIElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playback, setPlayback] = useState<PlaybackUrl>();
  const playbackRef = useRef<PlaybackUrl | undefined>(undefined);
  const requestRef = useRef<Promise<void> | null>(null);
  const sourceIdRef = useRef(sourceId);
  const requestGenerationRef = useRef(0);
  const retrySeekRef = useRef(0);
  const queuedSeekRef = useRef<{ seconds: number; resume: boolean } | undefined>(undefined);
  const [pendingSeek, setPendingSeek] = useState<{ seconds: number; resume: boolean }>();
  const [audioBusy, setAudioBusy] = useState(false);
  const [audioError, setAudioError] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const api = useApi();
  const isDemo = useDemoMode();
  const [source, setSource] = useState<Source>();
  const [people, setPeople] = useState<WorkspacePerson[]>([]);
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [projectIds, setProjectIds] = useState<string[]>([]);
  const [personRoles, setPersonRoles] = useState<PersonRoles>({});
  const [associationBusy, setAssociationBusy] = useState(false);
  const [associationError, setAssociationError] = useState<string>();
  const associationGenerationRef = useRef(0);

  useEffect(() => {
    associationGenerationRef.current += 1;
    setSource(undefined);
    setPeople([]);
    setProjects([]);
    setProjectIds([]);
    setPersonRoles({});
    setAssociationBusy(false);
    setAssociationError(undefined);
    if (!sourceId) return;
    let active = true;
    Promise.all([api.listSources(workspaceId), api.listPeople(workspaceId), api.listProjects(workspaceId)])
      .then(([sources, nextPeople, nextProjects]) => {
        if (!active) return;
        const nextSource = sources.find((item) => item.id === sourceId);
        setSource(nextSource);
        setPeople(nextPeople);
        setProjects(nextProjects);
        setProjectIds(nextSource?.projectIds ?? (nextSource?.projectId ? [nextSource.projectId] : []));
        setPersonRoles(rolesByPerson(nextSource?.associations ?? []));
        setAssociationError(undefined);
      })
      .catch((cause) => { if (active) setAssociationError(cause instanceof Error ? cause.message : "연결 정보를 불러오지 못했습니다."); });
    return () => { active = false; };
  }, [api, sourceId, workspaceId]);

  const saveAssociations = async () => {
    const currentSource = source;
    if (!sourceId || !currentSource || currentSource.id !== sourceId || associationBusy) return;
    const generation = associationGenerationRef.current;
    setAssociationBusy(true);
    setAssociationError(undefined);
    try {
      const saved = await api.updateSourceAssociations(workspaceId, sourceId, {
        revision: currentSource.associationRevision ?? 0,
        projectIds,
        people: associationPeople(personRoles),
      });
      if (generation !== associationGenerationRef.current || sourceIdRef.current !== sourceId) return;
      setSource((current) => current?.id === sourceId ? { ...current, associationRevision: saved.revision, projectIds: saved.projectIds, projectId: saved.projectIds[0] ?? null, associations: saved.people } : current);
      toast.success("소스 연결을 저장했습니다.");
    } catch (cause) {
      if (generation === associationGenerationRef.current && sourceIdRef.current === sourceId) setAssociationError(cause instanceof Error ? cause.message : "연결을 저장하지 못했습니다.");
    } finally { if (generation === associationGenerationRef.current && sourceIdRef.current === sourceId) setAssociationBusy(false); }
  };

  const { data, error, isLoading, reload } = useAsync(
    (signal) => (sourceId ? api.getSourceContent(sourceId, signal) : Promise.resolve(undefined)),
    [sourceId],
  );

  // 본문이 그려진 뒤에 강조 구간으로 스크롤합니다.
  useEffect(() => {
    if (!data || !highlightChunkId) return;
    const timer = setTimeout(
      () => highlightRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }),
      80,
    );
    return () => clearTimeout(timer);
  }, [data, highlightChunkId]);

  const Icon = data?.kind === "meeting" ? Mic : FileText;
  sourceIdRef.current = sourceId;
  useEffect(() => {
    requestGenerationRef.current += 1;
    playbackRef.current = undefined;
    requestRef.current = null;
    retrySeekRef.current = 0;
    queuedSeekRef.current = undefined;
    setPlayback(undefined);
    setPendingSeek(undefined);
    setAudioBusy(false);
    setAudioError(false);
  }, [sourceId]);
  useEffect(() => {
    if (!pendingSeek || !playback || !audioRef.current) return;
    const element = audioRef.current;
    const seek = () => {
      element.currentTime = pendingSeek.seconds;
      if (pendingSeek.resume) void element.play().catch(() => {});
      setPendingSeek(undefined);
    };
    if (element.readyState >= 1) seek();
    else element.addEventListener("loadedmetadata", seek, { once: true });
    return () => element.removeEventListener("loadedmetadata", seek);
  }, [playback, pendingSeek]);
  const loadAudio = useCallback(async (seconds?: number) => {
    if (!sourceId) return;
    if (requestRef.current) {
      if (seconds !== undefined) queuedSeekRef.current = { seconds, resume: true };
      return requestRef.current;
    }
    const current = playbackRef.current;
    if (current && !playbackNeedsRefresh(current)) {
      if (seconds !== undefined) setPendingSeek({ seconds, resume: true });
      return;
    }
    const element = audioRef.current;
    const seek = seconds ?? (current ? element?.currentTime ?? retrySeekRef.current : retrySeekRef.current);
    const resume = seconds !== undefined || (current ? Boolean(element && !element.paused) : retrySeekRef.current > 0);
    queuedSeekRef.current = current || retrySeekRef.current > 0 || seconds !== undefined
      ? { seconds: seek, resume }
      : undefined;
    const generation = requestGenerationRef.current;
    setAudioBusy(true);
    setAudioError(false);
    const request = api.getSourcePlaybackUrl(sourceId)
      .then((result) => {
        if (generation !== requestGenerationRef.current || sourceIdRef.current !== sourceId) return;
        setPendingSeek(queuedSeekRef.current);
        queuedSeekRef.current = undefined;
        playbackRef.current = result;
        setPlayback(result);
        retrySeekRef.current = 0;
      })
      .catch((error) => {
        if (generation === requestGenerationRef.current && sourceIdRef.current === sourceId) {
          queuedSeekRef.current = undefined;
          toast.error(error instanceof Error ? error.message : "녹음 파일을 열지 못했습니다.");
        }
      })
      .finally(() => {
        if (requestRef.current === request) {
          requestRef.current = null;
          setAudioBusy(false);
        }
      });
    requestRef.current = request;
    return request;
  }, [api, sourceId]);
  useEffect(() => {
    if (!playback) return;
    const refreshIn = Date.parse(playback.expiresAt) - Date.now() - PLAYBACK_REFRESH_LEAD_MS;
    // A very short-lived or malformed URL is refreshed on the next interaction.
    if (!Number.isFinite(refreshIn) || refreshIn <= 0) return;
    const timer = window.setTimeout(() => { void loadAudio(); }, refreshIn);
    return () => window.clearTimeout(timer);
  }, [loadAudio, playback]);
  const exportMarkdown = async () => {
    if (!sourceId || exportBusy) return;
    setExportBusy(true);
    try {
      const blob = await api.exportSourceMarkdown(sourceId);
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href; link.download = `${(data?.title ?? "meeting").replace(/[\\/:*?"<>|]/g, "-")}.md`;
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(href), 0);
    } catch (error) { toast.error(error instanceof Error ? error.message : "Markdown을 내려받지 못했습니다."); }
    finally { setExportBusy(false); }
  };

  return (
    <Sheet open={Boolean(sourceId)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 sm:max-w-xl">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            {data ? <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden /> : null}
            <span className="truncate">{data?.title ?? "원문"}</span>
          </SheetTitle>
          <SheetDescription>
            {highlightChunkId
              ? "근거로 인용된 구간을 강조했습니다."
              : "소스의 정규화된 원문입니다."}
          </SheetDescription>
        </SheetHeader>

        <div className="overflow-y-auto px-4 pb-6">
          {sourceId && source?.id === sourceId && <section className="mb-4 space-y-2 rounded-lg border p-3 text-sm">
            <h3 className="font-medium">프로젝트·사람 연결</h3>
            <div className="flex flex-wrap gap-2">{projects.filter((project) => !project.archivedAt || projectIds.includes(project.id)).map((project) => <label key={project.id} className="flex items-center gap-1"><input type="checkbox" disabled={isDemo || associationBusy || (Boolean(project.archivedAt) && !projectIds.includes(project.id))} checked={projectIds.includes(project.id)} onChange={(event) => setProjectIds((current) => event.target.checked ? [...current, project.id] : current.filter((id) => id !== project.id))} />{project.name}{project.archivedAt ? " (보관됨)" : ""}</label>)}</div>
            <div className="space-y-1">{people.filter((person) => !person.archivedAt || personRoles[person.id]?.length).map((person) => <div key={person.id} className="flex flex-wrap items-center gap-2"><span>{person.name}{person.archivedAt ? " (보관됨)" : ""}</span>{(["participant", "author"] as const).map((role) => <label key={role} className="flex items-center gap-1"><input type="checkbox" aria-label={`${person.name} ${role === "participant" ? "참여자" : "작성자"}`} disabled={isDemo || associationBusy || (Boolean(person.archivedAt) && !personRoles[person.id]?.includes(role))} checked={personRoles[person.id]?.includes(role) ?? false} onChange={(event) => setPersonRoles((current) => { const selected = current[person.id] ?? []; const next = event.target.checked ? [...selected, role] : selected.filter((item) => item !== role); if (!next.length) { const remaining = { ...current }; delete remaining[person.id]; return remaining; } return { ...current, [person.id]: next }; })} />{role === "participant" ? "참여자" : "작성자"}</label>)}</div>)}</div>
            {associationError && <div role="alert" className="flex items-center gap-2 text-xs text-destructive"><span>{associationError}</span><Button size="sm" variant="ghost" onClick={() => { const generation = associationGenerationRef.current; void api.listSources(workspaceId).then((sources) => { if (generation !== associationGenerationRef.current || sourceIdRef.current !== sourceId) return; const latest = sources.find((item) => item.id === sourceId); setSource(latest); setProjectIds(latest?.projectIds ?? (latest?.projectId ? [latest.projectId] : [])); setPersonRoles(rolesByPerson(latest?.associations ?? [])); setAssociationError(undefined); }).catch((cause) => { if (generation === associationGenerationRef.current && sourceIdRef.current === sourceId) setAssociationError(cause instanceof Error ? cause.message : "다시 불러오지 못했습니다."); }); }}>최신 정보 불러오기</Button></div>}
            {!isDemo && <Button size="sm" variant="outline" disabled={associationBusy || source?.id !== sourceId} onClick={() => void saveAssociations()}>{associationBusy ? "저장 중…" : "연결 저장"}</Button>}
          </section>}
          {data?.kind === "meeting" && <div className="mb-3 flex flex-wrap items-center gap-2">{data.hasRecording && <Button size="sm" variant="outline" disabled={audioBusy} onClick={() => void loadAudio()}>{audioBusy ? "녹음 여는 중…" : audioError ? "녹음 다시 시도" : "녹음 듣기"}</Button>}<Button size="sm" variant="outline" disabled={exportBusy} onClick={() => void exportMarkdown()}>{exportBusy ? "내려받는 중…" : "Markdown 내보내기"}</Button>{playback && <audio ref={audioRef} controls preload="metadata" src={playback.url} className="w-full" onTimeUpdate={(event) => { retrySeekRef.current = event.currentTarget.currentTime; }} onError={(event) => {
            if (event.currentTarget.currentSrc && event.currentTarget.currentSrc !== playbackRef.current?.url) return;
            retrySeekRef.current = event.currentTarget.currentTime || retrySeekRef.current;
            requestGenerationRef.current += 1;
            playbackRef.current = undefined;
            queuedSeekRef.current = undefined;
            setPendingSeek(undefined);
            setPlayback(undefined);
            setAudioBusy(false);
            setAudioError(true);
          }} />}</div>}
          {isLoading ? (
            <p className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              원문을 불러오는 중…
            </p>
          ) : error ? (
            <div className="py-10 text-center">
              <p className="text-sm">{error.message}</p>
              <Button variant="outline" size="sm" className="mt-4" onClick={reload}>
                다시 시도
              </Button>
            </div>
          ) : !data || data.chunks.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              표시할 원문이 없습니다.
            </p>
          ) : (
            <ol className={data.kind === "meeting" ? "space-y-1" : "space-y-3"}>
              {data.chunks.map((chunk) => {
                const isHighlighted = chunk.id === highlightChunkId;
                return (
                  <li
                    key={chunk.id}
                    ref={isHighlighted ? highlightRef : undefined}
                    className={cn(
                      "text-sm leading-relaxed transition-colors",
                      isHighlighted
                        ? "rounded-md bg-primary/5 ring-1 ring-primary/30"
                        : data.kind === "meeting"
                          ? ""
                          : "rounded-lg bg-muted/40",
                      data.kind === "meeting" ? "px-1 py-1" : "p-3",
                    )}
                  >
                    {chunk.startSeconds != null ? (
                      <button type="button" disabled={!data.hasRecording || audioBusy} onClick={() => chunk.startSeconds != null && void loadAudio(chunk.startSeconds)} className="mb-1 block font-mono text-xs text-muted-foreground hover:underline disabled:cursor-default disabled:no-underline">
                        {formatTimestamp(chunk.startSeconds)}
                        {chunk.endSeconds != null ? ` – ${formatTimestamp(chunk.endSeconds)}` : ""}
                      </button>
                    ) : null}
                    {data.kind === "meeting" ? (
                      <div className="space-y-0.5">
                        {chunk.text
                          .split(/\n+/)
                          .filter(Boolean)
                          .map((line, index) => {
                            const parts = /^([^:\n]{1,80}):\s*(.*)$/.exec(line);
                            return parts ? (
                              <div
                                key={index}
                                className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-3 sm:grid-cols-[8rem_minmax(0,1fr)]"
                              >
                                <span
                                  className={`truncate font-semibold ${speakerColor(parts[1])}`}
                                >
                                  {parts[1]}
                                </span>
                                <span className="whitespace-pre-wrap">{parts[2]}</span>
                              </div>
                            ) : (
                              <p key={index} className="whitespace-pre-wrap">
                                {line}
                              </p>
                            );
                          })}
                      </div>
                    ) : (
                      chunk.text
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
