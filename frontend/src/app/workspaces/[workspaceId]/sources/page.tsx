"use client";

import { use, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RecordingControls } from "@/features/source-ingestion/components/recording-controls";
import { SourceList } from "@/features/source-ingestion/components/source-list";
import { UploadDropzone } from "@/features/source-ingestion/components/upload-dropzone";
import { UploadQueue } from "@/features/source-ingestion/components/upload-queue";
import { useAudioRecorder } from "@/features/source-ingestion/hooks/use-audio-recorder";
import { useJobPolling } from "@/features/source-ingestion/hooks/use-job-polling";
import { useSourceUpload } from "@/features/source-ingestion/hooks/use-source-upload";
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
  const { items, uploadDocuments, uploadRecording, dismiss } = useSourceUpload(
    workspaceId,
    onUploaded,
  );

  // 녹음이 끝나면 사용자가 따로 누르지 않아도 바로 업로드가 시작됩니다.
  const onRecorded = useCallback(
    (audio: Blob, durationSeconds: number) => void uploadRecording(audio, durationSeconds),
    [uploadRecording],
  );
  const recorder = useAudioRecorder({ onComplete: onRecorded });

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
    [reload, router, workspaceId],
  );

  const jobs = useJobPolling(jobIds, onSettled);

  return (
    <>
      <PageHeader title="소스" description="회의 녹음과 문서를 올리고 처리 상태를 확인합니다." />

      <Tabs defaultValue="document">
        <TabsList>
          <TabsTrigger value="document">문서 업로드</TabsTrigger>
          <TabsTrigger value="meeting">회의 녹음</TabsTrigger>
        </TabsList>

        <TabsContent value="document" className="mt-4">
          <UploadDropzone onFilesSelected={uploadDocuments} />
        </TabsContent>

        <TabsContent value="meeting" className="mt-4">
          <RecordingControls
            status={recorder.status}
            elapsedSeconds={recorder.elapsedSeconds}
            errorMessage={recorder.errorMessage}
            onStart={() => void recorder.start()}
            onStop={recorder.stop}
          />
          <p className="mt-2 text-xs text-muted-foreground">
            정지하면 녹음이 자동으로 올라가고 음성 인식부터 분석까지 이어집니다.
          </p>
        </TabsContent>
      </Tabs>

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
            아직 올라온 소스가 없습니다. 문서나 회의 녹음을 올려 맥락을 쌓아보세요.
          </div>
        )}
      </section>
    </>
  );
}
