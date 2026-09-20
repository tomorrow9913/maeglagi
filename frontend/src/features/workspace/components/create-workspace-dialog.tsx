"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import { ListSkeleton } from "@/components/common/state-views";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAsync } from "@/hooks/use-async";
import { BOOTSTRAP_AI_PROVIDERS, pickDefaultProvider, withOllamaProvider } from "@/lib/api";
import { useApi } from "@/lib/api/context";
import type { LlmProvider, Workspace, WorkspaceSecrets } from "@/lib/api";
import { toUserMessage } from "@/lib/api/error-message";

import { AI_CONNECTION_EXPLAINER, connectionLabelPlaceholder } from "../lib/connection-copy";
import { firstUnmetRequirement } from "../lib/create-requirements";
import { bindCredentialToSelections } from "../lib/model-roles";
import { useKeyModels } from "../hooks/use-key-models";
import { ApiKeyField } from "./api-key-field";
import { KeyModelSection } from "./key-model-section";
import { ProviderDefaults } from "./provider-defaults";
import { ProviderSelect } from "./provider-select";

/** 백엔드 CreateWorkspaceRequest.name의 최대 길이 */
const WORKSPACE_NAME_MAX_LENGTH = 120;

/**
 * 계정의 AI 연결을 선택하고 워크스페이스의 모델 역할을 정합니다.
 * 처음 쓰는 계정에는 연결을 추가한 뒤 그 연결을 사용합니다.
 */
