"use client";

import { useState } from "react";

import { ErrorState, ListSkeleton } from "@/components/common/state-views";
import { PageHeader } from "@/components/layout/page-header";
import { ApiKeyCard } from "@/features/workspace/components/api-key-card";
import { useAsync } from "@/hooks/use-async";
import { BOOTSTRAP_AI_PROVIDERS, withOllamaProvider } from "@/lib/api";
import { useApi } from "@/lib/api/context";

export default function AccountAiPage() {
  const api = useApi();
  const [, setRevision] = useState(0);
  const { data, error, isLoading, reload } = useAsync(
    (signal) => Promise.all([api.listAccountCredentials(signal), api.listProviders(signal)]),
    [],
  );
  const credentials = data?.[0] ?? [];
  const providers = data
    ? withOllamaProvider(data[1].length ? data[1] : BOOTSTRAP_AI_PROVIDERS).map((provider) => ({
        ...provider,
        configured: credentials.some(
          (credential) => credential.provider === provider.id && credential.status === "active",
        ),
      }))
    : [];

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6">
      <PageHeader
        title="계정 AI 연결"
        description="내 개인 API key를 관리합니다. 워크스페이스 공용 연결이 없을 때 대체하여 사용합니다."
      />
      {isLoading && !data ? (
        <ListSkeleton count={1} className="h-40" label="AI 연결을 불러오는 중" />
      ) : error && !data ? (
        <ErrorState error={error} onRetry={reload} />
      ) : (
        <ApiKeyCard
          credentials={credentials}
          providers={providers}
          onUpdated={() => {
            setRevision((value) => value + 1);
            reload();
          }}
        />
      )}
    </main>
  );
}
