"use client";

import { useCallback, useRef, useState } from "react";
import { Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type UploadDropzoneProps = {
  /** 허용 확장자. 기본값은 PoC 범위인 PDF/DOCX/TXT/MD 입니다. */
  accept?: string;
  multiple?: boolean;
  disabled?: boolean;
  onFilesSelected: (files: File[]) => void;
};

/**
 * 드래그 앤 드롭 + 파일 선택을 함께 받는 업로드 영역입니다.
 *
 * 이 컴포넌트는 파일을 고르는 일까지만 맡습니다. 실제 업로드 요청과
 * 진행률은 Day 2 문서 업로드 작업에서 상위 컴포넌트가 담당합니다.
 */
export function UploadDropzone({
  accept = ".pdf,.docx,.txt,.md",
  multiple = true,
  disabled = false,
  onFilesSelected,
}: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const emit = useCallback(
    (fileList: FileList | null) => {
      const files = Array.from(fileList ?? []);
      if (files.length > 0) onFilesSelected(files);
    },
    [onFilesSelected],
  );

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragging(false);
        if (!disabled) emit(event.dataTransfer.files);
      }}
      className={cn(
        "flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-12 text-center transition-colors",
        isDragging ? "border-primary bg-primary/5" : "border-border bg-card",
        disabled && "pointer-events-none opacity-60",
      )}
    >
      <Upload className="size-6 text-muted-foreground" aria-hidden />
      <div className="space-y-1">
        <p className="text-sm font-medium">파일을 여기에 끌어다 놓으세요</p>
        <p className="text-xs text-muted-foreground">PDF, DOCX, TXT, MD를 지원합니다.</p>
      </div>
      <Button type="button" variant="outline" size="sm" onClick={() => inputRef.current?.click()}>
        파일 선택
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        className="hidden"
        onChange={(event) => {
          emit(event.target.files);
          event.target.value = "";
        }}
      />
    </div>
  );
}
