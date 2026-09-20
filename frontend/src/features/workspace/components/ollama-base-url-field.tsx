"use client";

import type { ReactNode } from "react";

import { Input } from "@/components/ui/input";

/**
 * Ollama 서버 주소 입력란입니다.
 *
 * Ollama는 확인 대상이 키가 아니라 이 주소이므로, 연결 확인 결과(`children`)와
 * `aria-invalid`를 이 입력란에 붙입니다.
 */
export function OllamaBaseUrlField({
  id,
  value,
  onChange,
  disabled = false,
  invalid,
  children,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  invalid?: boolean;
  /** 입력란 바로 아래에 둘 연결 확인 상태. `${id}-status`를 id로 써야 합니다. */
  children?: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        Ollama 서버 주소
      </label>
      <Input
        id={id}
        type="url"
        inputMode="url"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="https://ollama.example.com"
        autoComplete="url"
        spellCheck={false}
        disabled={disabled}
        maxLength={2048}
        required
        aria-invalid={invalid || undefined}
        aria-describedby={children ? `${id}-status ${id}-help` : `${id}-help`}
      />
      {children}
      <p id={`${id}-help`} className="text-xs text-muted-foreground">
        맥락이 서버가 이 주소로 접속합니다. 내 컴퓨터의 localhost는 서버에서 보이지 않으니, 밖에서
        접속되는 https 주소를 입력해 주세요.
      </p>
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer select-none underline-offset-4 hover:underline">
          직접 설치해 쓰는 경우
        </summary>
        <p className="mt-1 leading-relaxed">
          맥락이를 직접 설치했고 관리자가 내부 주소를 허용했다면{" "}
          <code className="font-mono">http://ollama:11434</code>나{" "}
          <code className="font-mono">http://host.docker.internal:11434</code>처럼 서버에서 보이는 내부
          주소를 쓸 수 있어요.
        </p>
      </details>
    </div>
  );
}
