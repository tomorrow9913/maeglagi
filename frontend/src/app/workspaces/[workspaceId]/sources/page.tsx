"use client";

import { use, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SourceList } from "@/features/source-ingestion/components/source-list";
import { UploadDropzone } from "@/features/source-ingestion/components/upload-dropzone";
import { UploadQueue } from "@/features/source-ingestion/components/upload-queue";
import { useDocumentUpload } from "@/features/source-ingestion/hooks/use-document-upload";
import { useJobPolling } from "@/features/source-ingestion/hooks/use-job-polling";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import type { ProcessingJob } from "@/lib/api";
import { workspacePath } from "@/lib/navigation";

export default function SourcesPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const router = useRouter();

  const {
    data: sources,
    error,
    isLoading,
    reload,
  } = useAsync((signal) => api.listSources(workspaceId, signal), [workspaceId]);

  const onUploaded = useCallback(() => reload(), [reload]);
  const { items, upload, dismiss } = useDocumentUpload(workspaceId, onUploaded);

  // 전송이 끝나 job이 붙은 항목만 폴링 대상입니다.
  const jobIds = useMemo(() => items.flatMap((item) => (item.job ? [item.job.id] : [])), [items]);

  const onSettled = useCallback(
    (job: ProcessingJob) => {
      reload();

      if (job.status === "failed") {
        toast.error("소스 처리에 실패했습니다.");
        return;
      }

      // 처리가 끝나면 맥락이 반영된 Timeline으로 갈 수 있게 안내합니다.
      toast.success("분석이 끝났습니다. Timeline에 반영됐습니다.", {
        action: {
          label: "Timeline 보기",
          onClick: () => router.push(workspacePath(workspaceId, "timeline")),
        },
      });
    },
    [reload, router, workspaceId],
  );

  const jobs = useJobPolling(jobIds, onSettled);

  return (
    <>
      <PageHeader title="소스" description="회의 녹음과 문서를 올리고 처리 상태를 확인합니다." />

      <UploadDropzone onFilesSelected={upload} />
      <UploadQueue items={items} jobs={jobs} onDismiss={dismiss} className="mt-4" />

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
