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
import { api } from "@/lib/api";
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
            <ol className="space-y-3">
              {data.chunks.map((chunk) => {
                const isHighlighted = chunk.id === highlightChunkId;
                return (
                  <li
                    key={chunk.id}
                    ref={isHighlighted ? highlightRef : undefined}
                    className={cn(
                      "rounded-lg border p-3 text-sm leading-relaxed transition-colors",
                      isHighlighted
                        ? "border-primary/40 bg-primary/5"
                        : "border-transparent bg-muted/40",
                    )}
                  >
                    {chunk.startSeconds != null ? (
                      <span className="mb-1 block font-mono text-xs text-muted-foreground">
                        {formatTimestamp(chunk.startSeconds)}
                        {chunk.endSeconds != null ? ` – ${formatTimestamp(chunk.endSeconds)}` : ""}
                      </span>
                    ) : null}
                    {chunk.text}
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
