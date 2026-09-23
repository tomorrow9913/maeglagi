"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";

import { ErrorState, ListSkeleton } from "@/components/common/state-views";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAsync } from "@/hooks/use-async";
import { useApi } from "@/lib/api/context";

export function WorkspaceSharingCard({ workspaceId }: { workspaceId: string }) {
  const api = useApi();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "editor" | "viewer">("editor");
  const [busy, setBusy] = useState(false);
  const workspace = useAsync((signal) => api.getWorkspace(workspaceId, signal), [workspaceId]);
  const members = useAsync(
    (signal) => api.listWorkspaceMembers(workspaceId, signal),
    [workspaceId],
  );
  const canManage = workspace.data?.role === "owner" || workspace.data?.role === "admin";

  const invite = async () => {
    if (!email.trim()) return;
    setBusy(true);
    try {
      await api.inviteWorkspaceMember(workspaceId, { email: email.trim(), role });
      setEmail("");
      toast.success("워크스페이스 멤버를 초대했습니다.");
      members.reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "초대하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const changeRole = async (memberId: string, nextRole: "admin" | "editor" | "viewer") => {
    try {
      await api.updateWorkspaceMember(workspaceId, memberId, nextRole);
      toast.success("멤버 권한을 변경했습니다.");
      members.reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "권한을 변경하지 못했습니다.");
    }
  };

  const remove = async (memberId: string) => {
    try {
      await api.removeWorkspaceMember(workspaceId, memberId);
      toast.success("멤버를 제거했습니다.");
      members.reload();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "멤버를 제거하지 못했습니다.");
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">워크스페이스 공유</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {canManage ? (
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              aria-label="초대 이메일"
              placeholder="team@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <Select value={role} onValueChange={(value) => setRole(value as typeof role)}>
              <SelectTrigger className="sm:w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="admin">관리자</SelectItem>
                <SelectItem value="editor">편집자</SelectItem>
                <SelectItem value="viewer">조회자</SelectItem>
              </SelectContent>
            </Select>
            <Button disabled={busy || !email.trim()} onClick={() => void invite()}>
              초대
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            멤버 초대와 권한 변경은 소유자와 관리자만 할 수 있습니다.
          </p>
        )}
        {members.error ? (
          <ErrorState error={members.error} onRetry={members.reload} />
        ) : members.isLoading && !members.data ? (
          <ListSkeleton count={2} label="멤버를 불러오는 중" />
        ) : (
          <ul className="divide-y rounded-md border">
            {(members.data ?? []).map((member) => (
              <li
                key={member.id}
                className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
              >
                <span className="min-w-0 truncate">{member.email || "워크스페이스 소유자"}</span>
                <div className="flex items-center gap-2">
                  {canManage && member.role !== "owner" ? (
                    <Select
                      value={member.role}
                      onValueChange={(value) =>
                        void changeRole(member.id, value as "admin" | "editor" | "viewer")
                      }
                    >
                      <SelectTrigger className="h-8 w-28" aria-label={`${member.email} 권한`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="admin">관리자</SelectItem>
                        <SelectItem value="editor">편집자</SelectItem>
                        <SelectItem value="viewer">조회자</SelectItem>
                      </SelectContent>
                    </Select>
                  ) : (
                    <Badge variant="secondary">{member.role}</Badge>
                  )}
                  <span className="text-xs text-muted-foreground">
                    {member.joinedAt ? "참여 중" : "초대 대기"}
                  </span>
                  {canManage && member.role !== "owner" ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`${member.email} 제거`}
                      onClick={() => void remove(member.id)}
                    >
                      <Trash2 className="size-4" aria-hidden />
                    </Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
