import { ImageResponse } from "next/og";

/**
 * iOS 홈 화면용 앱 아이콘입니다.
 *
 * apple-icon은 정적 파일 규칙상 SVG를 받지 않아 빌드 시점에 PNG로 굽습니다.
 * 형태는 `icon.svg`와 같은 심볼이고, 여백만 홈 화면 기준에 맞춰 조금 더 줍니다.
 */
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

const MARK = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none" stroke="#fffdf9" stroke-width="2.8" stroke-linecap="round"><circle cx="16" cy="13.5" r="8.5"/><path d="M11.8 20.9C13.6 24.4 19 25.4 22.4 28.8"/><path d="M20.2 20.9C18.4 24.4 13 25.4 9.6 28.8"/></svg>`;

export default function AppleIcon() {
  return new ImageResponse(
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        width: "100%",
        height: "100%",
        background: "#3e715f",
      }}
    >
      <img
        src={`data:image/svg+xml;utf8,${encodeURIComponent(MARK)}`}
        width={112}
        height={112}
        alt=""
      />
    </div>,
    size,
  );
}
