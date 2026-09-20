import type { NodeShape } from "../lib/graph-style";

/**
 * 범례와 목록에 쓰는 노드 모양입니다. 캔버스의 cytoscape `shape`와 같은 모양을 그립니다.
 *
 * 색은 `currentColor`를 따르므로 쓰는 쪽에서 `style={{ color }}`로 정합니다.
 */
export function NodeShapeIcon({
  shape,
  className = "size-3",
  color,
}: {
  shape: NodeShape;
  className?: string;
  color?: string;
}) {
  return (
    <svg
      viewBox="0 0 12 12"
      className={className}
      style={color ? { color } : undefined}
      fill="currentColor"
      aria-hidden
      focusable="false"
    >
      {shape === "ellipse" ? <circle cx="6" cy="6" r="5.5" /> : null}
      {shape === "round-rectangle" ? <rect x="0.5" y="0.5" width="11" height="11" rx="3" /> : null}
      {shape === "diamond" ? <polygon points="6,0 12,6 6,12 0,6" /> : null}
      {shape === "hexagon" ? <polygon points="3,0.8 9,0.8 12,6 9,11.2 3,11.2 0,6" /> : null}
      {shape === "round-triangle" ? (
        <polygon
          points="6,1.75 10.75,10.25 1.25,10.25"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      ) : null}
      {shape === "rectangle" ? <rect x="0" y="2" width="12" height="8" /> : null}
    </svg>
  );
}
