import { PageHeader } from "@/components/layout/page-header";
import { DemoAuthGuidance } from "@/components/layout/demo-auth-guidance";

export default function DemoSettingsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="내 워크스페이스로 가져가기"
        description="데모에는 바꿀 설정이 없습니다. AI 연결과 모델은 복사한 내 워크스페이스의 설정에서 정할 수 있어요."
      />
      <DemoAuthGuidance />
    </div>
  );
}
