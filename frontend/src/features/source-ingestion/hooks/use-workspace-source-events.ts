"use client";

import { useEffect, useRef, useState } from "react";
import { useApi } from "@/lib/api/context";
import type { MaeglagiApi, ProcessingJob } from "@/lib/api";

/** 처리 상태 스트림의 연결 상태. 연속으로 실패하면 "reconnecting"이 되고, 다시 이벤트를 받으면 "connected"로 돌아옵니다. */
export type SourceEventsConnection = "connected" | "reconnecting";

/** 일시적인 끊김(서버가 55초마다 닫는 정상 종료 포함)에는 알리지 않고, 이 횟수만큼 연속 실패하면 알립니다. */
export const RECONNECTING_AFTER_FAILURES = 3;

type Subscriber = {
  ids: Set<string>;
  onJob: (job: ProcessingJob) => void;
  onInvalid?: (sourceId: string, status: number) => void;
  onConnection?: (state: SourceEventsConnection) => void;
};

function permanentStatus(error: unknown): 401 | 403 | 404 | 422 | undefined {
  if (!error || typeof error !== "object" || !("status" in error)) return undefined;
  const status = error.status;
  return status === 401 || status === 403 || status === 404 || status === 422 ? status : undefined;
}

/** One authenticated stream per workspace/100-source batch, shared by mounted views. */
export class SourceEventChannel {
  private subscribers = new Set<Subscriber>();
  private controller?: AbortController;
  private idsKey = "";
  private generation = 0;
  private invalidIds = new Map<string, number>();
  /** 연속 실패 중인 스트림(100개 단위 배치)들. 하나라도 있으면 "reconnecting"입니다. */
  private failing = new Set<object>();
  private connectionState: SourceEventsConnection = "connected";

  constructor(private api: MaeglagiApi, private workspaceId: string) {}

  subscribe(subscriber: Subscriber) {
    this.subscribers.add(subscriber);
    this.sync();
    for (const id of subscriber.ids) {
      const status = this.invalidIds.get(id);
      if (status) subscriber.onInvalid?.(id, status);
    }
    if (this.connectionState !== "connected") subscriber.onConnection?.(this.connectionState);
    return () => { this.subscribers.delete(subscriber); this.sync(); };
  }

  get empty() { return this.subscribers.size === 0; }

  get connection() { return this.connectionState; }

  private markRun(run: object, failing: boolean) {
    if (failing) this.failing.add(run);
    else this.failing.delete(run);
    const next: SourceEventsConnection = this.failing.size > 0 ? "reconnecting" : "connected";
    if (next === this.connectionState) return;
    this.connectionState = next;
    for (const subscriber of this.subscribers) subscriber.onConnection?.(next);
  }

  private sync() {
    const requested = new Set([...this.subscribers].flatMap((subscriber) => [...subscriber.ids]));
    for (const id of this.invalidIds.keys()) if (!requested.has(id)) this.invalidIds.delete(id);
    const ids = [...requested].filter((id) => !this.invalidIds.has(id)).sort();
    const key = ids.join(",");
    if (key === this.idsKey) return;
    this.idsKey = key;
    this.generation++;
    this.controller?.abort();
    this.controller = undefined;
    // 이전 스트림은 모두 끝났으므로 새 스트림의 결과로 다시 판단합니다.
    for (const run of [...this.failing]) this.markRun(run, false);
    if (!ids.length) return;
    const controller = new AbortController();
    this.controller = controller;
    const generation = this.generation;
    for (let index = 0; index < ids.length; index += 100) {
      void this.run(ids.slice(index, index + 100), controller.signal, generation);
    }
  }

  private async run(ids: string[], signal: AbortSignal, generation: number) {
    let retry = 0;
    const run = {};
    while (!signal.aborted && generation === this.generation) {
      try {
        for await (const job of this.api.sourceEvents(this.workspaceId, ids, signal)) {
          if (signal.aborted || generation !== this.generation) break;
          if (!job || typeof job.sourceId !== "string" || typeof job.id !== "string") continue;
          for (const subscriber of this.subscribers) if (subscriber.ids.has(job.sourceId)) subscriber.onJob(job);
          retry = 0;
          this.markRun(run, false);
        }
      } catch (error) {
        if (signal.aborted) break;
        const status = permanentStatus(error);
        if (status && generation === this.generation) {
          this.markRun(run, false);
          if (status !== 401 && status !== 403 && ids.length > 1) {
            const middle = Math.floor(ids.length / 2);
            void this.run(ids.slice(0, middle), signal, generation);
            void this.run(ids.slice(middle), signal, generation);
          } else {
            for (const id of ids) {
              if (this.invalidIds.has(id)) continue;
              this.invalidIds.set(id, status);
              for (const subscriber of this.subscribers) if (subscriber.ids.has(id)) subscriber.onInvalid?.(id, status);
            }
            this.sync();
          }
          return;
        }
        // A failed connection keeps the last rendered status; the next attempt gets fresh auth.
        retry++;
        if (generation === this.generation && retry >= RECONNECTING_AFTER_FAILURES) this.markRun(run, true);
        if (process.env.NODE_ENV !== "test") console.warn("Source event stream disconnected", error);
      }
      if (signal.aborted || generation !== this.generation) break;
      const delay = Math.min(10_000, 500 * 2 ** Math.min(retry, 5));
      await new Promise<void>((resolve) => {
        const finish = () => { signal.removeEventListener("abort", abort); resolve(); };
        const abort = () => { clearTimeout(timer); finish(); };
        const timer = setTimeout(finish, delay);
        signal.addEventListener("abort", abort, { once: true });
      });
    }
    if (generation === this.generation) this.markRun(run, false);
  }
}

const channels = new WeakMap<MaeglagiApi, Map<string, SourceEventChannel>>();

/** 구독한 소스의 처리 이벤트를 전달하고, 스트림 연결 상태를 돌려줍니다. */
export function useWorkspaceSourceEvents(workspaceId: string, sourceIds: string[], onJob: (job: ProcessingJob) => void, enabled = true, onInvalid?: (sourceId: string, status: number) => void): SourceEventsConnection {
  const api = useApi();
  const [connection, setConnection] = useState<SourceEventsConnection>("connected");
  const callback = useRef(onJob);
  callback.current = onJob;
  const invalidCallback = useRef(onInvalid);
  invalidCallback.current = onInvalid;
  const idsKey = [...new Set(sourceIds)].sort().join(",");

  useEffect(() => {
    if (!enabled || !idsKey) return;
    let byWorkspace = channels.get(api);
    if (!byWorkspace) { byWorkspace = new Map(); channels.set(api, byWorkspace); }
    let channel = byWorkspace.get(workspaceId);
    if (!channel) { channel = new SourceEventChannel(api, workspaceId); byWorkspace.set(workspaceId, channel); }
    const activeChannel = channel;
    const unsubscribe = channel.subscribe({ ids: new Set(idsKey.split(",")), onJob: (job) => callback.current(job), onInvalid: (id, status) => invalidCallback.current?.(id, status), onConnection: setConnection });
    return () => {
      unsubscribe();
      // 구독이 끝나면 더 지켜볼 스트림이 없으므로 안내를 거둡니다.
      setConnection("connected");
      if (activeChannel.empty) byWorkspace?.delete(workspaceId);
    };
  }, [api, workspaceId, idsKey, enabled]);

  return connection;
}
