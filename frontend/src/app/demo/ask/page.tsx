import Link from "next/link";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";

export default function DemoAskPage() {
  return <div className="space-y-5"><PageHeader title="데모 워크스페이스" description="실제 데이터베이스의 프로젝트·참여자·자료·그래프를 읽기 전용으로 살펴보세요." /><div className="flex flex-wrap gap-2"><Button asChild variant="outline"><Link href="/demo/directory">프로젝트와 참여자</Link></Button><Button asChild variant="outline"><Link href="/demo/graph">그래프 보기</Link></Button><Button asChild variant="outline"><Link href="/demo/sources">자료 보기</Link></Button></div><p className="text-sm text-muted-foreground">프로젝트 편집, 업로드, AI 질문은 로그인한 뒤 내 워크스페이스에서 사용할 수 있습니다.</p><Button asChild><Link href="/login">로그인하기</Link></Button></div>;
}
