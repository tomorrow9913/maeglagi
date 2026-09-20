"use client";

import { Suspense, use, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/common/state-views";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MeetingCapture } from "@/features/source-ingestion/components/meeting-capture";
import { MeetingReviewDialog } from "@/features/source-ingestion/components/meeting-review-dialog";
import { SourceList } from "@/features/source-ingestion/components/source-list";
import { SourceViewer } from "@/features/source-ingestion/components/source-viewer";
import { SourceFileUpload } from "@/features/source-ingestion/components/source-file-upload";
import { UploadQueue } from "@/features/source-ingestion/components/upload-queue";
import { useJobEvents } from "@/features/source-ingestion/hooks/use-job-events";
import { useLiveSources } from "@/features/source-ingestion/hooks/use-live-sources";
import { useSourceUpload } from "@/features/source-ingestion/hooks/use-source-upload";
import { useDemoMode, useWorkspacePath } from "@/lib/api/context";
import type { ProcessingJob } from "@/lib/api";
import { CONNECTION_DELAYED, RECORDING_BLOCKS_FILE_UPLOAD, settledToast } from "@/features/source-ingestion/lib/copy";
import { sourcePresentation } from "@/features/source-ingestion/lib/source-presentation";

export default function SourcesPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);

  return <SourcesView workspaceId={workspaceId} />;
}

export function SourcesView({ workspaceId }: { workspaceId: string }) {
  return <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}><SourcesContent workspaceId={workspaceId} /></Suspense>;
}

function SourcesContent({ workspaceId }: { workspaceId: string }) {
  const isDemo = useDemoMode();
  const router = useRouter();
  const workspacePath = useWorkspacePath();
  const [meetingBusy, setMeetingBusy] = useState(false);
  const [reviewSourceId, setReviewSourceId] = useState<string>();
  const [restartKey, setRestartKey] = useState(0);
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
  useEffect(() => {
    if (isDemo) return;
    const sourceId = searchParams.get("review");
    if (sourceId) setReviewSourceId(sourceId);
  }, [isDemo, searchParams]);

  const closeViewer = useCallback(() => {
    setViewer(undefined);
    // 쿼리를 지워 새로고침해도 다시 열리지 않게 합니다.
    if (searchParams.get("source")) router.replace(workspacePath(workspaceId, "sources"));
  }, [router, searchParams, workspaceId, workspacePath]);

  const { sources, progress, error, isLoading, reload, connection: listConnection } = useLiveSources(workspaceId);

  const { items, uploadDocuments, uploadRecording, uploadTranscript, cancel, retry, dismiss } = useSourceUpload(
    workspaceId,
  );

  const onSettled = useCallback(
    (job: ProcessingJob) => {
      // 문구는 Ask의 업로드 창과 같은 모듈에서 가져옵니다. 올린 파일 이름을 함께 알려줍니다.
      const title = items.find((item) => item.job?.sourceId === job.sourceId)?.fileName;
      const copy = settledToast(job, title, "sources");
      if (!copy) return;
      const onClick = copy.action?.kind === "review"
        ? () => setReviewSourceId(job.sourceId)
        : copy.action?.kind === "timeline"
          ? () => router.push(workspacePath(workspaceId, "timeline"))
          : undefined;
      toast[copy.tone](copy.message, copy.action && onClick ? { action: { label: copy.action.label, onClick } } : undefined);
    },
    [items, router, workspaceId, workspacePath],
  );

  const { jobs, connection: queueConnection } = useJobEvents(workspaceId, items.flatMap((item) => item.job ? [item.job] : []), onSettled, restartKey);
  // 큐가 이미 같은 안내를 보여주고 있으면 목록 위에는 다시 띄우지 않습니다.
  const queueShowsDelay = queueConnection === "reconnecting" && items.some((item) => {
    const job = item.job ? (jobs[item.job.id] ?? item.job) : undefined;
    return job?.status === "queued" || job?.status === "enqueue_pending" || job?.status === "processing";
  });

  return (
    <>
      <PageHeader title="소스" description={isDemo ? "공개 데모의 회의와 문서를 읽기 전용으로 살펴봅니다." : "회의 녹음과 문서를 올리고 처리 상태를 확인합니다."} />

      {!isDemo && <p className="mb-4 text-xs text-muted-foreground">이 화면에서 올린 파일은 서비스 AI 연결로 자동 처리합니다. 내 에이전트로 처리하려면 <a href="/account/mcp" className="text-primary underline-offset-2 hover:underline">계정 MCP 연결</a>을 사용해 주세요.</p>}

      {!isDemo && <Tabs defaultValue="document">
        <TabsList>
          <TabsTrigger value="document" disabled={meetingBusy}>
            문서·녹음 파일
          </TabsTrigger>
          <TabsTrigger value="meeting">회의 녹음</TabsTrigger>
        </TabsList>
        {meetingBusy && <p className="mt-2 text-xs text-muted-foreground">{RECORDING_BLOCKS_FILE_UPLOAD}</p>}

        <TabsContent value="document" className="mt-4">
          <SourceFileUpload workspaceId={workspaceId} onDocuments={uploadDocuments} onAudio={uploadRecording} />
        </TabsContent>

        <TabsContent value="meeting" className="mt-4">
          <MeetingCapture
            workspaceId={workspaceId}
            onAudio={uploadRecording}
            onTranscript={uploadTranscript}
            onBusyChange={setMeetingBusy}
          />
        </TabsContent>
      </Tabs>}

      {!isDemo && <UploadQueue items={items} jobs={jobs} connection={queueConnection} onDismiss={dismiss} onCancel={cancel} onRetry={retry} onReview={setReviewSourceId} onRefresh={reload} className="mt-4" />}

      <section className="mt-10">
        <h2 className="mb-3 text-lg font-semibold">올라온 소스</h2>
        {listConnection === "reconnecting" && !queueShowsDelay && (
          <p role="status" className="mb-3 text-xs text-muted-foreground">{CONNECTION_DELAYED}</p>
        )}

        {isLoading ? (
          <ListSkeleton count={2} className="h-20" />
        ) : error && !sources ? (
          <ErrorState error={error} onRetry={reload} />
        ) : sources && sources.length > 0 ? (
          <SourceList sources={sources} progress={progress} onOpen={(sourceId) => { const source = sources.find((item) => item.id === sourceId); if (!isDemo && source && sourcePresentation(source.status, source.kind).needsReview) setReviewSourceId(sourceId); else setViewer({ sourceId }); }} />
        ) : (
          <EmptyState
            title="아직 올라온 소스가 없습니다"
            description={isDemo ? "공개할 소스가 없습니다." : "위에서 문서를 올리거나 회의를 녹음해 맥락을 쌓아보세요."}
          />
        )}
      </section>

      <SourceViewer
        workspaceId={workspaceId}
        sourceId={viewer?.sourceId}
        highlightChunkId={viewer?.chunkId}
        onClose={closeViewer}
      />
      {!isDemo && <MeetingReviewDialog workspaceId={workspaceId} sourceId={reviewSourceId} onClose={() => { setReviewSourceId(undefined); reload(); if (searchParams.get("review")) router.replace(workspacePath(workspaceId, "sources")); }} onConfirmed={() => { setRestartKey((value) => value + 1); reload(); }} />}
    </>
  );
}
