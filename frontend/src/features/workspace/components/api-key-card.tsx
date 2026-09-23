"use client";

import { useRef, useState } from "react";
import { KeyRound, Plus } from "lucide-react";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/state-views";
import { StatusBadge } from "@/components/common/status-badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/api/context";
import type { AiProvider, LlmProvider, WorkspaceSecrets } from "@/lib/api";
import { toUserMessage } from "@/lib/api/error-message";

import {
  AI_CONNECTION_EXPLAINER,
  DEFAULT_CONNECTION_EXPLAINER,
  connectionLabelPlaceholder,
} from "../lib/connection-copy";
import {
  CREDENTIAL_DEFAULT_MESSAGE,
  credentialDefaultErrorMessage,
  credentialDeleteErrorMessage,
  credentialStatusInfo,
} from "../lib/credential-messages";
import { ollamaUrlShapeError } from "../lib/ollama-url";
import { ApiKeyField } from "./api-key-field";
import { ProviderSelect } from "./provider-select";

const hasStoredKey = (credential: WorkspaceSecrets) =>
  credential.keyHint !== "none" && credential.keyHint !== "local";

type KeyAction = "keep" | "replace" | "remove";

const KEY_ACTIONS: { value: KeyAction; label: string; hint?: string }[] = [
  {
    value: "keep",
    label: "유지",
    hint: "저장된 API key를 그대로 씁니다. 저장할 때 서버 연결을 확인합니다.",
  },
  { value: "replace", label: "교체" },
  {
    value: "remove",
    label: "제거",
    hint: "저장된 API key를 지웁니다. 저장할 때 API key 없이 서버 연결을 확인합니다.",
  },
];

/**
 * 계정의 AI 연결 목록과 추가·수정·삭제·기본 지정입니다.
 *
 * 목록을 먼저 보여주고, "연결 추가"나 "수정"을 누른 뒤에만 입력 양식을 엽니다.
 * 수정 중에는 AI 공급자와 연결 이름을 바꿀 수 없으므로 글자로만 보여줍니다.
 */
