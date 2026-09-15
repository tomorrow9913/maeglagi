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
import { api } from "@/lib/api";
import type { Workspace } from "@/lib/api";

/**
 * 워크스페이스를 먼저 만들고, BYOK 키는 설정 화면에서 별도로 등록합니다.
 */
export function CreateWorkspaceDialog({ onCreated }: { onCreated: (created: Workspace) => void }) {
  const [isOpen, setIsOpen] = useState(false);
  const [name, setName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const reset = () => {
    setName("");
  };

  const submit = async () => {
    setIsSubmitting(true);
    try {
      const created = await api.createWorkspace({ name });

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
            맥락을 모을 공간을 만듭니다. LLM 키는 설정에서 등록할 수 있습니다.
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

          <DialogFooter>
            <Button type="submit" disabled={!name.trim() || isSubmitting}>
              {isSubmitting ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
              만들기
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
