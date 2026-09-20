"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** 입력하던 내용이 있을 때, 닫기 전에 한 번 확인합니다. */
export function DiscardConfirmDialog({
  open,
  onKeepEditing,
  onDiscard,
}: {
  open: boolean;
  onKeepEditing: () => void;
  onDiscard: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onKeepEditing()}>
      <DialogContent showCloseButton={false} className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>입력한 내용을 버릴까요?</DialogTitle>
          <DialogDescription>저장하지 않은 내용은 사라집니다.</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onKeepEditing}>
            계속 편집
          </Button>
          <Button type="button" variant="destructive" onClick={onDiscard}>
            버리기
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
