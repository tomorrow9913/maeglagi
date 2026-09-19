"use client";

import { Suspense, use, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/common/state-views";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MeetingCapture } from "@/features/source-ingestion/components/meeting-capture";
import { SourceList } from "@/features/source-ingestion/components/source-list";
import { SourceViewer } from "@/features/source-ingestion/components/source-viewer";
import { UploadDropzone } from "@/features/source-ingestion/components/upload-dropzone";
import { UploadQueue } from "@/features/source-ingestion/components/upload-queue";
import { useJobPolling } from "@/features/source-ingestion/hooks/use-job-polling";
import { useSourceUpload } from "@/features/source-ingestion/hooks/use-source-upload";
import { useAsync } from "@/hooks/use-async";
import { useApi, useWorkspacePath } from "@/lib/api/context";
import type { ProcessingJob } from "@/lib/api";

export default function SourcesPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);

  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
      <SourcesView workspaceId={workspaceId} />
    </Suspense>
  );
}

function SourcesView({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const router = useRouter();
  const workspacePath = useWorkspacePath();
  const [meetingBusy, setMeetingBusy] = useState(false);
  const searchParams = useSearchParams();

  /*
   * 다른 화면(Timeline·Graph·Ask)이 `?source=&chunk=`로 원문을 열어달라고
   * 요청합니다. URL을 상태로 삼아 뒤로 가기로도 닫히게 둡니다.
   */
  const [viewer, setViewer] = useState<{ sourceId: string; chunkId?: string }>();

  useEffect(() => {
    const sourceId = searchParams.get("source");
    if (!sourceId) {
      setViewer(undefined);
      return;
    }
    setViewer({ sourceId, chunkId: searchParams.get("chunk") ?? undefined });
  }, [searchParams]);

  const closeViewer = useCallback(() => {
    setViewer(undefined);
    // 쿼리를 지워 새로고침해도 다시 열리지 않게 합니다.
    if (searchParams.get("source")) router.replace(workspacePath(workspaceId, "sources"));
  }, [router, searchParams, workspaceId, workspacePath]);

  const {
    data: sources,
    error,
    isLoading,
    reload,
  } = useAsync((signal) => api.listSources(workspaceId, signal), [workspaceId]);

  const onUploaded = useCallback(() => reload(), [reload]);
  const { items, uploadDocuments, uploadRecording, uploadTranscript, dismiss } = useSourceUpload(
    workspaceId,
    onUploaded,
  );

  const jobIds = useMemo(() => items.flatMap((item) => (item.job ? [item.job.id] : [])), [items]);

  const onSettled = useCallback(
    (job: ProcessingJob) => {
      reload();

      if (job.status === "failed") {
        toast.error("소스 처리에 실패했습니다.");
        return;
      }

      toast.success("분석이 끝났습니다. Timeline에 반영됐습니다.", {
        action: {
          label: "Timeline 보기",
          onClick: () => router.push(workspacePath(workspaceId, "timeline")),
        },
      });
    },
    [reload, router, workspaceId, workspacePath],
  );

  const jobs = useJobPolling(jobIds, onSettled);

  return (
    <>
      <PageHeader title="소스" description="회의 녹음과 문서를 올리고 처리 상태를 확인합니다." />

      <Tabs defaultValue="document">
        <TabsList>
          <TabsTrigger value="document" disabled={meetingBusy}>
            문서 업로드
          </TabsTrigger>
          <TabsTrigger value="meeting">회의 녹음</TabsTrigger>
        </TabsList>

        <TabsContent value="document" className="mt-4">
          <UploadDropzone onFilesSelected={uploadDocuments} />
        </TabsContent>

        <TabsContent value="meeting" className="mt-4">
          <MeetingCapture
            onAudio={uploadRecording}
            onTranscript={uploadTranscript}
            onBusyChange={setMeetingBusy}
          />
        </TabsContent>
      </Tabs>

      <UploadQueue items={items} jobs={jobs} onDismiss={dismiss} className="mt-4" />

      <section className="mt-10">
        <h2 className="mb-3 text-lg font-semibold">올라온 소스</h2>

        {isLoading ? (
          <ListSkeleton count={2} className="h-20" />
        ) : error ? (
          <ErrorState error={error} onRetry={reload} />
        ) : sources && sources.length > 0 ? (
          <SourceList sources={sources} onOpen={(sourceId) => setViewer({ sourceId })} />
        ) : (
          <EmptyState
            title="아직 올라온 소스가 없습니다"
            description="위에서 문서를 올리거나 회의를 녹음해 맥락을 쌓아보세요."
          />
        )}
      </section>

      <SourceViewer
        sourceId={viewer?.sourceId}
        highlightChunkId={viewer?.chunkId}
        onClose={closeViewer}
      />
    </>
  );
}
