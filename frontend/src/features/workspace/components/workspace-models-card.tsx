"use client";

import { useEffect, useState } from "react";
import { Cpu } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, ListSkeleton } from "@/components/common/state-views";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { useAsync } from "@/hooks/use-async";
import { useApi } from "@/lib/api/context";
import type {
  AiProvider,
  ModelOption,
  ModelRole,
  ModelSelections,
  RoleModels,
  WorkspaceModels,
  WorkspaceSecrets,
} from "@/lib/api";

import { sameSelection } from "../lib/model-roles";
import { ModelPicker } from "./model-picker";
import { toUserMessage } from "@/lib/api/error-message";

function savedSelections(roles: RoleModels[]): ModelSelections {
  const selections: ModelSelections = {};
  for (const entry of roles) {
    if (entry.selected) selections[entry.role] = entry.selected;
  }
  return selections;
}

/**
 * 워크스페이스가 용도별로 쓸 모델을 고르고 저장합니다.
 *
 * 저장된 모든 AI 연결의 활성 키로 사용할 수 있는 모델을 함께 보여줍니다.
 * 연결이 바뀌면 부모가 `revision`을 올려 목록을 다시 불러옵니다. Ollama는 모델을 하나씩
 * 점검해 오래 걸릴 수 있으므로, 다시 받는 동안에도 이전 목록을 흐리게 남겨 둡니다.
 */
export function WorkspaceModelsCard({
  workspaceId,
  providers,
  credentials,
  revision = 0,
}: {
  workspaceId: string;
  providers: AiProvider[];
  credentials: WorkspaceSecrets[];
  /** 계정의 AI 연결이 바뀔 때마다 올라가는 값 */
  revision?: number;
}) {
  const api = useApi();
  const { data, error, isLoading, isRefetching, reload } = useAsync(
    (signal) => api.getWorkspaceModels(workspaceId, undefined, signal),
    [workspaceId, revision],
    { resetKey: workspaceId },
  );
  const includesOllama = credentials.some(
    (item) => item.provider === "ollama" && item.status === "active",
  );
  const loadingCopy = includesOllama
    ? "Ollama 서버의 모델을 하나씩 확인하고 있어요. 모델이 많으면 오래 걸려요."
    : "쓸 수 있는 모델을 불러오고 있어요";

  const [models, setModels] = useState<WorkspaceModels>();
  const [selections, setSelections] = useState<ModelSelections>({});
  const [editedRoles, setEditedRoles] = useState<ModelRole[]>([]);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!data) return;
    setModels(data);
    setSelections(savedSelections(data.roles));
    setEditedRoles([]);
  }, [data]);

  // 바뀐 용도만 보냅니다. 잠긴 용도는 애초에 바꿀 수 없으니 비교에서 뺍니다.
  const changed: ModelSelections = {};
  for (const entry of models?.roles ?? []) {
    const chosen = selections[entry.role];
    if (
      chosen &&
      editedRoles.includes(entry.role) &&
      !entry.locked &&
      !sameSelection(chosen, entry.selected ?? undefined)
    ) {
      changed[entry.role] = chosen;
    }
  }
  const hasChanges = Object.keys(changed).length > 0;

  const save = async () => {
    setIsSaving(true);
    try {
      const next = await api.updateWorkspaceModels(workspaceId, changed);
      setModels(next);
      setSelections(savedSelections(next.roles));
      setEditedRoles([]);
      toast.success("사용할 모델을 저장했습니다.");
    } catch (cause) {
      toast.error(toUserMessage(cause, "모델을 저장하지 못했습니다."));
    } finally {
      setIsSaving(false);
    }
  };

  const select = (role: ModelRole, option: ModelOption) => {
    setSelections((current) => ({ ...current, [role]: option }));
    setEditedRoles((current) => (current.includes(role) ? current : [...current, role]));
  };

  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-start gap-3">
        <Cpu className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-medium">사용할 모델</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            계정의 AI 연결로 쓸 수 있는 모델 중에서 용도마다 고릅니다. 이 선택은 현재 워크스페이스에만
            적용됩니다. 가격이 낮은 모델부터 보여주고, 가격을 알 수 없는 모델은 뒤에 나옵니다.
          </p>

          <div className="mt-4 space-y-3">
            {isLoading && !models ? (
              includesOllama ? (
                <div role="status" className="space-y-3">
                  <p className="flex items-start gap-2 text-xs text-muted-foreground">
                    <Spinner className="mt-0.5 size-3" />
                    {loadingCopy}
                  </p>
                  <div className="space-y-3" aria-hidden>
                    <Skeleton className="h-16 w-full rounded-xl" />
                    <Skeleton className="h-16 w-full rounded-xl" />
                  </div>
                </div>
              ) : (
                <ListSkeleton count={2} className="h-16" label={loadingCopy} />
              )
            ) : error && !models ? (
              <ErrorState error={error} onRetry={reload} />
            ) : models ? (
              <>
                {isRefetching ? (
                  <p role="status" className="flex items-start gap-2 text-xs text-muted-foreground">
                    <Spinner className="mt-0.5 size-3" />
                    {includesOllama
                      ? loadingCopy
                      : "바뀐 AI 연결로 모델 목록을 다시 불러오고 있어요"}
                  </p>
                ) : error ? (
                  <ErrorState
                    compact
                    error={error}
                    onRetry={reload}
                    title="모델 목록을 새로 불러오지 못했습니다"
                  />
                ) : null}
                <form
                  className={isRefetching ? "space-y-4 opacity-60" : "space-y-4"}
                  aria-busy={isRefetching || undefined}
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (hasChanges && !isRefetching) void save();
                  }}
                >
                  <ModelPicker
                    idPrefix="settings-model"
                    roles={models.roles}
                    value={selections}
                    onChange={select}
                    disabled={isSaving || isRefetching}
                    providers={providers}
                    credentials={credentials}
                    showSavedStatus
                    includesOllama={includesOllama}
                  />
                  <Button
                    type="submit"
                    size="sm"
                    disabled={!hasChanges || isRefetching}
                    pending={isSaving}
                    pendingLabel="저장하는 중…"
                  >
                    저장
                  </Button>
                </form>
              </>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
