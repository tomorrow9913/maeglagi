"use client";

import { useEffect, useRef } from "react";
import { useApi } from "@/lib/api/context";
import type { MaeglagiApi, ProcessingJob } from "@/lib/api";

type Subscriber = { ids: Set<string>; onJob: (job: ProcessingJob) => void; onInvalid?: (sourceId: string, status: number) => void };

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

  constructor(private api: MaeglagiApi, private workspaceId: string) {}

  subscribe(subscriber: Subscriber) {
    this.subscribers.add(subscriber);
    this.sync();
    for (const id of subscriber.ids) {
      const status = this.invalidIds.get(id);
      if (status) subscriber.onInvalid?.(id, status);
    }
    return () => { this.subscribers.delete(subscriber); this.sync(); };
  }

  get empty() { return this.subscribers.size === 0; }

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
    while (!signal.aborted && generation === this.generation) {
      try {
        for await (const job of this.api.sourceEvents(this.workspaceId, ids, signal)) {
          if (signal.aborted || generation !== this.generation) break;
          if (!job || typeof job.sourceId !== "string" || typeof job.id !== "string") continue;
          for (const subscriber of this.subscribers) if (subscriber.ids.has(job.sourceId)) subscriber.onJob(job);
          retry = 0;
        }
      } catch (error) {
        if (signal.aborted) break;
        const status = permanentStatus(error);
        if (status && generation === this.generation) {
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
  }
}

const channels = new WeakMap<MaeglagiApi, Map<string, SourceEventChannel>>();

export function useWorkspaceSourceEvents(workspaceId: string, sourceIds: string[], onJob: (job: ProcessingJob) => void, enabled = true, onInvalid?: (sourceId: string, status: number) => void) {
  const api = useApi();
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
    const unsubscribe = channel.subscribe({ ids: new Set(idsKey.split(",")), onJob: (job) => callback.current(job), onInvalid: (id, status) => invalidCallback.current?.(id, status) });
    return () => {
      unsubscribe();
      if (activeChannel.empty) byWorkspace?.delete(workspaceId);
    };
  }, [api, workspaceId, idsKey, enabled]);
}
