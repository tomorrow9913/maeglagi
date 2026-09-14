"use client";

import { useCallback, useRef, useState } from "react";
import { Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import {
  ACCEPTED_DOCUMENT_EXTENSIONS,
  MAX_DOCUMENT_BYTES,
  formatBytes,
} from "../lib/validate-file";

export type UploadDropzoneProps = {
  /** 허용 확장자. 기본값은 PoC 범위인 PDF/DOCX/TXT/MD 입니다. */
  accept?: string;
  /** 드롭존 아래에 보여줄 안내 문구. 기본값은 문서 업로드 기준입니다. */
  hint?: string;
  multiple?: boolean;
  disabled?: boolean;
  onFilesSelected: (files: File[]) => void;
};

/**
 * 드래그 앤 드롭 + 파일 선택을 함께 받는 업로드 영역입니다.
 *
 * 이 컴포넌트는 파일을 고르는 일까지만 맡습니다. 포맷·크기 검증과 업로드
 * 요청은 `useDocumentUpload`가 처리합니다.
 */
export function UploadDropzone({
  accept = ACCEPTED_DOCUMENT_EXTENSIONS.join(","),
  multiple = true,
  disabled = false,
  hint = `${ACCEPTED_DOCUMENT_EXTENSIONS.join(", ")} · 최대 ${formatBytes(MAX_DOCUMENT_BYTES)}`,
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
        <p className="text-xs text-muted-foreground">{hint}</p>
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
