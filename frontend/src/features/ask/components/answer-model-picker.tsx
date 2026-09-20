"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAsync } from "@/hooks/use-async";
import { useApi, useWorkspacePath } from "@/lib/api/context";
import type { ModelOption, RoleModels } from "@/lib/api";
import { optionKey } from "@/features/workspace/lib/model-roles";
import { toUserMessage } from "@/lib/api/error-message";


export function AnswerModelPicker({
  workspaceId,
  isStreaming,
  onSavingChange,
}: {
  workspaceId: string;
  isStreaming: boolean;
  onSavingChange: (saving: boolean) => void;
}) {
  const api = useApi();
  const workspacePath = useWorkspacePath();
  const {
    data,
    error: loadError,
    isLoading,
    reload,
  } = useAsync((signal) => api.getWorkspaceModels(workspaceId, undefined, signal), [workspaceId]);
  const { data: providers } = useAsync((signal) => api.listProviders(signal), []);
  const { data: credentials } = useAsync((signal) => api.listAccountCredentials(signal), []);
  const [answer, setAnswer] = useState<RoleModels>();
  const [failedOption, setFailedOption] = useState<ModelOption>();
  const [saveError, setSaveError] = useState<string>();
  const [isSaving, setIsSaving] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const savingRef = useRef(false);

  useEffect(() => {
    setAnswer(data?.roles.find((role) => role.role === "answer"));
    setFailedOption(undefined);
    setSaveError(undefined);
  }, [data]);

  const providerName = (id: string) =>
    providers?.find((provider) => provider.id === id)?.displayName ?? id;
  const modelLabel = (option: ModelOption) => {
    const credential = credentials?.find((item) => item.id === option.credentialId);
    const connection = credential
      ? `${credential.label}${credential.baseUrl ? ` (${credential.baseUrl})` : ""}`
      : option.credentialId?.slice(0, 8);
    return `${providerName(option.provider)} · ${option.model}${connection ? ` · ${connection}` : ""}`;
  };
  const options = answer?.options ?? [];
  const selected = answer?.selected;
  const selectedAvailable =
    selected && options.some((option) => optionKey(option) === optionKey(selected));
  const visibleOptions = selected && !selectedAvailable ? [selected, ...options] : options;

  const save = async (option: ModelOption) => {
    if (
      savingRef.current ||
      isStreaming ||
      optionKey(option) === (selected && optionKey(selected))
    ) {
      return;
    }
    savingRef.current = true;
    setIsSaving(true);
    onSavingChange(true);
    setSaveError(undefined);
    setFailedOption(undefined);
    try {
      const next = await api.updateWorkspaceModels(workspaceId, { answer: option });
      setAnswer(next.roles.find((role) => role.role === "answer"));
    } catch (cause) {
      setFailedOption(option);
      setSaveError(toUserMessage(cause, "모델을 저장하지 못했습니다."));
    } finally {
      savingRef.current = false;
      setIsSaving(false);
      onSavingChange(false);
    }
  };

  return (
    <div className="mt-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span
          className={`min-w-0 break-words ${loadError || saveError ? "text-destructive" : ""}`}
          role={loadError || saveError ? "alert" : isLoading || isSaving ? "status" : undefined}
        >
          {loadError
            ? `모델 불러오기 실패: ${loadError.message}`
            : saveError
              ? `모델 저장 실패: ${saveError}`
              : isSaving
                ? "모델 저장 중…"
                : isLoading
                  ? "답변 모델을 불러오는 중…"
                  : `현재 사용 중: ${selected ? modelLabel(selected) : "선택된 모델 없음"}`}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          aria-expanded={isExpanded}
          aria-controls="ask-answer-model-settings"
          onClick={() => setIsExpanded((expanded) => !expanded)}
        >
          모델 선택
        </Button>
      </div>
      <section
        id="ask-answer-model-settings"
        className="mt-2 rounded-xl border border-border bg-card px-3 py-3 sm:px-4"
        aria-label="답변 모델"
        hidden={!isExpanded}
      >
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
          <label htmlFor="ask-answer-model" className="shrink-0 text-sm font-medium">
            답변 모델
          </label>
          <div className="min-w-0 flex-1">
            {isLoading ? (
              <p className="text-sm text-muted-foreground" role="status">
                모델을 불러오는 중…
              </p>
            ) : loadError ? (
              <div
                className="flex flex-wrap items-center gap-2 text-sm text-destructive"
                role="alert"
              >
                <span>{loadError.message}</span>
                <Button type="button" variant="outline" size="sm" onClick={reload}>
                  다시 시도
                </Button>
              </div>
            ) : options.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                사용 가능한 답변 모델이 없습니다.{" "}
                <Link
                  className="underline underline-offset-2"
                  href={workspacePath(workspaceId, "settings")}
                >
                  설정에서 AI 연결 등록
                </Link>
              </p>
            ) : (
              <Select
                value={selected ? optionKey(selected) : undefined}
                onValueChange={(key) => {
                  const option = options.find((item) => optionKey(item) === key);
                  if (option) void save(option);
                }}
              >
                <SelectTrigger
                  id="ask-answer-model"
                  className="w-full sm:max-w-md"
                  disabled={isStreaming || isSaving}
                >
                  <SelectValue placeholder="모델을 고르세요" />
                </SelectTrigger>
                <SelectContent>
                  {visibleOptions.map((option) => (
                    <SelectItem
                      key={optionKey(option)}
                      value={optionKey(option)}
                      disabled={!options.some((item) => optionKey(item) === optionKey(option))}
                    >
                      {modelLabel(option)}
                      {!options.some((item) => optionKey(item) === optionKey(option))
                        ? " (현재 저장됨)"
                        : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          {isSaving ? (
            <span className="flex items-center gap-1 text-xs text-muted-foreground" role="status">
              <Loader2 className="size-3 animate-spin" aria-hidden />
              저장 중…
            </span>
          ) : null}
        </div>
        {!isLoading && !loadError ? (
          <p className="mt-2 text-xs break-words text-muted-foreground">
            현재 사용 중: {selected ? modelLabel(selected) : "선택된 모델 없음"}
          </p>
        ) : null}
        <p className="mt-2 text-xs text-muted-foreground">
          여기서 바꾸면 워크스페이스 설정에도 저장되며 다음 질문부터 적용됩니다.
        </p>
        {saveError ? (
          <div
            className="mt-2 flex flex-wrap items-center gap-2 text-xs text-destructive"
            role="alert"
          >
            <span>저장 실패: {saveError} 기존 모델을 유지합니다.</span>
            {failedOption ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={isStreaming || isSaving}
                onClick={() => void save(failedOption)}
              >
                다시 시도
              </Button>
            ) : null}
          </div>
        ) : null}
      </section>
    </div>
  );
}
