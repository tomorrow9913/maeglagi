import assert from "node:assert/strict";
import test from "node:test";

import { agentAnalysisRequest, sourcePresentation, reviewConfirmationCopy, reviewDisplayState } from "../src/features/source-ingestion/lib/source-presentation.ts";
import { stageLabel, stagesFor } from "../src/features/source-ingestion/lib/processing-stages.ts";

test("agent work stays visible as a paused, inspectable source rather than ready evidence", () => {
  const waiting = sourcePresentation("awaiting_agent", "meeting");
  assert.equal(waiting.label, "에이전트 작업 대기");
  assert.equal(waiting.canOpen, true);
  assert.equal(waiting.needsReview, false);
  assert.equal(waiting.isProcessing, false);
  assert.equal(waiting.evidenceReady, false);
  assert.equal(stageLabel.awaiting_agent, "에이전트 작업 대기");
  assert.deepEqual(stagesFor("document", undefined, "agent"), ["uploaded", "awaiting_agent", "analyzing", "graphing", "completed"]);
});

test("agent handoff identifies the exact source and requires saved completion", () => {
  const request = agentAnalysisRequest("workspace-1", "source-2");
  assert.match(request, /workspace-1/);
  assert.match(request, /source-2/);
  assert.match(request, /submit_analysis/);
  assert.match(request, /phase=done/);
  assert.match(request, /명시적으로 확인/);
  assert.doesNotMatch(request, /API key|Bearer/);
});

test("meeting review instructions preserve the server path and defer agent analysis", () => {
  const server = reviewConfirmationCopy("server");
  const agent = reviewConfirmationCopy("agent");
  assert.match(server.button, /분석 시작/);
  assert.match(server.success, /분석을 시작/);
  assert.doesNotMatch(agent.button, /분석 시작/);
  assert.match(agent.success, /기다립니다/);
  assert.equal(sourcePresentation("awaiting_review", "meeting").needsReview, true);
  assert.equal(sourcePresentation("succeeded", "document").evidenceReady, true);
  assert.equal(reviewDisplayState({ reviewState: "confirmed", status: "failed", analysisMode: "server" }).showServerRetry, true);
  assert.equal(reviewDisplayState({ reviewState: "confirmed", status: "failed", analysisMode: "agent" }).showServerRetry, false);
  assert.equal(reviewDisplayState({ reviewState: "confirmed", status: "failed", analysisMode: "agent" }).showAgentFailure, true);
  assert.equal(reviewDisplayState({ reviewState: "confirmed", status: "awaiting_agent", analysisMode: "agent" }).waitingForAgent, true);
});
