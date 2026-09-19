import { AlertCircle, Check, Loader2 } from "lucide-react";

import { Progress } from "@/components/ui/progress";
import type { ProcessingJob } from "@/lib/api";
import { cn } from "@/lib/utils";

import { stageIndexOf, stageLabel, stagesFor } from "../lib/processing-stages";

/**
 * 업로드한 소스가 어느 단계까지 처리됐는지 보여줍니다.
 *
 * 회의 녹음은 음성 인식 단계가 하나 더 있어 종류에 따라 단계 수가 다릅니다.
 */
export function ProcessingTracker({ job, className }: { job: ProcessingJob; className?: string }) {
  if (job.status === "awaiting_agent") {
    return <p role="status" className={cn("mt-2 text-xs text-muted-foreground", className)}>업로드된 소스를 에이전트가 처리할 때까지 기다립니다. 분석은 자동으로 시작되지 않습니다.</p>;
  }
  const stages = stagesFor(job.sourceKind, job.transcriptSource, job.analysisMode);
  const currentIndex = stageIndexOf(job.sourceKind, job.stage, job.transcriptSource, job.analysisMode);
  const failed = job.status === "failed";

  return (
    <div className={cn("space-y-2", className)}>
      <Progress
        value={job.progress * 100}
        className={cn("h-1", failed && "[&>*]:bg-destructive")}
      />

      <ol className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {stages.map((stage, index) => {
          const isDone = index < currentIndex || job.status === "succeeded";
          const isCurrent = index === currentIndex && job.status !== "succeeded";

          return (
            <li key={stage} className="flex items-center gap-2">
              {index > 0 ? <span className="text-xs text-muted-foreground/40">›</span> : null}
              <span
                className={cn(
                  "flex items-center gap-1 text-xs",
                  isDone && "text-success",
                  isCurrent && !failed && "font-medium text-foreground",
                  isCurrent && failed && "font-medium text-destructive",
                  !isDone && !isCurrent && "text-muted-foreground",
                )}
              >
                {isDone ? (
                  <Check className="size-3" aria-hidden />
                ) : isCurrent && failed ? (
                  <AlertCircle className="size-3" aria-hidden />
                ) : isCurrent && job.status !== "awaiting_review" ? (
                  <Loader2 className="size-3 animate-spin" aria-hidden />
                ) : null}
                {stageLabel[stage]}
              </span>
            </li>
          );
        })}
      </ol>

      {failed && job.errorMessage ? (
        <p className="text-xs text-destructive">{job.errorMessage}</p>
      ) : null}
    </div>
  );
}
