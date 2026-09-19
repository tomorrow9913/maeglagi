"use client";

import { useEffect, useState } from "react";
import { Cpu, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, ListSkeleton } from "@/components/common/state-views";
import { Button } from "@/components/ui/button";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import type { ModelOption, ModelRole, ModelSelections, WorkspaceModels } from "@/lib/api";

import { initialSelections, sameSelection } from "../lib/model-roles";
import { ModelPicker } from "./model-picker";

/**
 * 워크스페이스가 용도별로 쓸 모델을 고르고 저장합니다.
 *
 * 고를 수 있는 목록은 저장된 키로 서버가 공급자에서 받아 온 것입니다. 키를 교체하면 목록이
 * 달라지므로 부모가 `key`를 바꿔 이 카드를 다시 마운트합니다.
 */
export function WorkspaceModelsCard({ workspaceId }: { workspaceId: string }) {
  const { data, error, isLoading, reload } = useAsync(
    (signal) => api.getWorkspaceModels(workspaceId, signal),
    [workspaceId],
  );

  // 저장 직후에는 다시 불러오지 않고 서버가 돌려준 결과를 그대로 씁니다.
  const [models, setModels] = useState<WorkspaceModels>();
  const [selections, setSelections] = useState<ModelSelections>({});
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!data) return;
    setModels(data);
    setSelections(initialSelections(data.roles));
  }, [data]);

  // 바뀐 용도만 보냅니다. 잠긴 용도는 애초에 바꿀 수 없으니 비교에서 뺍니다.
  const changed: ModelSelections = {};
  for (const entry of models?.roles ?? []) {
    const chosen = selections[entry.role];
    if (chosen && !entry.locked && !sameSelection(chosen, entry.selected ?? undefined)) {
      changed[entry.role] = chosen;
    }
  }
  const hasChanges = Object.keys(changed).length > 0;

  const save = async () => {
    setIsSaving(true);
    try {
      const next = await api.updateWorkspaceModels(workspaceId, changed);
      setModels(next);
      setSelections(initialSelections(next.roles));
      toast.success("사용할 모델을 저장했습니다.");
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "모델을 저장하지 못했습니다.");
    } finally {
      setIsSaving(false);
    }
  };

  const select = (role: ModelRole, option: ModelOption) =>
    setSelections((current) => ({ ...current, [role]: option }));

  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-start gap-3">
        <Cpu className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-medium">사용할 모델</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            등록한 키로 쓸 수 있는 모델 중에서 용도마다 고릅니다. 가격을 확인할 수 있는
            모델은 낮은 순서로, 가격 정보가 없는 모델은 뒤에 표시됩니다.
          </p>

          <div className="mt-4">
            {isLoading ? (
              <ListSkeleton count={2} className="h-16" />
            ) : error ? (
              <ErrorState error={error} onRetry={reload} />
            ) : models ? (
              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void save();
                }}
              >
                <ModelPicker
                  idPrefix="settings-model"
                  roles={models.roles}
                  value={selections}
                  onChange={select}
                  disabled={isSaving}
                />
                <Button type="submit" size="sm" disabled={!hasChanges || isSaving}>
                  {isSaving ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
                  저장
                </Button>
              </form>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
