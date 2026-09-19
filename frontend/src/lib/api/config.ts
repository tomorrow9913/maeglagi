/** API 호출 대상과 mock 전환을 한 곳에서 결정합니다. */

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

/**
 * mock 사용 여부.
 *
 * 명시적으로 `NEXT_PUBLIC_USE_MOCKS=true`를 설정한 로컬 개발에서만 fixture를
 * 사용합니다. 기본값은 실제 API이며 공개 데모는 별도의 읽기 전용 API를 사용합니다.
 * 빌드 타임에 인라인되므로 `process.env.X`를 통째로 비교해야 합니다.
 */
export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "true";

/** mock이 흉내 내는 네트워크 지연(ms). 로딩 상태를 실제처럼 확인하려고 둡니다. */
export const MOCK_LATENCY_MS = 350;
