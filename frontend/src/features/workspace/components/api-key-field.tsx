"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, Eye, EyeOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useApi } from "@/lib/api/context";
import type { ApiKeyValidation, LlmProvider } from "@/lib/api";
import { toUserMessage } from "@/lib/api/error-message";
import { providerKeyPlaceholder } from "@/lib/api/providers";
import { cn } from "@/lib/utils";

import {
  isTypingScheme,
  normalizeValidationCopy,
  ollamaFailureMessage,
  ollamaUrlShapeError,
} from "../lib/ollama-url";
import { OllamaBaseUrlField } from "./ollama-base-url-field";

export type ApiKeyFieldProps = {
  id: string;
  provider: LlmProvider;
  authMode?: "apiKey" | "optionalApiKey" | "none";
  /** 키 입력란의 라벨. 입력란이 없는 방식(`none`)에서는 제목으로만 보여줍니다. */
  label: string;
  value: string;
  onChange: (value: string) => void;
  /**
   * 서버 주소가 필요한 공급자(Ollama)의 주소 입력란. 넘기면 이 컴포넌트가 주소 입력란을 함께
   * 그리고, 연결 확인 결과를 키가 아니라 주소 입력란에 붙입니다.
   */
  baseUrlField?: { id: string; value: string; onChange: (value: string) => void };
  /** 저장된 키를 유지·제거하는 수정 모드. 키 입력란과 입력 중 확인을 끄고 저장할 때 서버가 확인합니다. */
  keyInputHidden?: boolean;
  /** 검증 결과가 바뀔 때마다 알려줍니다. 유효하지 않으면 undefined입니다. */
  onValidated?: (result: ApiKeyValidation | undefined, validatedKey?: string) => void;
  disabled?: boolean;
  /** 주소 입력란과 키 입력란 사이에 둘 내용(기존 키 유지·교체·제거 선택) */
  children?: ReactNode;
};

/**
 * BYOK 연결 입력란입니다. API key와, Ollama라면 서버 주소를 받습니다.
 *
 * 입력값은 기본적으로 가려지고, 눈 아이콘으로 잠깐 확인만 할 수 있습니다.
 * 입력이 멈추면 서버에 검증을 요청해 결과를 확인 대상(키 또는 주소) 아래에 보여줍니다.
 */
