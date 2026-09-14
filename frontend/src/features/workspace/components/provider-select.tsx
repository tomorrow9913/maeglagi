"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { LlmProvider } from "@/lib/api";

const providerLabel: Record<LlmProvider, string> = {
  anthropic: "Anthropic (Claude)",
  openai: "OpenAI",
};

export function ProviderSelect({
  id,
  value,
  onChange,
  disabled = false,
}: {
  id: string;
  value: LlmProvider;
  onChange: (value: LlmProvider) => void;
  disabled?: boolean;
}) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as LlmProvider)}>
      <SelectTrigger id={id} disabled={disabled} className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {Object.entries(providerLabel).map(([key, label]) => (
          <SelectItem key={key} value={key}>
            {label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export { providerLabel };
