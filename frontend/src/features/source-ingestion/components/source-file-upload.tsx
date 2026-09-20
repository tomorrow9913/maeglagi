"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { useApi, useWorkspacePath } from "@/lib/api/context";
import type { WorkspaceProject } from "@/lib/api";
import { ACCEPTED_AUDIO_EXTENSIONS, MAX_AUDIO_BYTES, classifySourceFile } from "../lib/classify-source-file";
import { NO_PROJECTS_HINT } from "../lib/copy";
import { ACCEPTED_DOCUMENT_EXTENSIONS, MAX_DOCUMENT_BYTES } from "../lib/validate-file";
import { UploadDropzone } from "./upload-dropzone";

const megabytes = (bytes: number) => `${Math.round(bytes / (1024 * 1024))}MB`;
// 파일 이름에는 "/"가 들어갈 수 없어 구분자로 씁니다.
const fileKey = (file: File) => `${file.name}/${file.size}/${file.lastModified}`;

/**
 * 문서와 녹음 파일을 한 드롭존으로 받습니다.
 *
 * 전송 상태, 실패 사유, 다시 시도는 모두 업로드 큐(`UploadQueue`)에 한 줄로 보이므로
 * 이 컴포넌트는 같은 실패를 따로 다시 알리지 않습니다.
 */
export function SourceFileUpload({ workspaceId, onDocuments, onAudio }: {
  workspaceId: string;
  onDocuments: (files: File[]) => Promise<void>;
  onAudio: (audio: Blob, duration: number, liveDraft?: undefined, projectId?: string, projectIds?: string[]) => Promise<void>;
}) {
  const api = useApi();
  const workspacePath = useWorkspacePath();
  const [projects, setProjects] = useState<WorkspaceProject[]>();
  const [projectIds, setProjectIds] = useState<string[]>([]);
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
    const key = fileKey(file);
    // 같은 파일을 연달아 고르거나 끌어다 놓아도 한 번만 올립니다.
    if (submitted.current.has(key) || pending.current.has(key)) return;
    pending.current.add(key);
    setBusy(true);
    try {
      await onAudio(file, 0, undefined, ids[0], ids);
      submitted.current.add(key);
    } catch {
      // 실패·취소는 업로드 큐 항목에 남고 거기서 다시 시도합니다. 같은 파일을 다시 골라도 됩니다.
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
        const key = fileKey(file);
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

  const visibleProjects = projects?.filter((project) => !project.archivedAt || projectIds.includes(project.id)) ?? [];

  return (
    <div className="space-y-3">
      <div className="space-y-2 rounded-lg border p-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium">녹음 파일 프로젝트</p>
          <Link href={workspacePath(workspaceId, "directory")} className="text-xs underline">프로젝트·참여자 관리</Link>
        </div>
        {projects && visibleProjects.length === 0 ? (
          <p className="text-xs text-muted-foreground">{NO_PROJECTS_HINT}</p>
        ) : (
          <div className="flex flex-wrap gap-3">
            {visibleProjects.map((project) => (
              <label key={project.id} className="flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  checked={projectIds.includes(project.id)}
                  disabled={busy || Boolean(project.archivedAt)}
                  onChange={(event) => setProjectIds((current) => event.target.checked ? [...current, project.id] : current.filter((id) => id !== project.id))}
                />
                {project.name}
              </label>
            ))}
          </div>
        )}
        <p className="text-xs text-muted-foreground">선택한 프로젝트는 녹음 파일에 적용되고, 대본 검토에서 바꿀 수 있습니다. 받아쓰기가 끝난 뒤 대본을 확인하면 분석을 시작합니다.</p>
      </div>
      <UploadDropzone
        accept={[...ACCEPTED_DOCUMENT_EXTENSIONS, ...ACCEPTED_AUDIO_EXTENSIONS].join(",")}
        hint={`문서 PDF, DOCX, TXT, MD · 최대 ${megabytes(MAX_DOCUMENT_BYTES)} / 녹음 WebM, MP4, M4A, WAV, MP3, OGG, FLAC · 최대 ${megabytes(MAX_AUDIO_BYTES)}`}
        onFilesSelected={selectFiles}
      />
    </div>
  );
}
