"use client";

import { useEffect, useRef } from "react";
import { FileText, Loader2, Mic } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useAsync } from "@/hooks/use-async";
import { useApi } from "@/lib/api/context";
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

export function SourceViewer({
  sourceId,
  highlightChunkId,
  onClose,
}: {
  sourceId: string | undefined;
  highlightChunkId?: string;
  onClose: () => void;
}) {
  const highlightRef = useRef<HTMLLIElement>(null);
  const api = useApi();

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
                      <span className="mb-1 block font-mono text-xs text-muted-foreground">
                        {formatTimestamp(chunk.startSeconds)}
                        {chunk.endSeconds != null ? ` – ${formatTimestamp(chunk.endSeconds)}` : ""}
                      </span>
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
