"use client";

import { use, useCallback } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SourceList } from "@/features/source-ingestion/components/source-list";
import { UploadDropzone } from "@/features/source-ingestion/components/upload-dropzone";
import { UploadQueue } from "@/features/source-ingestion/components/upload-queue";
import { useDocumentUpload } from "@/features/source-ingestion/hooks/use-document-upload";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";

export default function SourcesPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);

  const {
    data: sources,
    error,
    isLoading,
    reload,
  } = useAsync((signal) => api.listSources(workspaceId, signal), [workspaceId]);

  // 업로드가 끝나면 목록을 다시 불러 새 소스를 바로 보여줍니다.
  const onUploaded = useCallback(() => reload(), [reload]);
  const { items, upload, dismiss } = useDocumentUpload(workspaceId, onUploaded);

  return (
    <>
      <PageHeader title="소스" description="회의 녹음과 문서를 올리고 처리 상태를 확인합니다." />

      <UploadDropzone onFilesSelected={upload} />
      <UploadQueue items={items} onDismiss={dismiss} className="mt-4" />

      <section className="mt-10">
        <h2 className="mb-3 text-sm font-medium">올라온 소스</h2>

        {isLoading ? (
          <Skeleton className="h-40 w-full rounded-xl" />
        ) : error ? (
          <div className="rounded-xl border border-border bg-card p-10 text-center">
            <p className="text-sm">{error.message}</p>
            <Button variant="outline" size="sm" className="mt-4" onClick={reload}>
              다시 시도
            </Button>
          </div>
        ) : sources && sources.length > 0 ? (
          <SourceList sources={sources} />
        ) : (
          <div className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
            아직 올라온 소스가 없습니다. 문서를 올려 맥락을 쌓아보세요.
          </div>
        )}
      </section>
    </>
  );
}
