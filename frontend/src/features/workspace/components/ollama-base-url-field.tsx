"use client";

import { Input } from "@/components/ui/input";

export function OllamaBaseUrlField({
  id,
  value,
  onChange,
  disabled = false,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">Ollama 서버 주소</label>
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
        required
      />
      <p className="text-xs text-muted-foreground">
        SaaS에서는 외부에서 접근 가능한 HTTPS 주소를 입력하세요. 자체 서버에서는 배포 정책에 따라
        내부망 또는 Docker 주소를 사용할 수 있습니다. localhost는 브라우저가 아닌 API 서버를 가리킵니다.
      </p>
    </div>
  );
}
