import Link from "next/link";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";

export default function DemoSettingsPage() {
  return <div className="space-y-4"><PageHeader title="데모 설정" description="공개 데모는 읽기 전용입니다." /><p className="text-sm text-muted-foreground">AI 연결과 모델은 내 워크스페이스에서 설정할 수 있습니다.</p><Button asChild><Link href="/login">로그인하기</Link></Button></div>;
}
