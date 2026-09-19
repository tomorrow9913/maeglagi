"use client";

import { useRef, useState } from "react";
import { KeyRound, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/api/context";
import type { AiProvider, LlmProvider, WorkspaceSecrets } from "@/lib/api";

import { ApiKeyField } from "./api-key-field";
import { ProviderSelect } from "./provider-select";

export function ApiKeyCard({
  workspaceId,
  credentials,
  providers,
  provider,
  onProviderChange,
  onUpdated,
}: {
  workspaceId: string;
  credentials: WorkspaceSecrets[];
  providers: AiProvider[];
  provider: LlmProvider;
  onProviderChange: (provider: LlmProvider) => void;
  onUpdated: () => void;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const api = useApi();
  const [editingCredential, setEditingCredential] = useState<WorkspaceSecrets>();
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [validatedKey, setValidatedKey] = useState<string>();
  const [isSaving, setIsSaving] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const selectedCredentials = credentials.filter((item) => item.provider === provider);

  const beginEdit = (credential?: WorkspaceSecrets) => {
    setEditingCredential(credential);
    setLabel(credential?.label ?? "");
    setApiKey("");
    setValidatedKey(undefined);
    setIsEditing(true);
    window.requestAnimationFrame(() => {
      formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      formRef.current
        ?.querySelector<HTMLInputElement>(credential ? "#settings-key" : "#settings-label")
        ?.focus({ preventScroll: true });
    });
  };

  const selectKeyProvider = (next: LlmProvider) => {
    onProviderChange(next);
    setIsEditing(false);
    setEditingCredential(undefined);
    setApiKey("");
    setValidatedKey(undefined);
  };

  const save = async () => {
    const trimmedLabel = label.trim();
    if (
      !trimmedLabel ||
      validatedKey !== apiKey.trim() ||
      (!editingCredential &&
        credentials.some((item) => item.provider === provider && item.label === trimmedLabel))
    )
      return;
    setIsSaving(true);
    try {
      await api.updateApiKey(workspaceId, { provider, label: trimmedLabel, apiKey: apiKey.trim() });
      setIsEditing(false);
      setApiKey("");
      setValidatedKey(undefined);
      onUpdated();
      toast.success("API key를 저장하고 기본 키로 지정했습니다.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "키를 저장하지 못했습니다.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-start gap-3">
          <KeyRound className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-medium">LLM API key</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              등록된 키의 provider와 이름을 확인하고 새 키를 추가하거나 교체할 수 있습니다. 아래
              provider 선택은 키 등록에만 적용됩니다. 키 원문은 저장 후 다시 보여주지 않습니다.
            </p>
            <form
              ref={formRef}
              className="mt-4 scroll-mt-4 space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (isEditing) void save();
              }}
            >
              {isEditing ? (
                <p className="text-xs text-muted-foreground">
                  {editingCredential
                    ? "기존 키를 교체하고 기본 키로 지정합니다."
                    : "새 키를 추가하고 기본 키로 지정합니다."}
                </p>
              ) : null}
              <div className="space-y-1.5">
                <label htmlFor="settings-provider" className="text-sm font-medium">
                  API key provider
                </label>
                <ProviderSelect
                  id="settings-provider"
                  value={provider}
                  providers={providers}
                  disabled={isSaving}
                  onChange={selectKeyProvider}
                />
              </div>
              {!isEditing ? (
                <Button type="button" size="sm" variant="outline" onClick={() => beginEdit()}>
                  {selectedCredentials.length ? "다른 키 추가" : "API key 등록"}
                </Button>
              ) : (
                <>
                  <div className="space-y-1.5">
                    <label htmlFor="settings-label" className="text-sm font-medium">
                      키 이름
                    </label>
                    <Input
                      id="settings-label"
                      value={label}
                      maxLength={80}
                      disabled={isSaving || Boolean(editingCredential)}
                      onChange={(event) => setLabel(event.target.value)}
                      required
                    />
                    {!editingCredential &&
                    label.trim() &&
                    credentials.some(
                      (item) => item.provider === provider && item.label === label.trim(),
                    ) ? (
                      <p className="text-xs text-warning">
                        이 이름의 키가 이미 있습니다. 목록에서 키 교체를 선택하거나 다른 이름을
                        입력해 주세요.
                      </p>
                    ) : null}
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="settings-key" className="text-sm font-medium">
                      새 API key
                    </label>
                    <ApiKeyField
                      id="settings-key"
                      provider={provider}
                      value={apiKey}
                      onChange={(value) => {
                        setApiKey(value);
                        setValidatedKey(undefined);
                      }}
                      onValidated={(result, key) =>
                        setValidatedKey(result?.valid ? key : undefined)
                      }
                      disabled={isSaving}
                    />
                  </div>
                  <div className="flex gap-2">
                    <Button
                      type="submit"
                      size="sm"
                      disabled={
                        !label.trim() ||
                        validatedKey !== apiKey.trim() ||
                        isSaving ||
                        (!editingCredential &&
                          credentials.some(
                            (item) => item.provider === provider && item.label === label.trim(),
                          ))
                      }
                    >
                      {isSaving ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}{" "}
                      저장
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={isSaving}
                      onClick={() => {
                        setIsEditing(false);
                        setApiKey("");
                      }}
                    >
                      취소
                    </Button>
                  </div>
                </>
              )}
            </form>
          </div>
        </div>
      </section>
      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="text-sm font-medium">등록된 API 키</h2>
        <div className="mt-4 space-y-2">
          {credentials.length === 0 ? (
            <p className="text-sm text-muted-foreground">등록된 키가 없습니다.</p>
          ) : (
            credentials.map((credential) => (
              <div
                key={credential.id}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm"
              >
                <span>
                  {providers.find((item) => item.id === credential.provider)?.displayName ??
                    credential.provider}
                </span>
                <span className="font-medium">{credential.label}</span>
                <span className="font-mono text-muted-foreground">••••{credential.keyHint}</span>
                <span className="text-xs text-muted-foreground">
                  {credential.isDefault ? "기본 키 · " : ""}
                  {credential.status === "active" ? "활성" : credential.status}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={isSaving}
                  onClick={() => {
                    onProviderChange(credential.provider);
                    beginEdit(credential);
                  }}
                >
                  키 교체
                </Button>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
