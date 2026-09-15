"use client";

/**
 * 루트 레이아웃까지 실패했을 때의 마지막 방어선입니다.
 *
 * 이 경계는 자체 html/body를 그려야 하고, 전역 스타일도 신뢰할 수 없으므로
 * 인라인 스타일만 씁니다.
 */
export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="ko">
      <body
        style={{
          display: "flex",
          minHeight: "100dvh",
          alignItems: "center",
          justifyContent: "center",
          margin: 0,
          fontFamily: "system-ui, sans-serif",
          background: "#f5f3ee",
          color: "#1c2b26",
        }}
      >
        <main style={{ textAlign: "center", padding: 24 }}>
          <h1 style={{ fontSize: 18, margin: "0 0 8px" }}>앱을 불러오지 못했습니다</h1>
          <p style={{ fontSize: 14, color: "#66736e", margin: "0 0 16px" }}>
            잠시 후 다시 시도해 주세요.
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              padding: "8px 16px",
              borderRadius: 8,
              border: 0,
              background: "#3e715f",
              color: "#fffdf9",
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            다시 시도
          </button>
        </main>
      </body>
    </html>
  );
}
