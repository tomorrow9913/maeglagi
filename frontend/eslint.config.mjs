import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

/**
 * ESLint 설정.
 *
 * 타입 검사(`tsc --noEmit`)가 못 잡는 것을 여기서 막습니다. 특히 선언만
 * 하고 쓰지 않는 prop과 Hook 의존성 누락이 대상입니다.
 */
const config = [
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts"],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      // 의도적으로 버리는 값은 _ 접두사로 표시합니다.
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
        },
      ],
    },
  },
  {
    // shadcn 원본은 직접 수정하지 않으므로 규칙을 강제하지 않습니다.
    files: ["src/components/ui/**"],
    rules: {
      "@typescript-eslint/no-unused-vars": "off",
      "@typescript-eslint/no-explicit-any": "off",
    },
  },
];

export default config;
