"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { useAsync } from "@/hooks/use-async";
import { useApi, useWorkspacePath } from "@/lib/api/context";
import type { ModelOption, RoleModels } from "@/lib/api";
import { optionKey } from "@/features/workspace/lib/model-roles";
import { toUserMessage } from "@/lib/api/error-message";

import { connectionLabels, modelOptionLabel } from "../lib/model-label";

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

  const labels = useMemo(() => connectionLabels(credentials ?? []), [credentials]);
  const providerName = (id: string) =>
    providers?.find((provider) => provider.id === id)?.displayName ?? id;
  const modelLabel = (option: ModelOption) => modelOptionLabel(option, providerName, labels);

  const options = answer?.options ?? [];
  const selected = answer?.selected;
  const selectedAvailable =
    selected && options.some((option) => optionKey(option) === optionKey(selected));
  const visibleOptions = selected && !selectedAvailable ? [selected, ...options] : options;
  const settingsHref = workspacePath(workspaceId, "settings");
  const isReady = !isLoading && !loadError;
  // 쓸 수 있는 모델이 하나도 없거나 저장된 모델의 연결이 사라지면 질문이 실패합니다. 보내기 전에 알립니다.
  const isModelMissing = isReady && (options.length === 0 || (selected && !selectedAvailable));

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
      setSaveError(toUserMessage(cause, "잠시 후 다시 시도해 주세요."));
    } finally {
      savingRef.current = false;
      setIsSaving(false);
      onSavingChange(false);
    }
  };

  /*
   * 상태 줄은 패널을 펼치지 않아도 항상 보입니다. 오류와 다시 시도는 여기 한 곳에만 두고,
   * 펼친 패널에서는 같은 내용을 되풀이하지 않습니다.
   */
  const statusLine = loadError ? (
    <>
      <span className="min-w-0 break-words text-destructive" role="alert">
        답변 모델을 불러오지 못했습니다. {toUserMessage(loadError, "")}
      </span>
      <Button type="button" variant="outline" size="xs" onClick={reload}>
        다시 시도
      </Button>
    </>
  ) : saveError ? (
    <>
      <span className="min-w-0 break-words text-destructive" role="alert">
        모델을 저장하지 못했습니다. {saveError} 기존 모델을 유지합니다.
      </span>
      {failedOption ? (
        <Button
          type="button"
          variant="outline"
          size="xs"
          disabled={isStreaming || isSaving}
          onClick={() => void save(failedOption)}
        >
          다시 시도
        </Button>
      ) : null}
    </>
  ) : isSaving ? (
    <span className="flex items-center gap-1.5" role="status">
      <Spinner className="size-3" />
      모델을 저장하는 중…
    </span>
  ) : isLoading ? (
    <span className="flex items-center gap-1.5" role="status">
      <Spinner className="size-3" />
      답변 모델을 불러오는 중…
    </span>
  ) : isModelMissing ? (
    <span className="min-w-0 break-words text-foreground" role="status">
      {options.length === 0
        ? "답변에 쓸 모델이 없습니다."
        : "저장된 답변 모델을 지금 쓸 수 없습니다."}{" "}
      <Link className="font-medium text-primary underline underline-offset-2" href={settingsHref}>
        설정에서 AI 연결 등록
      </Link>
    </span>
  ) : selected ? (
    <span className="min-w-0 break-words">현재 사용 중: {modelLabel(selected)}</span>
  ) : (
    <span className="min-w-0 break-words">답변 모델을 아직 고르지 않았습니다.</span>
  );

  return (
    <div className="mt-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        {statusLine}
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
            {!isReady ? (
              // 불러오는 중이거나 실패한 사유는 위 상태 줄에 이미 있습니다.
              <p className="text-sm text-muted-foreground">
                {isLoading ? "모델을 불러오는 중…" : "모델을 불러온 뒤에 고를 수 있습니다."}
              </p>
            ) : options.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                AI 연결을 등록하면 여기서 답변 모델을 고를 수 있어요.
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
                  <SelectValue placeholder="모델 선택" />
                </SelectTrigger>
                <SelectContent>
                  {visibleOptions.map((option) => {
                    const isAvailable = options.some(
                      (item) => optionKey(item) === optionKey(option),
                    );
                    return (
                      <SelectItem
                        key={optionKey(option)}
                        value={optionKey(option)}
                        disabled={!isAvailable}
                      >
                        {modelLabel(option)}
                        {isAvailable ? "" : " (현재 저장됨)"}
                      </SelectItem>
                    );
                  })}
                </SelectContent>
              </Select>
            )}
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          여기서 바꾸면 워크스페이스 설정에도 저장되며 다음 질문부터 적용됩니다.
        </p>
      </section>
    </div>
  );
}