export function CreateWorkspaceDialog({
  onCreated,
  triggerLabel = "새 워크스페이스",
}: {
  onCreated: (created: Workspace, mode: "agent" | "service") => void;
  triggerLabel?: string;
}) {
  const api = useApi();
  const [isOpen, setIsOpen] = useState(false);
  const [name, setName] = useState("");
  const [setupMode, setSetupMode] = useState<"agent" | "service">("agent");
  // 서버가 지원하는 AI 공급자를 받아 보여줍니다. 받지 못하면 대비 목록으로 물러섭니다.
  // 처리 방식을 바꾸면 이전 방식의 빈 결과가 남지 않도록 resetKey로 비웁니다.
  const { data: catalog, isLoading: catalogLoading } = useAsync(
    (signal) => (setupMode === "service" ? api.listProviders(signal) : Promise.resolve([])),
    [setupMode],
    { resetKey: setupMode },
  );
  const {
    data: savedCredentials,
    error: credentialsError,
    isLoading: credentialsLoading,
    reload: reloadCredentials,
  } = useAsync(
    (signal) =>
      setupMode === "service" ? api.listAccountCredentials(signal) : Promise.resolve([]),
    [setupMode],
    { resetKey: setupMode },
  );
  // 공급자 목록과 저장된 연결을 둘 다 받은 뒤에 기본 선택을 정합니다. 먼저 온 쪽만으로 고르면
  // 나중에 온 응답이 선택을 바꿔 화면이 깜빡입니다.
  const isServiceLoading =
    setupMode === "service" &&
    ((catalogLoading && !catalog) || (credentialsLoading && !savedCredentials));
  const providers = withOllamaProvider(
    catalog && catalog.length > 0 ? catalog : BOOTSTRAP_AI_PROVIDERS,
  );
  const [chosen, setChosen] = useState<LlmProvider>();
  const accountDefaultProvider =
    savedCredentials?.find((item) => item.isDefault && item.status === "active")?.provider ??
    savedCredentials?.find((item) => item.status === "active")?.provider;
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
  const accountCredentials =
    newlySavedCredential && !savedCredentials?.some((item) => item.id === newlySavedCredential.id)
      ? [...(savedCredentials ?? []), newlySavedCredential]
      : (savedCredentials ?? []);
  const credentialsReady = savedCredentials !== undefined && !credentialsError;
  const availableCredentials = accountCredentials.filter(
    (item) => item.provider === provider && item.status === "active",
  );
  const duplicateLabel = accountCredentials.some(
    (item) => item.provider === provider && item.label === connectionLabel.trim(),
  );
  // 고른 연결이 없으면 계정의 기본 연결을, 그것도 없으면 첫 연결을 씁니다.
  const selectedCredential =
    availableCredentials.find((item) => item.id === chosenCredentialId) ??
    availableCredentials.find((item) => item.isDefault) ??
    availableCredentials[0];
  const addingConnection = credentialMode === "new" || availableCredentials.length === 0;
  // 검증을 통과한 키. 이 키로만 모델 목록을 받아 오므로, 없으면 아직 확인 전이라는 뜻입니다.
  const [validatedKey, setValidatedKey] = useState<string>();
  const isKeyValid =
    credentialsReady &&
    (addingConnection ? validatedKey !== undefined : Boolean(selectedCredential));
  const [isSubmitting, setIsSubmitting] = useState(false);
  // 연결 저장은 됐는데 워크스페이스 생성이 실패한 경우. 다시 입력할 필요가 없다는 것을 알려줍니다.
  const [connectionSavedOnly, setConnectionSavedOnly] = useState(false);
  const selectedProvider = providers.find((item) => item.id === provider);
  const needsBaseUrl = Boolean(selectedProvider?.requiresBaseUrl);
  const keyModels = useKeyModels(
    provider,
    setupMode === "service" && addingConnection ? validatedKey : undefined,
    selectedProvider?.defaultModels,
    setupMode === "service" && addingConnection && needsBaseUrl ? baseUrl : undefined,
    setupMode === "service" && !addingConnection ? selectedCredential?.id : undefined,
  );

  // 버튼의 비활성 조건과 버튼 위 안내가 같은 판단에서 나옵니다.
  const unmetRequirement = firstUnmetRequirement({
    name,
    setupMode,
    credentialsReady,
    credentialsFailed: Boolean(credentialsError),
    addingConnection,
    connectionLabel,
    duplicateLabel,
    needsBaseUrl,
    baseUrl,
    isConnectionValid: isKeyValid,
    modelsLoading: keyModels.isLoading,
    modelsFailed: Boolean(keyModels.error),
    hasRoles: Boolean(keyModels.roles),
    selectionCount: Object.keys(keyModels.selections).length,
  });

  const clearConnectionInputs = () => {
    setValidatedKey(undefined);
    setApiKey("");
  };

  const reset = () => {
    setName("");
    setSetupMode("agent");
    setChosen(undefined);
    setBaseUrl("");
    setConnectionLabel("");
    setCredentialMode("saved");
    setChosenCredentialId(undefined);
    setNewlySavedCredential(undefined);
    setConnectionSavedOnly(false);
    clearConnectionInputs();
  };

  const submit = async () => {
    if (isSubmitting || unmetRequirement) return;
    setIsSubmitting(true);
    let savedConnection = false;
    try {
      let created: Workspace;
      if (setupMode === "agent") {
        created = await api.createWorkspace({ name: name.trim() });
      } else {
        let credentialId = selectedCredential?.id;
        if (addingConnection) {
          const saved = await api.createAccountCredential({
            provider,
            label: connectionLabel.trim(),
            apiKey: selectedProvider?.authMode === "none" ? "" : apiKey.trim(),
            ...(needsBaseUrl ? { baseUrl: baseUrl.trim() } : {}),
          });
          savedConnection = true;
          credentialId = saved.id;
          setNewlySavedCredential(saved);
          setChosenCredentialId(saved.id);
          setCredentialMode("saved");
          clearConnectionInputs();
          reloadCredentials();
        }
        const models = bindCredentialToSelections(keyModels.selections, provider, credentialId!);
        created = await api.createWorkspace({ name: name.trim(), credentialId, models });
      }

      toast.success(`${created.name} 워크스페이스를 만들었습니다.`);
      onCreated(created, setupMode);
      setIsOpen(false);
      reset();
    } catch (error) {
      if (savedConnection) setConnectionSavedOnly(true);
      toast.error(toUserMessage(error, "워크스페이스를 만들지 못했습니다."));
    } finally {
      setIsSubmitting(false);
    }
  };

  const keyLabel =
    selectedProvider?.authMode === "optionalApiKey"
      ? "API key (선택 사항)"
      : selectedProvider?.authMode === "none"
        ? "서버에서 관리하는 연결"
        : "API key";

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(next) => {
        // 만드는 중에 닫히면 성공한 뒤 예고 없이 화면이 바뀌므로, 끝날 때까지 열어 둡니다.
        if (!next && isSubmitting) return;
        setIsOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="size-4" aria-hidden />
          {triggerLabel}
        </Button>
      </DialogTrigger>

      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-md"
        showCloseButton={!isSubmitting}
      >
        <DialogHeader>
          <DialogTitle>새 워크스페이스</DialogTitle>
          <DialogDescription>
            맥락을 모을 공간을 만듭니다. AI 연결은 나중에 추가할 수 있습니다.
          </DialogDescription>
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
              maxLength={WORKSPACE_NAME_MAX_LENGTH}
              placeholder="예: 제품팀 주간회의"
              disabled={isSubmitting}
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <fieldset className="space-y-2" disabled={isSubmitting}>
            <legend className="text-sm font-medium">처리 방식</legend>
            <div className="grid grid-cols-2 gap-2">
              <Button
                type="button"
                variant={setupMode === "agent" ? "secondary" : "outline"}
                aria-pressed={setupMode === "agent"}
                onClick={() => setSetupMode("agent")}
              >
                내 에이전트 + MCP
              </Button>
              <Button
                type="button"
                variant={setupMode === "service" ? "secondary" : "outline"}
                aria-pressed={setupMode === "service"}
                onClick={() => setSetupMode("service")}
              >
                서비스 AI 연결
              </Button>
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {setupMode === "agent"
                ? "AI 공급자의 API key 없이 시작합니다. 만든 뒤 계정 MCP 연결에서 토큰을 발급해 쓰고 있는 에이전트에 연결해 주세요. 오디오를 처리하려면 에이전트에 음성 처리 기능이 필요합니다."
                : AI_CONNECTION_EXPLAINER}
            </p>
          </fieldset>

          {setupMode === "service" && isServiceLoading ? (
            <ListSkeleton
              count={2}
              className="h-9"
              label="AI 공급자와 저장된 AI 연결을 불러오는 중"
            />
          ) : null}

          {setupMode === "service" && !isServiceLoading ? (
            <>
              <div className="space-y-1.5">
                <label htmlFor="workspace-provider" className="text-sm font-medium">
                  AI 공급자
                </label>
                <ProviderSelect
                  id="workspace-provider"
                  value={provider}
                  onChange={(next) => {
                    // 다른 공급자에 이전 키로 모델을 요청하지 않도록, 키는 다시 확인될 때까지 비웁니다.
                    clearConnectionInputs();
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
                {!isKeyValid ? (
                  <ProviderDefaults provider={selectedProvider} className="pt-1" />
                ) : null}
              </div>

              {credentialsError ? (
                <div className="space-y-2 text-xs text-destructive" role="alert">
                  <p>
                    계정 AI 연결을 불러오지 못했습니다. 같은 연결을 두 번 추가하지 않도록 다시 불러와
                    주세요.
                  </p>
                  <Button type="button" size="sm" variant="outline" onClick={reloadCredentials}>
                    다시 시도
                  </Button>
                </div>
              ) : null}

              {credentialsReady && availableCredentials.length > 0 ? (
                <div className="space-y-1.5">
                  {addingConnection ? (
                    <>
                      <p className="text-sm font-medium">계정 AI 연결</p>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={isSubmitting}
                        onClick={() => {
                          setCredentialMode("saved");
                          clearConnectionInputs();
                        }}
                      >
                        저장된 연결 선택
                      </Button>
                    </>
                  ) : (
                    <>
                      <label htmlFor="workspace-credential" className="text-sm font-medium">
                        계정 AI 연결
                      </label>
                      <Select
                        value={selectedCredential?.id}
                        onValueChange={(id) => setChosenCredentialId(id)}
                      >
                        <SelectTrigger
                          id="workspace-credential"
                          className="w-full"
                          disabled={isSubmitting}
                        >
                          <SelectValue placeholder="연결을 골라 주세요" />
                        </SelectTrigger>
                        <SelectContent>
                          {availableCredentials.map((credential) => (
                            <SelectItem key={credential.id} value={credential.id}>
                              {credential.label}
                              {credential.baseUrl ? ` · ${credential.baseUrl}` : ""}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={isSubmitting}
                        onClick={() => {
                          setCredentialMode("new");
                          setChosenCredentialId(undefined);
                        }}
                      >
                        연결 추가
                      </Button>
                    </>
                  )}
                  <p className="text-xs text-muted-foreground">
                    연결은 계정에 저장되어 다른 워크스페이스에서도 쓸 수 있습니다.
                  </p>
                </div>
              ) : null}

              {credentialsReady && addingConnection ? (
                <>
                  <div className="space-y-1.5">
                    <label htmlFor="workspace-connection-label" className="text-sm font-medium">
                      연결 이름
                    </label>
                    <Input
                      id="workspace-connection-label"
                      value={connectionLabel}
                      maxLength={80}
                      placeholder={connectionLabelPlaceholder(provider)}
                      disabled={isSubmitting}
                      onChange={(event) => setConnectionLabel(event.target.value)}
                      aria-describedby={duplicateLabel ? "workspace-connection-label-error" : undefined}
                      aria-invalid={duplicateLabel || undefined}
                      required
                    />
                    {duplicateLabel ? (
                      <p id="workspace-connection-label-error" className="text-xs text-warning">
                        같은 이름의 AI 연결이 있습니다. 저장된 연결을 선택하거나 다른 이름을 입력해
                        주세요.
                      </p>
                    ) : null}
                  </div>

                  <ApiKeyField
                    id="workspace-key"
                    provider={provider}
                    authMode={selectedProvider?.authMode}
                    label={keyLabel}
                    value={apiKey}
                    baseUrlField={
                      needsBaseUrl
                        ? {
                            id: "workspace-base-url",
                            value: baseUrl,
                            onChange: (value) => {
                              setBaseUrl(value);
                              setValidatedKey(undefined);
                            },
                          }
                        : undefined
                    }
                    onChange={(value) => {
                      setApiKey(value);
                      setValidatedKey(undefined);
                    }}
                    onValidated={(_result, key) => setValidatedKey(key)}
                    disabled={isSubmitting}
                  />
                </>
              ) : null}

              <KeyModelSection
                idPrefix="workspace-model"
                hasValidKey={isKeyValid}
                roles={keyModels.roles}
                selections={keyModels.selections}
                onSelect={keyModels.select}
                isLoading={keyModels.isLoading}
                error={keyModels.error}
                onRetry={keyModels.reload}
                isOllama={provider === "ollama"}
                disabled={isSubmitting}
              />
            </>
          ) : null}

          {connectionSavedOnly ? (
            <p role="status" className="text-xs text-muted-foreground">
              AI 연결은 저장했습니다. 워크스페이스만 다시 만들어 주세요.
            </p>
          ) : null}
          {unmetRequirement && !isSubmitting ? (
            <p id="workspace-create-requirement" className="text-xs text-muted-foreground">
              {unmetRequirement}
            </p>
          ) : null}

          <DialogFooter>
            <Button
              type="submit"
              disabled={Boolean(unmetRequirement)}
              pending={isSubmitting}
              pendingLabel="만드는 중…"
              aria-describedby={
                unmetRequirement && !isSubmitting ? "workspace-create-requirement" : undefined
              }
            >
              만들기
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
