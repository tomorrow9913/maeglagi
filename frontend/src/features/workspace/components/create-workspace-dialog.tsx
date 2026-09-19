"use client";

import { useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAsync } from "@/hooks/use-async";
import { BOOTSTRAP_AI_PROVIDERS, pickDefaultProvider, withOllamaProvider } from "@/lib/api";
import { useApi } from "@/lib/api/context";
import type { LlmProvider, Workspace, WorkspaceSecrets } from "@/lib/api";

import { bindCredentialToSelections } from "../lib/model-roles";
import { useKeyModels } from "../hooks/use-key-models";
import { ApiKeyField } from "./api-key-field";
import { KeyModelSection } from "./key-model-section";
import { OllamaBaseUrlField } from "./ollama-base-url-field";
import { ProviderDefaults } from "./provider-defaults";
import { ProviderSelect } from "./provider-select";

/**
 * 계정의 AI 연결을 선택하고 워크스페이스의 모델 역할을 정합니다.
 * 처음 쓰는 계정에는 연결을 등록한 뒤 그 연결을 사용합니다.
 */
export function CreateWorkspaceDialog({ onCreated }: { onCreated: (created: Workspace) => void }) {
  const api = useApi();
  const [isOpen, setIsOpen] = useState(false);
  const [name, setName] = useState("");
  // 서버가 지원하는 provider를 받아 보여줍니다. 받지 못하면 대비 목록으로 물러섭니다.
  const { data: catalog } = useAsync((signal) => api.listProviders(signal), []);
  const { data: savedCredentials, error: credentialsError, isLoading: credentialsLoading, reload: reloadCredentials } =
    useAsync((signal) => api.listAccountCredentials(signal), []);
  const providers = withOllamaProvider(catalog && catalog.length > 0 ? catalog : BOOTSTRAP_AI_PROVIDERS);
  const [chosen, setChosen] = useState<LlmProvider>();
  const accountDefaultProvider = savedCredentials?.find((item) => item.isDefault && item.status === "active")?.provider
    ?? savedCredentials?.find((item) => item.status === "active")?.provider;
  const provider =
    chosen && providers.some((item) => item.id === chosen)
      ? chosen
      : accountDefaultProvider && providers.some((item) => item.id === accountDefaultProvider)
        ? accountDefaultProvider
        : pickDefaultProvider(providers);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [connectionLabel, setConnectionLabel] = useState("");
  const [credentialMode, setCredentialMode] = useState<"saved" | "new">("saved");
  const [chosenCredentialId, setChosenCredentialId] = useState<string>();
  const [newlySavedCredential, setNewlySavedCredential] = useState<WorkspaceSecrets>();
  const accountCredentials = newlySavedCredential && !savedCredentials?.some((item) => item.id === newlySavedCredential.id)
    ? [...(savedCredentials ?? []), newlySavedCredential]
    : savedCredentials ?? [];
  const credentialsReady = savedCredentials !== undefined && !credentialsError;
  const availableCredentials = accountCredentials.filter((item) => item.provider === provider && item.status === "active");
  const duplicateLabel = accountCredentials.some((item) => item.provider === provider && item.label === connectionLabel.trim());
  const selectedCredential = availableCredentials.find((item) => item.id === chosenCredentialId) ?? availableCredentials[0];
  const addingConnection = credentialMode === "new" || availableCredentials.length === 0;
  // 검증을 통과한 키. 이 키로만 모델 목록을 받아 오므로, 없으면 아직 확인 전이라는 뜻입니다.
  const [validatedKey, setValidatedKey] = useState<string>();
  const isKeyValid = credentialsReady && (addingConnection ? validatedKey !== undefined : Boolean(selectedCredential));
  const [isSubmitting, setIsSubmitting] = useState(false);
  const selectedProvider = providers.find((item) => item.id === provider);
  const keyModels = useKeyModels(
    provider,
    addingConnection ? validatedKey : undefined,
    selectedProvider?.defaultModels,
    addingConnection && selectedProvider?.requiresBaseUrl ? baseUrl : undefined,
    addingConnection ? undefined : selectedCredential?.id,
  );

  const reset = () => {
    setName("");
    setChosen(undefined);
    setApiKey("");
    setBaseUrl("");
    setConnectionLabel("");
    setCredentialMode("saved");
    setChosenCredentialId(undefined);
    setNewlySavedCredential(undefined);
    setValidatedKey(undefined);
  };

  const submit = async () => {
    if (
      isSubmitting || !name.trim() || !credentialsReady || !isKeyValid ||
      !keyModels.roles || keyModels.error || keyModels.isLoading ||
      Object.keys(keyModels.selections).length === 0 ||
      (addingConnection && (!connectionLabel.trim() || duplicateLabel))
    ) return;
    setIsSubmitting(true);
    try {
      let credentialId = selectedCredential?.id;
      if (addingConnection) {
        const saved = await api.createAccountCredential({
          provider,
          label: connectionLabel.trim(),
          apiKey: selectedProvider?.authMode === "none" ? "" : apiKey.trim(),
          ...(selectedProvider?.requiresBaseUrl ? { baseUrl: baseUrl.trim() } : {}),
        });
        credentialId = saved.id;
        setNewlySavedCredential(saved);
        setChosenCredentialId(saved.id);
        setCredentialMode("saved");
        setApiKey("");
        setValidatedKey(undefined);
        reloadCredentials();
      }
      const models = bindCredentialToSelections(keyModels.selections, provider, credentialId!);
      const created = await api.createWorkspace({
        name,
        credentialId,
        models,
      });

      toast.success(`${created.name} 워크스페이스를 만들었습니다.`);
      onCreated(created);
      setIsOpen(false);
      reset();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "워크스페이스를 만들지 못했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(next) => {
        setIsOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="size-4" aria-hidden />새 워크스페이스
        </Button>
      </DialogTrigger>

      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>새 워크스페이스</DialogTitle>
          <DialogDescription>맥락을 모을 공간을 만들고 분석에 쓸 AI 연결을 선택합니다.</DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="space-y-1.5">
            <label htmlFor="workspace-name" className="text-sm font-medium">
              이름
            </label>
            <Input
              id="workspace-name"
              value={name}
              placeholder="예: 맥락이 PoC"
              disabled={isSubmitting}
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="workspace-provider" className="text-sm font-medium">
              AI 공급자
            </label>
            <ProviderSelect
              id="workspace-provider"
              value={provider}
              onChange={(next) => {
                // 다른 provider에 이전 키로 모델을 요청하지 않도록, 키는 다시 확인될 때까지 비웁니다.
                setValidatedKey(undefined);
                setApiKey("");
                setBaseUrl("");
                setConnectionLabel("");
                setChosenCredentialId(undefined);
                setCredentialMode("saved");
                setChosen(next);
              }}
              providers={providers}
              disabled={isSubmitting}
            />
            {/* 연결을 확인하기 전에도 공급자의 기본 모델을 보여줍니다. */}
            {!isKeyValid ? <ProviderDefaults provider={selectedProvider} className="pt-1" /> : null}
          </div>

          {credentialsLoading && !savedCredentials ? <p className="text-xs text-muted-foreground">저장된 AI 연결을 불러오는 중…</p> : null}
          {credentialsError ? (
            <div className="space-y-2 text-xs text-destructive" role="alert">
              <p>계정의 AI 연결을 불러오지 못했습니다. 중복 등록을 피하려면 다시 불러와 주세요.</p>
              <Button type="button" size="sm" variant="outline" onClick={reloadCredentials}>다시 시도</Button>
            </div>
          ) : null}

          {credentialsReady && availableCredentials.length > 0 ? (
            <div className="space-y-1.5">
              <label htmlFor="workspace-credential" className="text-sm font-medium">계정 AI 연결</label>
              {addingConnection ? (
                <Button type="button" size="sm" variant="outline" onClick={() => { setCredentialMode("saved"); setValidatedKey(undefined); setApiKey(""); }}>저장된 연결 선택</Button>
              ) : (
                <Select value={selectedCredential?.id} onValueChange={(id) => setChosenCredentialId(id)}>
                  <SelectTrigger id="workspace-credential"><SelectValue placeholder="연결을 고르세요" /></SelectTrigger>
                  <SelectContent>
                    {availableCredentials.map((credential) => (
                      <SelectItem key={credential.id} value={credential.id}>
                        {credential.label}{credential.baseUrl ? ` · ${credential.baseUrl}` : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              {!addingConnection ? <Button type="button" size="sm" variant="outline" onClick={() => { setCredentialMode("new"); setChosenCredentialId(undefined); }}>새 연결 등록</Button> : null}
              <p className="text-xs text-muted-foreground">이 연결은 계정에 저장되어 다른 워크스페이스에서도 사용할 수 있습니다.</p>
            </div>
          ) : null}

          {credentialsReady && addingConnection ? <div className="space-y-1.5">
            <label htmlFor="workspace-connection-label" className="text-sm font-medium">새 연결 이름</label>
            <Input id="workspace-connection-label" value={connectionLabel} maxLength={80} placeholder="예: 개인 Ollama 서버" disabled={isSubmitting} onChange={(event) => setConnectionLabel(event.target.value)} required />
            {duplicateLabel ? <p className="text-xs text-warning">같은 이름의 계정 연결이 있습니다. 저장된 연결을 선택하거나 다른 이름을 입력해 주세요.</p> : null}
          </div> : null}

          {credentialsReady && addingConnection && selectedProvider?.requiresBaseUrl ? (
            <OllamaBaseUrlField
              id="workspace-base-url"
              value={baseUrl}
              disabled={isSubmitting}
              onChange={(value) => {
                setBaseUrl(value);
                setValidatedKey(undefined);
              }}
            />
          ) : null}

          {credentialsReady && addingConnection ? <div className="space-y-1.5">
            <label htmlFor="workspace-key" className="text-sm font-medium">
              {selectedProvider?.authMode === "optionalApiKey" ? "API key (선택 사항)" : selectedProvider?.authMode === "none" ? "서버 관리 로컬 연결" : "API key"}
            </label>
            <ApiKeyField
              id="workspace-key"
              provider={provider}
              authMode={selectedProvider?.authMode}
              baseUrl={selectedProvider?.requiresBaseUrl ? baseUrl : undefined}
              value={apiKey}
              onChange={(value) => { setApiKey(value); setValidatedKey(undefined); }}
              onValidated={(_result, key) => setValidatedKey(key)}
              disabled={isSubmitting}
            />
          </div> : null}

          <KeyModelSection
            idPrefix="workspace-model"
            hasValidKey={isKeyValid}
            roles={keyModels.roles}
            selections={keyModels.selections}
            onSelect={keyModels.select}
            isLoading={keyModels.isLoading}
            error={keyModels.error}
            disabled={isSubmitting}
          />

          <DialogFooter>
            <Button
              type="submit"
              disabled={
                !name.trim() ||
                !credentialsReady ||
                (addingConnection && !connectionLabel.trim()) ||
                (addingConnection && duplicateLabel) ||
                !isKeyValid ||
                !keyModels.roles ||
                Boolean(keyModels.error) ||
                Object.keys(keyModels.selections).length === 0 ||
                keyModels.isLoading ||
                isSubmitting
              }
            >
              {isSubmitting ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
              만들기
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
