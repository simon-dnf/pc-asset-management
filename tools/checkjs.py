"""화면 스크립트(web/js) 구문 점검.

`h(...)` 중첩이 깊어 괄호를 한 개 빠뜨리기 쉽고, 그러면 화면 전체가 비어버린다.
브라우저를 열기 전에 이걸로 먼저 걸러낸다.

    python tools\\checkjs.py

문자열·템플릿리터럴·주석·정규식을 건너뛰고 괄호/중괄호/대괄호 균형만 본다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "web" / "js"

PAIRS = {")": "(", "]": "[", "}": "{"}
OPENERS = set(PAIRS.values())


def check(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    stack: list[tuple[str, int]] = []
    errors: list[str] = []
    line = 1
    i, n = 0, len(src)
    # 정규식 리터럴과 나눗셈을 구분하기 위해 직전 의미 있는 문자를 기억한다
    prev = ""

    while i < n:
        ch = src[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        # 주석
        if ch == "/" and i + 1 < n:
            if src[i + 1] == "/":
                while i < n and src[i] != "\n":
                    i += 1
                continue
            if src[i + 1] == "*":
                i += 2
                while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                    if src[i] == "\n":
                        line += 1
                    i += 1
                i += 2
                continue
            # 정규식 리터럴 (직전 문자가 값이 아닐 때만)
            if prev not in ")]}" and not (prev.isalnum() or prev in "_$"):
                i += 1
                in_class = False
                while i < n:
                    c = src[i]
                    if c == "\\":
                        i += 2
                        continue
                    if c == "[":
                        in_class = True
                    elif c == "]":
                        in_class = False
                    elif c == "/" and not in_class:
                        break
                    elif c == "\n":
                        break
                    i += 1
                i += 1
                prev = "/"
                continue
        # 문자열
        if ch in "'\"":
            quote = ch
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == quote:
                    break
                if src[i] == "\n":
                    errors.append(f"{path.name}:{line} 문자열이 줄에서 끝나지 않았습니다.")
                    break
                i += 1
            i += 1
            prev = "'"
            continue
        # 템플릿 리터럴 (${...} 안은 코드라 다시 검사해야 하므로 중첩 깊이만 센다)
        if ch == "`":
            i += 1
            depth = 0
            while i < n:
                c = src[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "\n":
                    line += 1
                elif c == "$" and i + 1 < n and src[i + 1] == "{":
                    depth += 1
                    i += 2
                    continue
                elif c == "}" and depth:
                    depth -= 1
                elif c == "`" and depth == 0:
                    break
                i += 1
            i += 1
            prev = "`"
            continue

        if ch in OPENERS:
            stack.append((ch, line))
        elif ch in PAIRS:
            if not stack:
                errors.append(f"{path.name}:{line} 여는 짝 없이 '{ch}' 가 닫혔습니다.")
            elif stack[-1][0] != PAIRS[ch]:
                open_ch, open_line = stack.pop()
                errors.append(
                    f"{path.name}:{line} '{ch}' 로 닫으려 했지만 {open_line}행의 '{open_ch}' 가 열려 있습니다.")
            else:
                stack.pop()

        if not ch.isspace():
            prev = ch
        i += 1

    for open_ch, open_line in stack:
        errors.append(f"{path.name}:{open_line} '{open_ch}' 가 닫히지 않았습니다.")
    return errors


def main() -> int:
    files = sorted(JS_DIR.rglob("*.js"))
    if not files:
        print("점검할 파일이 없습니다.")
        return 1
    bad = 0
    for f in files:
        errs = check(f)
        rel = f.relative_to(ROOT).as_posix()
        if errs:
            bad += 1
            print(f"  FAIL  {rel}")
            for e in errs[:5]:
                print(f"          {e}")
        else:
            print(f"  ok    {rel}")
    print()
    if bad:
        print(f"===== 문제 있는 파일 {bad}개 =====")
        return 1
    print(f"===== {len(files)}개 파일 모두 정상 =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