export function ApiKeyField({
  id,
  provider,
  authMode = "apiKey",
  label,
  value,
  onChange,
  baseUrlField,
  keyInputHidden = false,
  onValidated,
  disabled = false,
  children,
}: ApiKeyFieldProps) {
  const [isRevealed, setIsRevealed] = useState(false);
  const api = useApi();
  const [isChecking, setIsChecking] = useState(false);
  const [result, setResult] = useState<ApiKeyValidation>();
  // 일시적인 실패 뒤에 입력을 지웠다 다시 치지 않고도 확인을 다시 걸 수 있게 합니다.
  const [attempt, setAttempt] = useState(0);
  const recheckNow = useRef(false);

  const validatedRef = useRef(onValidated);
  validatedRef.current = onValidated;

  const baseUrl = baseUrlField?.value;
  const checksAddress = baseUrlField !== undefined;
  // 주소 모양이 맞기 전에는 서버에 묻지 않습니다. `https://`까지만 친 상태로 오류가 뜨는 것을 막습니다.
  const shapeError = checksAddress ? ollamaUrlShapeError(baseUrl ?? "") : undefined;

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
    const address = baseUrl?.trim();
    setIsChecking(false);
    publish(undefined);
    if (
      keyInputHidden ||
      (authMode === "apiKey" && !key) ||
      (checksAddress && (!address || shapeError !== undefined))
    ) {
      return;
    }

    // "다시 확인"은 입력이 멈추기를 기다릴 이유가 없으므로 바로 확인합니다.
    const wait = authMode === "none" || recheckNow.current ? 0 : 600;
    recheckNow.current = false;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setIsChecking(true);
      try {
        const validation = await api.validateApiKey(
          { provider, apiKey: key, ...(address ? { baseUrl: address } : {}) },
          controller.signal,
        );
        if (controller.signal.aborted) return;
        publish(
          validation.valid
            ? validation
            : {
                ...validation,
                message: checksAddress
                  ? ollamaFailureMessage(validation, address ?? "")
                  : normalizeValidationCopy(validation.message, "API key를 확인해 주세요."),
              },
          key,
        );
      } catch (error) {
        if (controller.signal.aborted) return;
        publish({
          valid: false,
          message: toUserMessage(
            error,
            checksAddress ? "Ollama 서버 연결을 확인하지 못했습니다." : "API key를 확인하지 못했습니다.",
          ),
        });
      } finally {
        if (!controller.signal.aborted) setIsChecking(false);
      }
    }, wait);

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [value, provider, authMode, baseUrl, checksAddress, shapeError, keyInputHidden, publish, api, attempt]);

  const statusId = `${baseUrlField ? baseUrlField.id : id}-status`;
  const idleHint = checksAddress
    ? shapeError
    : authMode === "none"
      ? "서버에서 관리하는 연결입니다. 주소나 API key를 입력하지 않습니다."
      : "API key는 암호화해 저장하며 저장한 뒤에는 다시 보여주지 않습니다.";

  const showsShapeWarning = Boolean(shapeError) && !isTypingScheme(baseUrl ?? "");
  const status = (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <p
        id={statusId}
        aria-live="polite"
        className={cn(
          "flex items-start gap-1.5 text-xs",
          isChecking
            ? "text-muted-foreground"
            : result?.valid
              ? "text-success"
              : result
                ? "text-destructive"
                : showsShapeWarning
                  ? "text-warning"
                  : "text-muted-foreground",
        )}
      >
        {isChecking ? (
          <>
            <Spinner className="mt-0.5 size-3" />
            {checksAddress
              ? "Ollama 서버 연결을 확인하고 있어요"
              : authMode === "none"
                ? "서버의 연결을 확인하고 있어요"
                : "API key를 확인하고 있어요"}
          </>
        ) : result?.valid ? (
          <>
            <CheckCircle2 className="mt-0.5 size-3 shrink-0" aria-hidden />
            {normalizeValidationCopy(result.message, "연결을 확인했습니다.")}
          </>
        ) : result ? (
          <>
            <AlertCircle className="mt-0.5 size-3 shrink-0" aria-hidden />
            {result.message}
          </>
        ) : (
          idleHint
        )}
      </p>
      {result && !result.valid && !isChecking ? (
        <Button
          type="button"
          variant="outline"
          size="xs"
          disabled={disabled}
          onClick={() => {
            recheckNow.current = true;
            setAttempt((current) => current + 1);
          }}
        >
          다시 확인
        </Button>
      ) : null}
    </div>
  );

  const showKeyInput = authMode !== "none" && !keyInputHidden;

  return (
    <div className="space-y-4">
      {baseUrlField ? (
        <OllamaBaseUrlField
          id={baseUrlField.id}
          value={baseUrlField.value}
          disabled={disabled}
          invalid={result ? !result.valid : undefined}
          onChange={baseUrlField.onChange}
        >
          {status}
        </OllamaBaseUrlField>
      ) : null}

      {children}

      {showKeyInput ? (
        <div className="space-y-1.5">
          <label htmlFor={id} className="text-sm font-medium">
            {label}
          </label>
          <div className="relative">
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
              aria-describedby={checksAddress ? `${id}-help` : statusId}
              aria-invalid={!checksAddress && result ? !result.valid : undefined}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute top-1/2 right-1 size-7 -translate-y-1/2"
              aria-label={isRevealed ? "API key 가리기" : "API key 보기"}
              onClick={() => setIsRevealed((shown) => !shown)}
            >
              {isRevealed ? (
                <EyeOff className="size-3.5" aria-hidden />
              ) : (
                <Eye className="size-3.5" aria-hidden />
              )}
            </Button>
          </div>
          {checksAddress ? (
            <p id={`${id}-help`} className="text-xs text-muted-foreground">
              API key가 필요 없는 서버라면 비워 두어도 됩니다. 입력한 API key는 암호화해 저장하며 다시
              보여주지 않습니다.
            </p>
          ) : (
            status
          )}
        </div>
      ) : !checksAddress && !keyInputHidden ? (
        <div className="space-y-1.5">
          <p className="text-sm font-medium">{label}</p>
          {status}
        </div>
      ) : null}
    </div>
  );
}
