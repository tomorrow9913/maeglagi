"use client";

import { useLayoutEffect, useRef, type Ref } from "react";

import { cn } from "@/lib/utils";

import { QUESTION_MAX_LENGTH } from "../lib/ask-turns";

/**
 * 질문 입력창입니다. 내용에 맞춰 높이가 늘어납니다.
 *
 * Enter로 보내고 Shift+Enter로 줄을 바꿉니다. 한글 조합 중의 Enter는 글자를 확정하는
 * 키라서 보내기로 처리하지 않습니다. 답변이 오는 동안에도 잠그지 않아, 포커스를 잃지
 * 않고 다음 질문을 미리 적을 수 있습니다. 보내기를 막는 일은 호출하는 쪽이 맡습니다.
 */
export function QuestionInput({
  value,
  onChange,
  onSubmit,
  className,
  ref,
  ...props
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  className?: string;
  ref?: Ref<HTMLTextAreaElement>;
} & Omit<React.ComponentProps<"textarea">, "value" | "onChange" | "onSubmit" | "ref">) {
  const innerRef = useRef<HTMLTextAreaElement>(null);

  // 보낸 뒤 비워질 때도 높이가 줄어들도록 값이 바뀔 때마다 다시 잽니다.
  useLayoutEffect(() => {
    const element = innerRef.current;
    if (!element) return;
    element.style.height = "auto";
    // 테두리 두께만큼 더해야 스크롤바가 생기지 않습니다.
    element.style.height = `${element.scrollHeight + 2}px`;
  }, [value]);

  return (
    <textarea
      ref={(element) => {
        innerRef.current = element;
        if (typeof ref === "function") ref(element);
        else if (ref) ref.current = element;
      }}
      rows={1}
      value={value}
      maxLength={QUESTION_MAX_LENGTH}
      enterKeyHint="send"
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={(event) => {
        if (event.key !== "Enter" || event.shiftKey) return;
        // 조합 중 Enter는 브라우저마다 isComposing 또는 keyCode 229로 알려줍니다.
        if (event.nativeEvent.isComposing || event.keyCode === 229) return;
        event.preventDefault();
        onSubmit();
      }}
      className={cn(
        "block max-h-40 min-h-8 w-full min-w-0 resize-none overflow-y-auto rounded-lg border border-input bg-transparent px-2.5 py-1 text-base break-words transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm dark:bg-input/30",
        className,
      )}
      {...props}
    />
  );
}
