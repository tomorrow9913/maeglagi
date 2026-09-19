"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useApi, useWorkspacePath } from "@/lib/api/context";
import type { WorkspaceProject } from "@/lib/api";
import { ACCEPTED_AUDIO_EXTENSIONS, classifySourceFile } from "../lib/classify-source-file";
import { ACCEPTED_DOCUMENT_EXTENSIONS } from "../lib/validate-file";
import { UploadDropzone } from "./upload-dropzone";

export function SourceFileUpload({ workspaceId, onDocuments, onAudio }: {
  workspaceId: string;
  onDocuments: (files: File[]) => Promise<void>;
  onAudio: (audio: Blob, duration: number, liveDraft?: undefined, projectId?: string, projectIds?: string[]) => Promise<void>;
}) {
  const api = useApi();
  const workspacePath = useWorkspacePath();
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [projectIds, setProjectIds] = useState<string[]>([]);
  const [failed, setFailed] = useState<Map<string, File>>(new Map());
  const [busy, setBusy] = useState(false);
  const submitted = useRef(new Set<string>());
  const pending = useRef(new Set<string>());
  const pendingDocuments = useRef(new Set<string>());

  useEffect(() => {
    let active = true;
    void api.listProjects(workspaceId).then((result) => { if (active) setProjects(result); }).catch(() => { /* Upload remains available without project metadata. */ });
    return () => { active = false; };
  }, [api, workspaceId]);

  const uploadAudio = useCallback(async (file: File, ids: string[]) => {
    const key = `${file.name}\u0000${file.size}\u0000${file.lastModified}`;
    if (submitted.current.has(key) || pending.current.has(key)) return;
    pending.current.add(key);
    setBusy(true);
    try {
      await onAudio(file, 0, undefined, ids[0], ids);
      submitted.current.add(key);
      setFailed((current) => { const next = new Map(current); next.delete(key); return next; });
    } catch {
      setFailed((current) => new Map(current).set(key, file));
    } finally {
      pending.current.delete(key);
      setBusy(pending.current.size > 0);
    }
  }, [onAudio]);

  const selectFiles = useCallback((files: File[]) => {
    const documents: File[] = [];
    const documentKeys: string[] = [];
    for (const file of files) {
      const result = classifySourceFile(file);
      if (result.kind === "document") {
        const key = `${file.name}\u0000${file.size}\u0000${file.lastModified}`;
        if (!pendingDocuments.current.has(key)) {
          pendingDocuments.current.add(key);
          documentKeys.push(key);
          documents.push(result.file);
        }
      }
      else if (result.kind === "audio") void uploadAudio(result.file, [...projectIds]);
      else toast.error(`${file.name}: ${result.reason}`);
    }
    if (documents.length) void onDocuments(documents).finally(() => {
      documentKeys.forEach((key) => pendingDocuments.current.delete(key));
    });
  }, [onDocuments, projectIds, uploadAudio]);

  return <div className="space-y-3">
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex items-center justify-between"><p className="text-sm font-medium">녹음 파일 프로젝트</p><Link href={workspacePath(workspaceId, "directory")} className="text-xs underline">프로젝트·참여자 관리</Link></div>
      <div className="flex flex-wrap gap-3">{projects.filter((project) => !project.archivedAt || projectIds.includes(project.id)).map((project) => <label key={project.id} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={projectIds.includes(project.id)} disabled={busy || Boolean(project.archivedAt)} onChange={(event) => setProjectIds((current) => event.target.checked ? [...current, project.id] : current.filter((id) => id !== project.id))} />{project.name}</label>)}</div>
      <p className="text-xs text-muted-foreground">선택한 프로젝트는 녹음 파일에 적용됩니다. 대본 검토에서 변경할 수 있습니다. 음성 인식 후 대본을 확인해야 분석이 시작됩니다.</p>
    </div>
    <UploadDropzone
      accept={[...ACCEPTED_DOCUMENT_EXTENSIONS, ...ACCEPTED_AUDIO_EXTENSIONS].join(",")}
      hint="문서 PDF, DOCX, TXT, MD · 녹음 WebM, MP4, M4A, WAV, MP3, OGG, FLAC"
      onFilesSelected={selectFiles}
    />
    {[...failed].map(([key, file]) => <div key={key} role="alert" className="space-x-2 text-sm text-destructive"><span>{file.name}: 업로드에 실패했습니다. 파일은 이 화면에 남아 있습니다.</span><Button size="sm" variant="outline" disabled={pending.current.has(key)} onClick={() => void uploadAudio(file, [...projectIds])}>업로드 다시 시도</Button><Button size="sm" variant="ghost" disabled={pending.current.has(key)} onClick={() => setFailed((current) => { const next = new Map(current); next.delete(key); return next; })}>파일 선택 취소</Button></div>)}
  </div>;
}
