#!/usr/bin/env python3
"""guard-tools.py の回帰テスト。

ガードレールは「通すべきものを通す」ことと「止めるべきものを止める」ことの
両方が要る。ルールを足すときはここにケースを追加してから実装する。

    python3 .claude/hooks/test_guard_tools.py

pytest には依存しない（フックは pytest が無い環境でも直せる必要があるため）。
テスト内で ".env" を文字列連結で組み立てているのは、フック自身が
このファイルを編集する Bash コマンドをブロックしてしまうのを避けるため。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

HOOK = Path(__file__).with_name("guard-tools.py")

E = "." + "env"

# (コマンド, 期待する判定)
BASH_CASES = [
    # .env: ひな形だけ通す
    (f"cat > {E}.example", "allow"),
    (f"cat config/{E}.sample", "allow"),
    (f"cat {E}", "DENY"),
    (f"cat api/{E}.local", "DENY"),
    (f"echo x > {E}.production", "DENY"),
    ('grep -rn "\\.env" .', "allow"),  # 検索文字列はパスではない
    # rm: プロジェクト内の後片付けは通す
    ("rm -rf node_modules", "allow"),
    ("rm -rf dist && npm run build", "allow"),
    ("rm -rf /etc", "DENY"),
    ("rm -rf ../other", "DENY"),
    ("rm -rf ~/work", "DENY"),
    # git push
    ("git push origin main", "allow"),
    ("git push --force-with-lease", "DENY"),
    ("git push -f origin main", "DENY"),
    # ロックファイル
    ("sed -i s/a/b/ uv.lock", "DENY"),
    ("echo x > package-lock.json", "DENY"),
    ("uv add fastapi", "allow"),
    # 通常のコマンド
    ("npm run build", "allow"),
    ("uv run pytest -q", "allow"),
]

# (ツール名, file_path, 期待する判定)
FILE_CASES = [
    ("Read", f"/workspace/{E}", "DENY"),
    ("Edit", f"/workspace/{E}.production", "DENY"),
    ("Write", f"/workspace/{E}.example", "allow"),
    ("Write", f"/workspace/api/{E}.sample", "allow"),
    ("Edit", "/workspace/api/app/servers/api.py", "allow"),
    ("Read", "/workspace/docs/api-contract.md", "allow"),
]


def decide(payload: dict[str, object]) -> str:
    result = subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    return "DENY" if result.stdout.strip() else "allow"


def main() -> int:
    failures = 0

    for command, expected in BASH_CASES:
        actual = decide({"tool_name": "Bash", "tool_input": {"command": command}})
        ok = actual == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} Bash  {command!r:40} -> {actual}")

    for tool, path, expected in FILE_CASES:
        actual = decide({"tool_name": tool, "tool_input": {"file_path": path}})
        ok = actual == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {tool:5} {path!r:40} -> {actual}")

    print(f"\n{len(BASH_CASES) + len(FILE_CASES)} cases, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
