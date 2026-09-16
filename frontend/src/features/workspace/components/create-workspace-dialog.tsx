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
import { api, BOOTSTRAP_AI_PROVIDERS, DEFAULT_BOOTSTRAP_PROVIDER } from "@/lib/api";
import type { LlmProvider, Workspace } from "@/lib/api";

import { ApiKeyField } from "./api-key-field";
import { ProviderSelect } from "./provider-select";

/**
 * 워크스페이스를 만들면서 BYOK 키를 함께 등록합니다.
 *
 * 키가 검증을 통과해야 생성 버튼이 열립니다. 키 없이 만든 워크스페이스는
 * 어차피 분석을 돌릴 수 없기 때문입니다.
 */
export function CreateWorkspaceDialog({ onCreated }: { onCreated: (created: Workspace) => void }) {
  const [isOpen, setIsOpen] = useState(false);
  const [name, setName] = useState("");
  const [provider, setProvider] = useState<LlmProvider>(DEFAULT_BOOTSTRAP_PROVIDER);
  const [apiKey, setApiKey] = useState("");
  const [isKeyValid, setIsKeyValid] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const reset = () => {
    setName("");
    setProvider(DEFAULT_BOOTSTRAP_PROVIDER);
    setApiKey("");
    setIsKeyValid(false);
  };

  const submit = async () => {
    setIsSubmitting(true);
    try {
      const created = await api.createWorkspace({
        name,
        llmProvider: provider,
        llmApiKey: apiKey,
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

      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>새 워크스페이스</DialogTitle>
          <DialogDescription>
            맥락을 모을 공간을 만들고 분석에 쓸 LLM 키를 등록합니다.
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
              placeholder="예: 맥락이 PoC"
              disabled={isSubmitting}
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="workspace-provider" className="text-sm font-medium">
              LLM provider
            </label>
            <ProviderSelect
              id="workspace-provider"
              value={provider}
              onChange={setProvider}
              providers={BOOTSTRAP_AI_PROVIDERS}
              disabled={isSubmitting}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="workspace-key" className="text-sm font-medium">
              API key
            </label>
            <ApiKeyField
              id="workspace-key"
              provider={provider}
              value={apiKey}
              onChange={setApiKey}
              onValidated={(result) => setIsKeyValid(Boolean(result?.valid))}
              disabled={isSubmitting}
            />
          </div>

          <DialogFooter>
            <Button type="submit" disabled={!name.trim() || !isKeyValid || isSubmitting}>
              {isSubmitting ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
              만들기
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
