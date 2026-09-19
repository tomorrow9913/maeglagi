"use client";

import { useRef, useState } from "react";
import { KeyRound, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/api/context";
import type { AiProvider, LlmProvider, WorkspaceSecrets } from "@/lib/api";

import { ApiKeyField } from "./api-key-field";
import { OllamaBaseUrlField } from "./ollama-base-url-field";
import { ProviderSelect } from "./provider-select";

const hasOllamaKey = (credential: WorkspaceSecrets) =>
  credential.keyHint !== "none" && credential.keyHint !== "local";

export function ApiKeyCard({
  credentials,
  providers,
  provider,
  onProviderChange,
  onUpdated,
}: {
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
  const [baseUrl, setBaseUrl] = useState("");
  const [keyAction, setKeyAction] = useState<"keep" | "replace" | "remove">("replace");
  const [validatedKey, setValidatedKey] = useState<string>();
  const [isSaving, setIsSaving] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const selectedCredentials = credentials.filter((item) => item.provider === provider);
  const isOllama = provider === "ollama";

  const beginEdit = (credential?: WorkspaceSecrets) => {
    setEditingCredential(credential);
    setLabel(credential?.label ?? "");
    setApiKey("");
    setBaseUrl(credential?.baseUrl ?? "");
    setKeyAction(credential && hasOllamaKey(credential) ? "keep" : "remove");
    setValidatedKey(undefined);
    setIsEditing(true);
    window.requestAnimationFrame(() => {
      formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      formRef.current
        ?.querySelector<HTMLInputElement>(credential?.provider === "ollama" ? "#settings-base-url" : credential ? "#settings-key" : "#settings-label")
        ?.focus({ preventScroll: true });
    });
  };

  const selectKeyProvider = (next: LlmProvider) => {
    onProviderChange(next);
    setIsEditing(false);
    setEditingCredential(undefined);
    setApiKey("");
    setBaseUrl("");
    setKeyAction("replace");
    setValidatedKey(undefined);
  };

  const save = async () => {
    const trimmedLabel = label.trim();
    const needsValidation = !isOllama || !editingCredential || keyAction === "replace";
    if (
      !trimmedLabel ||
      (isOllama && !baseUrl.trim()) ||
      (needsValidation && validatedKey !== apiKey.trim()) ||
      (!editingCredential &&
        credentials.some((item) => item.provider === provider && item.label === trimmedLabel))
    )
      return;
    setIsSaving(true);
    try {
      if (editingCredential) {
        await api.rotateAccountCredential(editingCredential.id, {
          ...(isOllama && baseUrl.trim() !== (editingCredential.baseUrl ?? "") ? { baseUrl: baseUrl.trim() } : {}),
          ...(isOllama && keyAction === "keep" ? {} : { apiKey: isOllama && keyAction === "remove" ? "" : apiKey.trim() }),
        });
      } else {
        await api.createAccountCredential({
          provider,
          label: trimmedLabel,
          apiKey: apiKey.trim(),
          ...(isOllama ? { baseUrl: baseUrl.trim() } : {}),
        });
      }
      setIsEditing(false);
      setApiKey("");
      setValidatedKey(undefined);
      onUpdated();
      toast.success(editingCredential ? "계정 AI 연결을 수정했습니다." : "계정 AI 연결을 등록했습니다.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "AI 연결을 저장하지 못했습니다.");
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
            <h2 className="text-sm font-medium">AI 연결</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              이 계정의 AI 연결은 여러 워크스페이스에서 함께 사용합니다. 아래 공급자 선택은 연결 등록에만
              적용됩니다. 키 원문은 저장 후 다시 보여주지 않습니다.
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
                    ? isOllama ? "계정의 Ollama 서버 주소와 키를 수정합니다." : "계정의 기존 키를 교체합니다."
                    : "계정에 새 연결을 추가합니다."}
                </p>
              ) : null}
              <div className="space-y-1.5">
                <label htmlFor="settings-provider" className="text-sm font-medium">
                  AI 공급자
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
                  {selectedCredentials.length ? "다른 연결 추가" : "연결 등록"}
                </Button>
              ) : (
                <>
                  <div className="space-y-1.5">
                    <label htmlFor="settings-label" className="text-sm font-medium">
                      연결 이름
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
                        이 이름의 연결이 이미 있습니다. 목록에서 수정을 선택하거나 다른 이름을
                        입력해 주세요.
                      </p>
                    ) : null}
                  </div>
                  {isOllama ? (
                    <OllamaBaseUrlField
                      id="settings-base-url"
                      value={baseUrl}
                      disabled={isSaving}
                      onChange={(value) => { setBaseUrl(value); setValidatedKey(undefined); }}
                    />
                  ) : null}
                  {isOllama && editingCredential ? (
                    <div className="space-y-2">
                      <p className="text-sm font-medium">기존 API key</p>
                      <div className="flex flex-wrap gap-2">
                        <Button type="button" size="sm" variant={keyAction === "keep" ? "default" : "outline"} disabled={isSaving} onClick={() => { setKeyAction("keep"); setApiKey(""); setValidatedKey(undefined); }}>유지</Button>
                        <Button type="button" size="sm" variant={keyAction === "replace" ? "default" : "outline"} disabled={isSaving} onClick={() => { setKeyAction("replace"); setApiKey(""); setValidatedKey(undefined); }}>교체</Button>
                        <Button type="button" size="sm" variant={keyAction === "remove" ? "default" : "outline"} disabled={isSaving} onClick={() => { setKeyAction("remove"); setApiKey(""); setValidatedKey(undefined); }}>제거</Button>
                      </div>
                      {keyAction !== "replace" ? <p className="text-xs text-muted-foreground">{keyAction === "keep" ? "저장된 키를 유지합니다. 저장할 때 서버 연결을 확인합니다." : "저장된 키를 제거합니다. 저장할 때 키 없이 서버 연결을 확인합니다."}</p> : null}
                    </div>
                  ) : null}
                  {(!isOllama || !editingCredential || keyAction === "replace") ? <div className="space-y-1.5">
                    <label htmlFor="settings-key" className="text-sm font-medium">
                      {isOllama ? "API key (선택 사항)" : "새 API key"}
                    </label>
                    <ApiKeyField
                      id="settings-key"
                      provider={provider}
                      authMode={isOllama ? "optionalApiKey" : "apiKey"}
                      baseUrl={isOllama ? baseUrl : undefined}
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
                  </div> : null}
                  <div className="flex gap-2">
                    <Button
                      type="submit"
                      size="sm"
                      disabled={
                        !label.trim() ||
                        (isOllama && !baseUrl.trim()) ||
                        ((!isOllama || !editingCredential || keyAction === "replace") && validatedKey !== apiKey.trim()) ||
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
                        setValidatedKey(undefined);
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
        <h2 className="text-sm font-medium">계정에 등록된 AI 연결</h2>
        <div className="mt-4 space-y-2">
          {credentials.length === 0 ? (
            <p className="text-sm text-muted-foreground">등록된 연결이 없습니다.</p>
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
                {credential.baseUrl ? <span className="min-w-0 break-all text-xs text-muted-foreground">{credential.baseUrl}</span> : null}
                {credential.provider === "ollama"
                  ? <span className="text-xs text-muted-foreground">{hasOllamaKey(credential) ? "키 설정됨" : "키 없음"}</span>
                  : credential.keyHint ? <span className="font-mono text-muted-foreground">••••{credential.keyHint}</span> : null}
                <span className="text-xs text-muted-foreground">
                  {credential.isDefault ? "기본 연결 · " : ""}
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
                  수정
                </Button>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
