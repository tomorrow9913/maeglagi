import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * 보이는 라벨이 붙은 입력 한 칸입니다.
 *
 * placeholder만 두면 입력을 시작하는 순간 무엇을 적는 칸인지 사라집니다. 라벨에는
 * 필수 여부를 `(필수)`/`(선택)`로 함께 적습니다.
 */
export function FormField({
  htmlFor,
  label,
  required = false,
  error,
  errorId,
  className,
  children,
}: {
  htmlFor: string;
  label: string;
  required?: boolean;
  /** 입력 아래에 보여줄 오류 문구 */
  error?: string;
  /** 입력의 `aria-describedby`와 맞출 id */
  errorId?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("space-y-1", className)}>
      <label htmlFor={htmlFor} className="block text-sm font-medium">
        {label}{" "}
        <span className="font-normal text-muted-foreground">({required ? "필수" : "선택"})</span>
      </label>
      {children}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

const controlClass =
  "w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 text-base transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 md:text-sm";

/** 목표·설명처럼 긴 글을 받는 칸. `Input`과 같은 테두리·포커스 규칙을 씁니다. */
export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(controlClass, "min-h-20 resize-y py-1.5 leading-relaxed", className)}
      {...props}
    />
  );
}

/** 기본 `select`. `Input`과 높이·테두리를 맞춥니다. */
export function NativeSelect({ className, ...props }: ComponentProps<"select">) {
  return <select className={cn(controlClass, "h-8", className)} {...props} />;
}
