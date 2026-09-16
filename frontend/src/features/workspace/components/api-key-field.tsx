"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Eye, EyeOff, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { ApiKeyValidation, LlmProvider } from "@/lib/api";
import { cn } from "@/lib/utils";

export type ApiKeyFieldProps = {
  id: string;
  provider: LlmProvider;
  value: string;
  onChange: (value: string) => void;
  /** 검증 결과가 바뀔 때마다 알려줍니다. 유효하지 않으면 undefined입니다. */
  onValidated?: (result: ApiKeyValidation | undefined) => void;
  disabled?: boolean;
};

/**
 * BYOK API key 입력란입니다.
 *
 * 입력값은 기본적으로 가려지고, 눈 아이콘으로 잠깐 확인만 할 수 있습니다.
 * 입력이 멈추면 서버에 검증을 요청해 결과를 그 자리에서 보여줍니다.
 */
export function ApiKeyField({
  id,
  provider,
  value,
  onChange,
  onValidated,
  disabled = false,
}: ApiKeyFieldProps) {
  const [isRevealed, setIsRevealed] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [result, setResult] = useState<ApiKeyValidation>();

  const validatedRef = useRef(onValidated);
  validatedRef.current = onValidated;

  const publish = useCallback((next: ApiKeyValidation | undefined) => {
    setResult(next);
    validatedRef.current?.(next?.valid ? next : undefined);
  }, []);

  // 입력이 멈춘 뒤에만 검증해 타이핑 중 불필요한 호출을 막습니다.
  useEffect(() => {
    const key = value.trim();
    if (!key) {
      publish(undefined);
      return;
    }

    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setIsChecking(true);
      try {
        const validation = await api.validateApiKey({ provider, apiKey: key }, controller.signal);
        if (!controller.signal.aborted) publish(validation);
      } catch (error) {
        if (controller.signal.aborted) return;
        publish({
          valid: false,
          message: error instanceof Error ? error.message : "키를 확인하지 못했습니다.",
        });
      } finally {
        if (!controller.signal.aborted) setIsChecking(false);
      }
    }, 600);

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [value, provider, publish]);

  return (
    <div className="space-y-1.5">
      <div className="relative">
        <Input
          id={id}
          type={isRevealed ? "text" : "password"}
          value={value}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
          placeholder={
            provider === "anthropic" ? "sk-ant-..." : provider === "nvidia" ? "nvapi-..." : "sk-..."
          }
          onChange={(event) => onChange(event.target.value)}
          className="pr-10 font-mono"
          aria-describedby={`${id}-status`}
          aria-invalid={result ? !result.valid : undefined}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="absolute top-1/2 right-1 size-7 -translate-y-1/2"
          aria-label={isRevealed ? "키 가리기" : "키 보기"}
          onClick={() => setIsRevealed((shown) => !shown)}
        >
          {isRevealed ? (
            <EyeOff className="size-3.5" aria-hidden />
          ) : (
            <Eye className="size-3.5" aria-hidden />
          )}
        </Button>
      </div>

      <p
        id={`${id}-status`}
        aria-live="polite"
        className={cn(
          "flex items-center gap-1.5 text-xs",
          result?.valid ? "text-success" : result ? "text-destructive" : "text-muted-foreground",
        )}
      >
        {isChecking ? (
          <>
            <Loader2 className="size-3 animate-spin" aria-hidden />
            키를 확인하는 중…
          </>
        ) : result?.valid ? (
          <>
            <CheckCircle2 className="size-3" aria-hidden />
            {result.message}
          </>
        ) : result ? (
          <>
            <AlertCircle className="size-3" aria-hidden />
            {result.message}
          </>
        ) : (
          "키는 암호화해 저장되며 저장 후에는 다시 표시되지 않습니다."
        )}
      </p>
    </div>
  );
}
