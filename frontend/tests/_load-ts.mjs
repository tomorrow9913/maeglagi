/**
 * `@/` 별칭을 쓰는 TypeScript 모듈을 번들러 없이 불러오는 테스트용 로더입니다.
 *
 * Node의 타입 제거만으로는 `@/lib/...` 같은 경로를 풀 수 없습니다. 여기서는 파일을
 * CommonJS로 변환한 뒤, `@/`와 상대 경로만 `src/` 아래에서 찾아 같은 방식으로 불러옵니다.
 * 같은 realm에서 실행하므로 `assert.deepEqual`이 배열·객체를 그대로 비교할 수 있습니다.
 * 파일 이름이 `.test.mjs`가 아니라서 `node --test tests/*.test.mjs`에는 잡히지 않습니다.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import ts from "typescript";

const srcRoot = fileURLToPath(new URL("../src/", import.meta.url));
const cache = new Map();

function resolveFile(base) {
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, path.join(base, "index.ts")]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`테스트 로더가 모듈을 찾지 못했습니다: ${base}`);
}

function load(file) {
  if (cache.has(file)) return cache.get(file).exports;

  const loaded = { exports: {} };
  cache.set(file, loaded);

  const { outputText } = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    fileName: file,
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  });

  const require = (specifier) => {
    if (specifier.startsWith("@/"))
      return load(resolveFile(path.join(srcRoot, specifier.slice(2))));
    if (specifier.startsWith("."))
      return load(resolveFile(path.resolve(path.dirname(file), specifier)));
    throw new Error(`테스트 로더는 외부 패키지를 불러오지 않습니다: ${specifier} (${file})`);
  };

  vm.runInThisContext(`(function (exports, require, module) {${outputText}\n})`, {
    filename: file,
  })(loaded.exports, require, loaded);
  return loaded.exports;
}

/** `src/` 기준 경로로 모듈을 불러옵니다. 예: `loadTs("features/directory/lib/directory-forms.ts")` */
export function loadTs(relativePath) {
  return load(resolveFile(path.join(srcRoot, relativePath)));
}
