"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Eye, EyeOff, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/api/context";
import type { ApiKeyValidation, LlmProvider } from "@/lib/api";
import { providerKeyPlaceholder } from "@/lib/api/providers";
import { cn } from "@/lib/utils";
import { toUserMessage } from "@/lib/api/error-message";

export type ApiKeyFieldProps = {
  id: string;
  provider: LlmProvider;
  authMode?: "apiKey" | "optionalApiKey" | "none";
  baseUrl?: string;
  value: string;
  onChange: (value: string) => void;
  /** 검증 결과가 바뀔 때마다 알려줍니다. 유효하지 않으면 undefined입니다. */
  onValidated?: (result: ApiKeyValidation | undefined, validatedKey?: string) => void;
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
  authMode = "apiKey",
  baseUrl,
  value,
  onChange,
  onValidated,
  disabled = false,
}: ApiKeyFieldProps) {
  const [isRevealed, setIsRevealed] = useState(false);
  const api = useApi();
  const [isChecking, setIsChecking] = useState(false);
  const [result, setResult] = useState<ApiKeyValidation>();

  const validatedRef = useRef(onValidated);
  validatedRef.current = onValidated;

  // 통과한 결과에는 검증한 키도 함께 알려줍니다. 호출부가 "지금 이 키는 확인됐다"를
  // 기준으로 모델 목록을 받아오게 하려는 것입니다(타이핑 중인 키로는 요청하지 않습니다).
  const publish = useCallback((next: ApiKeyValidation | undefined, key?: string) => {
    setResult(next);
    if (next?.valid) validatedRef.current?.(next, key);
    else validatedRef.current?.(undefined, undefined);
  }, []);

  // 입력이 멈춘 뒤에만 검증해 타이핑 중 불필요한 호출을 막습니다.
  useEffect(() => {
    const key = authMode === "none" ? "" : value.trim();
    setIsChecking(false);
    publish(undefined);
    if ((authMode === "apiKey" && !key) || (authMode === "optionalApiKey" && !baseUrl?.trim())) {
      return;
    }

    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setIsChecking(true);
      try {
        const validation = await api.validateApiKey({ provider, apiKey: key, ...(baseUrl ? { baseUrl: baseUrl.trim() } : {}) }, controller.signal);
        if (!controller.signal.aborted) publish(validation, key);
      } catch (error) {
        if (controller.signal.aborted) return;
        publish({
          valid: false,
          message: toUserMessage(error, "키를 확인하지 못했습니다."),
        });
      } finally {
        if (!controller.signal.aborted) setIsChecking(false);
      }
    }, authMode === "none" ? 0 : 600);

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [value, provider, authMode, baseUrl, publish, api]);

  return (
    <div className="space-y-1.5">
      {authMode !== "none" && <div className="relative">
        <Input
          id={id}
          type={isRevealed ? "text" : "password"}
          value={value}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
          placeholder={providerKeyPlaceholder(provider)}
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
      </div>}

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
            {authMode === "optionalApiKey" ? "Ollama 서버 연결을 확인하는 중…" : authMode === "none" ? "서버의 로컬 연결을 확인하는 중…" : "키를 확인하는 중…"}
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
          authMode === "optionalApiKey"
            ? "키가 필요 없는 서버라면 비워 두세요. 입력한 키는 암호화해 저장하며 다시 표시하지 않습니다."
            : authMode === "none" ? "서버에서 관리하는 로컬 연결입니다. 주소나 키를 입력하지 않습니다." : "키는 암호화해 저장되며 저장 후에는 다시 표시되지 않습니다."
        )}
      </p>
    </div>
  );
}