export function ApiKeyCard({
  credentials,
  providers,
  onUpdated,
  workspaceId,
}: {
  credentials: WorkspaceSecrets[];
  providers: AiProvider[];
  /** 연결이 바뀐 뒤 호출됩니다. 쓸 수 있는 모델 목록까지 달라지는 변경이면 true입니다. */
  onUpdated: (affectsModels: boolean) => void;
  /** 있으면 팀이 공유하는 워크스페이스 연결을, 없으면 개인 계정 연결을 관리합니다. */
  workspaceId?: string;
}) {
  const api = useApi();
  const [mode, setMode] = useState<"idle" | "add" | "edit">("idle");
  const [editingCredential, setEditingCredential] = useState<WorkspaceSecrets>();
  const [chosenProvider, setChosenProvider] = useState<LlmProvider>();
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [keyAction, setKeyAction] = useState<KeyAction>("replace");
  const [validatedKey, setValidatedKey] = useState<string>();
  const [isSaving, setIsSaving] = useState(false);
  const [defaultPendingId, setDefaultPendingId] = useState<string>();
  const [deleteTarget, setDeleteTarget] = useState<WorkspaceSecrets>();
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string>();
  const formRef = useRef<HTMLFormElement>(null);

  const provider: LlmProvider =
    editingCredential?.provider ??
    (chosenProvider && providers.some((item) => item.id === chosenProvider)
      ? chosenProvider
      : (credentials.find((item) => item.isDefault)?.provider ?? providers[0]?.id ?? ""));
  const providerName = (id: LlmProvider) =>
    providers.find((item) => item.id === id)?.displayName ?? id;
  const isOllama = provider === "ollama";
  const isEditing = mode === "edit" && editingCredential !== undefined;
  // 키가 저장돼 있지 않은 Ollama 연결에는 유지·제거할 대상이 없으므로 선택지를 보여주지 않습니다.
  const choosesKeyAction = isEditing && isOllama && hasStoredKey(editingCredential);
  const needsValidation = !choosesKeyAction || keyAction === "replace";
  const trimmedLabel = label.trim();
  const duplicateLabel =
    !isEditing &&
    credentials.some((item) => item.provider === provider && item.label === trimmedLabel);
  const canSave =
    Boolean(trimmedLabel) &&
    !duplicateLabel &&
    (!isOllama || (Boolean(baseUrl.trim()) && !ollamaUrlShapeError(baseUrl))) &&
    (!needsValidation || validatedKey === apiKey.trim());

  const resetSecretInputs = () => {
    setApiKey("");
    setValidatedKey(undefined);
  };

  const focusForm = (selector: string) => {
    window.requestAnimationFrame(() => {
      formRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      formRef.current?.querySelector<HTMLElement>(selector)?.focus({ preventScroll: true });
    });
  };

  const beginAdd = () => {
    setMode("add");
    setEditingCredential(undefined);
    setLabel("");
    setBaseUrl("");
    setKeyAction("replace");
    resetSecretInputs();
    focusForm("#settings-provider");
  };

  const beginEdit = (credential: WorkspaceSecrets) => {
    setMode("edit");
    setEditingCredential(credential);
    setLabel(credential.label);
    setBaseUrl(credential.baseUrl ?? "");
    setKeyAction(credential.provider === "ollama" && hasStoredKey(credential) ? "keep" : "replace");
    resetSecretInputs();
    focusForm(credential.provider === "ollama" ? "#settings-base-url" : "#settings-key");
  };

  const closeForm = () => {
    setMode("idle");
    setEditingCredential(undefined);
    resetSecretInputs();
  };

  const save = async () => {
    if (!canSave || isSaving) return;
    setIsSaving(true);
    try {
      if (isEditing) {
        const keepsKey = choosesKeyAction && keyAction === "keep";
        await (workspaceId
          ? api.rotateProviderCredential(workspaceId, editingCredential.id, {
              ...(isOllama && baseUrl.trim() !== (editingCredential.baseUrl ?? "")
                ? { baseUrl: baseUrl.trim() }
                : {}),
              ...(keepsKey ? {} : { apiKey: keyAction === "remove" ? "" : apiKey.trim() }),
            })
          : api.rotateAccountCredential(editingCredential.id, {
              ...(isOllama && baseUrl.trim() !== (editingCredential.baseUrl ?? "")
                ? { baseUrl: baseUrl.trim() }
                : {}),
              ...(keepsKey ? {} : { apiKey: keyAction === "remove" ? "" : apiKey.trim() }),
            }));
      } else {
        const input = {
          provider,
          label: trimmedLabel,
          apiKey: apiKey.trim(),
          ...(isOllama ? { baseUrl: baseUrl.trim() } : {}),
        };
        await (workspaceId
          ? api.createWorkspaceCredential(workspaceId, input)
          : api.createAccountCredential(input));
      }
      toast.success(isEditing ? "AI 연결을 수정했습니다." : "AI 연결을 추가했습니다.");
      closeForm();
      onUpdated(true);
    } catch (error) {
      toast.error(toUserMessage(error, "AI 연결을 저장하지 못했습니다."));
    } finally {
      setIsSaving(false);
    }
  };

  const makeDefault = async (credential: WorkspaceSecrets) => {
    if (defaultPendingId) return;
    setDefaultPendingId(credential.id);
    try {
      await (workspaceId
        ? api.setDefaultWorkspaceCredential(workspaceId, credential.id)
        : api.setDefaultAccountCredential(credential.id));
      toast.success("기본 연결을 바꿨습니다.");
      onUpdated(false);
    } catch (error) {
      toast.error(credentialDefaultErrorMessage(error));
    } finally {
      setDefaultPendingId(undefined);
    }
  };

  // 서버도 같은 이유로 거절하므로, 미리 알 수 있는 경우에는 요청을 보내지 않고 이유만 보여줍니다.
  const deleteBlockedByDefault =
    deleteTarget !== undefined && deleteTarget.isDefault && credentials.length > 1;

  const confirmDelete = async () => {
    if (!deleteTarget || isDeleting) return;
    setIsDeleting(true);
    setDeleteError(undefined);
    try {
      await (workspaceId
        ? api.deleteWorkspaceCredential(workspaceId, deleteTarget.id)
        : api.deleteAccountCredential(deleteTarget.id));
      toast.success("AI 연결을 삭제했습니다.");
      if (editingCredential?.id === deleteTarget.id) closeForm();
      setDeleteTarget(undefined);
      onUpdated(true);
    } catch (error) {
      setDeleteError(credentialDeleteErrorMessage(error));
    } finally {
      setIsDeleting(false);
    }
  };

  const isBusy = isSaving || isDeleting || defaultPendingId !== undefined;

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-start gap-3">
          <KeyRound className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <h2 className="text-sm font-medium">
                {workspaceId ? "워크스페이스 AI 연결" : "계정 AI 연결"}
              </h2>
              {credentials.length > 0 ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={isBusy}
                  onClick={beginAdd}
                >
                  <Plus aria-hidden />
                  연결 추가
                </Button>
              ) : null}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {AI_CONNECTION_EXPLAINER}{" "}
              {workspaceId
                ? "관리자가 등록하며 모든 멤버의 분석과 기본 Ask에 우선 사용됩니다."
                : "내가 참여한 워크스페이스에 공유 연결이 없을 때 사용합니다."}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">{DEFAULT_CONNECTION_EXPLAINER}</p>

            {credentials.length === 0 ? (
              <EmptyState
                className="mt-4 p-6"
                icon={<KeyRound className="size-5" aria-hidden />}
                title="저장된 AI 연결이 없습니다"
                description="연결을 추가하면 이 워크스페이스에서 쓸 모델을 고를 수 있어요."
                action={
                  <Button type="button" size="sm" disabled={isBusy} onClick={beginAdd}>
                    <Plus aria-hidden />
                    연결 추가
                  </Button>
                }
              />
            ) : (
              <ul className="mt-4 space-y-2">
                {credentials.map((credential) => {
                  const name = `${providerName(credential.provider)} ${credential.label}`;
                  const status = credentialStatusInfo(credential.status);
                  return (
                    <li
                      key={credential.id}
                      className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-border px-3 py-2 text-sm"
                    >
                      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="text-muted-foreground">
                          {providerName(credential.provider)}
                        </span>
                        <span className="font-medium break-words">{credential.label}</span>
                        {credential.isDefault ? (
                          <StatusBadge tone="info">기본 연결</StatusBadge>
                        ) : null}
                        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
                        {credential.baseUrl ? (
                          <span className="min-w-0 text-xs break-all text-muted-foreground">
                            {credential.baseUrl}
                          </span>
                        ) : null}
                        {credential.provider === "ollama" ? (
                          <span className="text-xs text-muted-foreground">
                            {hasStoredKey(credential) ? "API key 있음" : "API key 없음"}
                          </span>
                        ) : credential.keyHint ? (
                          <span className="font-mono text-xs text-muted-foreground">
                            <span className="sr-only">API key 끝자리 </span>
                            <span aria-hidden>••••</span>
                            {credential.keyHint}
                          </span>
                        ) : null}
                        {credential.status !== "active" ? (
                          <span className="basis-full text-xs text-muted-foreground">
                            수정에서 연결을 다시 확인하면 쓸 수 있어요.
                          </span>
                        ) : null}
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5">
                        {!credential.isDefault && credential.status === "active" ? (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            aria-label={`${name} 연결을 기본으로 지정`}
                            disabled={isBusy}
                            pending={defaultPendingId === credential.id}
                            onClick={() => void makeDefault(credential)}
                          >
                            기본으로 지정
                          </Button>
                        ) : null}
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          aria-label={`${name} 연결 수정`}
                          disabled={isBusy}
                          onClick={() => beginEdit(credential)}
                        >
                          수정
                        </Button>
                        <Button
                          type="button"
                          variant="destructive"
                          size="sm"
                          aria-label={`${name} 연결 삭제`}
                          disabled={isBusy}
                          onClick={() => {
                            setDeleteError(undefined);
                            setDeleteTarget(credential);
                          }}
                        >
                          삭제
                        </Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </section>

      {mode !== "idle" ? (
        <section className="rounded-xl border border-border bg-card p-5">
          <h2 className="text-sm font-medium">
            {isEditing ? `${editingCredential.label} 연결 수정` : "연결 추가"}
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {isEditing
              ? `${isOllama ? "서버 주소와 API key를" : "API key를"} 바꿉니다. 이 연결을 쓰는 모든 워크스페이스에 적용됩니다.`
              : "AI 공급자를 고른 뒤 연결 이름과 API key를 입력해 주세요."}
          </p>
          <form
            ref={formRef}
            className="mt-4 scroll-mt-4 space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            {isEditing ? (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted-foreground">AI 공급자</dt>
                <dd className="font-medium">{providerName(provider)}</dd>
                <dt className="text-muted-foreground">연결 이름</dt>
                <dd className="font-medium break-words">{editingCredential.label}</dd>
              </dl>
            ) : (
              <>
                <div className="space-y-1.5">
                  <label htmlFor="settings-provider" className="text-sm font-medium">
                    AI 공급자
                  </label>
                  <ProviderSelect
                    id="settings-provider"
                    value={provider}
                    providers={providers}
                    disabled={isSaving}
                    onChange={(next) => {
                      // 이전 공급자의 키로 새 공급자를 확인하지 않도록 비웁니다. 연결 이름은 남깁니다.
                      setChosenProvider(next);
                      setBaseUrl("");
                      resetSecretInputs();
                    }}
                  />
                </div>
                <div className="space-y-1.5">
                  <label htmlFor="settings-label" className="text-sm font-medium">
                    연결 이름
                  </label>
                  <Input
                    id="settings-label"
                    value={label}
                    maxLength={80}
                    placeholder={connectionLabelPlaceholder(provider)}
                    disabled={isSaving}
                    onChange={(event) => setLabel(event.target.value)}
                    aria-describedby={duplicateLabel ? "settings-label-error" : undefined}
                    aria-invalid={duplicateLabel || undefined}
                    required
                  />
                  {duplicateLabel ? (
                    <p id="settings-label-error" className="text-xs text-warning">
                      이 이름의 연결이 이미 있습니다. 목록에서 수정을 선택하거나 다른 이름을 입력해
                      주세요.
                    </p>
                  ) : null}
                </div>
              </>
            )}

            <ApiKeyField
              id="settings-key"
              provider={provider}
              authMode={isOllama ? "optionalApiKey" : "apiKey"}
              label={isOllama ? "API key (선택 사항)" : isEditing ? "새 API key" : "API key"}
              value={apiKey}
              baseUrlField={
                isOllama
                  ? {
                      id: "settings-base-url",
                      value: baseUrl,
                      onChange: (value) => {
                        setBaseUrl(value);
                        setValidatedKey(undefined);
                      },
                    }
                  : undefined
              }
              keyInputHidden={!needsValidation}
              onChange={(value) => {
                setApiKey(value);
                setValidatedKey(undefined);
              }}
              onValidated={(result, key) => setValidatedKey(result?.valid ? key : undefined)}
              disabled={isSaving}
            >
              {choosesKeyAction ? (
                <div className="space-y-2">
                  <p id="settings-key-action-label" className="text-sm font-medium">
                    기존 API key
                  </p>
                  <div
                    role="radiogroup"
                    aria-labelledby="settings-key-action-label"
                    className="flex flex-wrap gap-2"
                    onKeyDown={(event) => {
                      const step =
                        event.key === "ArrowRight" || event.key === "ArrowDown"
                          ? 1
                          : event.key === "ArrowLeft" || event.key === "ArrowUp"
                            ? -1
                            : 0;
                      if (!step || isSaving) return;
                      event.preventDefault();
                      const index = KEY_ACTIONS.findIndex((item) => item.value === keyAction);
                      const next =
                        KEY_ACTIONS[(index + step + KEY_ACTIONS.length) % KEY_ACTIONS.length];
                      setKeyAction(next.value);
                      resetSecretInputs();
                      event.currentTarget
                        .querySelector<HTMLElement>(`[data-key-action="${next.value}"]`)
                        ?.focus();
                    }}
                  >
                    {KEY_ACTIONS.map((item) => (
                      <Button
                        key={item.value}
                        type="button"
                        role="radio"
                        size="sm"
                        data-key-action={item.value}
                        aria-checked={keyAction === item.value}
                        tabIndex={keyAction === item.value ? 0 : -1}
                        variant={keyAction === item.value ? "default" : "outline"}
                        disabled={isSaving}
                        onClick={() => {
                          setKeyAction(item.value);
                          resetSecretInputs();
                        }}
                      >
                        {item.label}
                      </Button>
                    ))}
                  </div>
                  {KEY_ACTIONS.find((item) => item.value === keyAction)?.hint ? (
                    <p className="text-xs text-muted-foreground">
                      {KEY_ACTIONS.find((item) => item.value === keyAction)?.hint}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </ApiKeyField>

            <div className="flex gap-2">
              <Button
                type="submit"
                size="sm"
                disabled={!canSave}
                pending={isSaving}
                pendingLabel="저장하는 중…"
              >
                저장
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={isSaving}
                onClick={closeForm}
              >
                취소
              </Button>
            </div>
          </form>
        </section>
      ) : null}

      <Dialog
        open={deleteTarget !== undefined}
        onOpenChange={(next) => {
          // 삭제 요청이 나가 있는 동안에는 닫지 않습니다. 결과를 놓치지 않게 하려는 것입니다.
          if (!next && !isDeleting) setDeleteTarget(undefined);
        }}
      >
        <DialogContent className="sm:max-w-md" showCloseButton={!isDeleting}>
          <DialogHeader>
            <DialogTitle>AI 연결 삭제</DialogTitle>
            <DialogDescription>
              {deleteTarget
                ? deleteBlockedByDefault
                  ? CREDENTIAL_DEFAULT_MESSAGE
                  : `${providerName(deleteTarget.provider)} · ${deleteTarget.label} 연결과 저장된 API key를 삭제합니다. 삭제한 뒤에는 되돌릴 수 없습니다. 워크스페이스의 모델에 쓰이고 있는 연결은 삭제되지 않습니다.`
                : null}
            </DialogDescription>
          </DialogHeader>
          {deleteError ? (
            <p role="alert" className="text-sm text-destructive">
              {deleteError}
            </p>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              disabled={isDeleting}
              onClick={() => setDeleteTarget(undefined)}
            >
              {deleteBlockedByDefault ? "닫기" : "취소"}
            </Button>
            {deleteBlockedByDefault ? null : (
              <Button
                type="button"
                variant="destructive"
                pending={isDeleting}
                pendingLabel="삭제하는 중…"
                onClick={() => void confirmDelete()}
              >
                삭제
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
