"use client";

import { useState } from "react";
import { KeyRound, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { AiProvider, LlmProvider, WorkspaceSecrets } from "@/lib/api";

import { ApiKeyField } from "./api-key-field";
import { ProviderCapabilities } from "./provider-capabilities";
import { ProviderSelect } from "./provider-select";

function formatUpdatedAt(iso: string): string {
  return iso.slice(0, 10).replaceAll("-", ".");
}

/**
 * 저장된 BYOK 키를 보여주고 교체합니다.
 *
 * 저장된 키 원문은 서버가 내려주지 않으므로 마지막 4자만 표시합니다.
 * 확인이 필요하면 새 키를 넣어 덮어쓰는 방식입니다.
 */
export function ApiKeyCard({
  workspaceId,
  secrets,
  providers,
  onUpdated,
}: {
  workspaceId: string;
  secrets: WorkspaceSecrets | null;
  providers: AiProvider[];
  onUpdated: (next: WorkspaceSecrets) => void;
}) {
  const [isEditing, setIsEditing] = useState(secrets === null);
  const [provider, setProvider] = useState<LlmProvider>(secrets?.provider ?? providers[0].id);
  const [apiKey, setApiKey] = useState("");
  const [isKeyValid, setIsKeyValid] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const save = async () => {
    setIsSaving(true);
    try {
      const next = await api.updateApiKey(workspaceId, { provider, apiKey });
      onUpdated(next);
      setApiKey("");
      setIsKeyValid(false);
      setIsEditing(false);
      toast.success("API key를 저장했습니다.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "키를 저장하지 못했습니다.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-start gap-3">
        <KeyRound className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-medium">LLM API key</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            분석과 답변 생성에 쓰이는 키입니다. 서버에 암호화해 저장하며 저장 후에는 다시 보여주지
            않습니다.
          </p>

          {secrets && !isEditing ? (
            <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1">
              <span className="text-sm">
                {providers.find((item) => item.id === secrets.provider)?.displayName ??
                  secrets.provider}
              </span>
              <span className="font-mono text-sm text-muted-foreground">
                {"•".repeat(12)}
                {secrets.keyHint}
              </span>
              <span className="text-xs text-muted-foreground">
                {formatUpdatedAt(secrets.updatedAt)} 저장
              </span>
              <Button
                variant="outline"
                size="sm"
                className="ml-auto"
                onClick={() => setIsEditing(true)}
              >
                키 교체
              </Button>
            </div>
          ) : (
            <form
              className="mt-4 space-y-4"
              onSubmit={(event) => {
                event.preventDefault();
                void save();
              }}
            >
              <div className="space-y-1.5">
                <label htmlFor="settings-provider" className="text-sm font-medium">
                  Provider
                </label>
                <ProviderSelect
                  id="settings-provider"
                  value={provider}
                  onChange={setProvider}
                  providers={providers}
                  disabled={isSaving}
                />
                <ProviderCapabilities
                  provider={providers.find((item) => item.id === provider)}
                  className="pt-1"
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="settings-key" className="text-sm font-medium">
                  새 API key
                </label>
                <ApiKeyField
                  id="settings-key"
                  provider={provider}
                  value={apiKey}
                  onChange={setApiKey}
                  onValidated={(result) => setIsKeyValid(Boolean(result?.valid))}
                  disabled={isSaving}
                />
              </div>

              <div className="flex gap-2">
                <Button type="submit" size="sm" disabled={!isKeyValid || isSaving}>
                  {isSaving ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
                  저장
                </Button>
                {secrets ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={isSaving}
                    onClick={() => {
                      setIsEditing(false);
                      setApiKey("");
                      setProvider(secrets.provider);
                    }}
                  >
                    취소
                  </Button>
                ) : null}
              </div>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
