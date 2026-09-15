/** API 호출 대상과 mock 전환을 한 곳에서 결정합니다. */

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

/**
 * mock 사용 여부.
 *
 * 백엔드가 준비되기 전에는 `NEXT_PUBLIC_USE_MOCKS=true`로 두고 모든 화면을
 * 개발합니다. 값을 `false`로 바꾸면 같은 인터페이스로 실 API를 호출합니다.
 * 빌드 타임에 인라인되므로 `process.env.X`를 통째로 비교해야 합니다.
 */
export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS !== "false";

/** mock이 흉내 내는 네트워크 지연(ms). 로딩 상태를 실제처럼 확인하려고 둡니다. */
export const MOCK_LATENCY_MS = 350;
