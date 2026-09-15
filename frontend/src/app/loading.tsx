import { ListSkeleton } from "@/components/common/state-views";

/** 라우트 전환 중 흰 화면 대신 자리를 채웁니다. */
export default function Loading() {
  return (
    <main className="mx-auto w-full max-w-6xl px-5 py-10">
      <ListSkeleton count={3} className="h-28" />
    </main>
  );
}
