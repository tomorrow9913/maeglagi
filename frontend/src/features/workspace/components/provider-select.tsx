"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AiProvider, LlmProvider } from "@/lib/api";

export function ProviderSelect({
  id,
  value,
  onChange,
  providers,
  disabled = false,
}: {
  id: string;
  value: LlmProvider;
  onChange: (value: LlmProvider) => void;
  providers: readonly AiProvider[];
  disabled?: boolean;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={id} disabled={disabled} className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {providers.map((provider) => (
          <SelectItem key={provider.id} value={provider.id}>
            {provider.displayName}
            {provider.configured ? " (설정됨)" : ""}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
