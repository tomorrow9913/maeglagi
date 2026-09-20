/**
 * 저장하지 않은 작업이 있을 때 앱 안 링크 이동을 한 번 막아 확인을 받습니다.
 *
 * `beforeunload`는 새로고침·탭 닫기만 잡고, Next.js `<Link>`처럼 페이지를 새로
 * 불러오지 않는 이동은 잡지 못합니다. 그래서 document의 click을 capture 단계에서
 * 먼저 받아 같은 출처 링크일 때만 `window.confirm`을 띄웁니다.
 *
 * 테스트가 Node에서 이 파일을 그대로 불러오므로 `@/` import와 지울 수 없는
 * TypeScript 문법(enum, namespace 등)을 쓰지 않습니다.
 */

export type GuardedClick = {
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  defaultPrevented: boolean;
};

export type GuardedAnchor = {
  /** `href` 속성 원문. 없으면 null */
  href: string | null;
  /** `target` 속성 원문 */
  target: string | null;
  /** `download` 속성이 있는지 */
  download: boolean;
};

/** 이 클릭이 "작업을 잃을 수 있는 앱 안 이동"인지 판단합니다. 부수 효과가 없습니다. */
export function shouldInterceptNavigation(
  click: GuardedClick,
  anchor: GuardedAnchor,
  currentHref: string,
): boolean {
  if (click.defaultPrevented || click.button !== 0) return false;
  // 새 탭·새 창·다운로드로 여는 클릭은 현재 화면을 떠나지 않습니다.
  if (click.metaKey || click.ctrlKey || click.shiftKey || click.altKey) return false;
  if (anchor.download) return false;
  const target = (anchor.target ?? "").trim().toLowerCase();
  if (target && target !== "_self") return false;
  const href = (anchor.href ?? "").trim();
  if (!href || href.startsWith("#")) return false;

  let current: URL;
  let next: URL;
  try {
    current = new URL(currentHref);
    next = new URL(href, current);
  } catch {
    return false;
  }
  if (next.protocol !== "http:" && next.protocol !== "https:") return false;
  // 다른 출처로 가는 이동은 브라우저의 beforeunload 확인이 맡습니다.
  if (next.origin !== current.origin) return false;
  // 같은 문서 안의 해시 이동과 현재 URL 링크는 화면을 바꾸지 않습니다.
  if (next.pathname === current.pathname && next.search === current.search) return false;
  return true;
}

const guards = new Map<number, string>();
let nextGuardId = 0;
let listening = false;

function activeMessage(): string | undefined {
  let message: string | undefined;
  for (const value of guards.values()) message = value;
  return message;
}

function onDocumentClick(event: MouseEvent) {
  const message = activeMessage();
  if (message === undefined) return;
  const origin = event.target;
  if (!(origin instanceof Element)) return;
  const anchor = origin.closest("a[href]");
  if (!anchor) return;
  const intercept = shouldInterceptNavigation(
    event,
    {
      href: anchor.getAttribute("href"),
      target: anchor.getAttribute("target"),
      download: anchor.hasAttribute("download"),
    },
    window.location.href,
  );
  if (!intercept) return;
  if (window.confirm(message)) return;
  event.preventDefault();
  event.stopPropagation();
}

/**
 * 가드를 등록합니다. 돌려받은 함수를 호출하면 해제됩니다.
 * 여러 개가 등록돼 있으면 가장 나중에 등록한 문구로 한 번만 묻습니다.
 */
export function registerNavigationGuard(message: string): () => void {
  const id = nextGuardId++;
  guards.set(id, message);
  if (!listening && typeof document !== "undefined") {
    document.addEventListener("click", onDocumentClick, true);
    listening = true;
  }
  return () => {
    guards.delete(id);
    if (guards.size === 0 && listening && typeof document !== "undefined") {
      document.removeEventListener("click", onDocumentClick, true);
      listening = false;
    }
  };
}
