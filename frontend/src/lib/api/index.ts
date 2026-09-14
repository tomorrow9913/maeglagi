import { USE_MOCKS } from "./config";
import type { MaeglagiApi } from "./contract";
import { httpApi } from "./http";
import { mockApi } from "./mock";

/**
 * 화면에서 쓰는 API 진입점입니다.
 *
 * `NEXT_PUBLIC_USE_MOCKS`로 mock과 실 API를 바꿉니다. 화면 코드는 항상
 * 이 `api`만 import 하고, 두 구현 중 무엇이 붙었는지 신경 쓰지 않습니다.
 */
export const api: MaeglagiApi = USE_MOCKS ? mockApi : httpApi;

/** 현재 mock이 붙어 있는지. 데모 배지 같은 안내 문구에만 씁니다. */
export const isMockMode = USE_MOCKS;

export { ApiError } from "./client";
export type { MaeglagiApi } from "./contract";
export * from "./types";
