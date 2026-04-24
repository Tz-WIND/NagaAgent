#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


TARGET = Path("frontend/src/components/LoginDialog.vue")

REPLACEMENTS = [
    (
        "window.open('https://github.com/RTGS2017/NagaAgent.git', '_blank')",
        "emit('skip')",
        "恢复跳过登录事件",
    ),
    (
        "不登录，使用开源版本",
        "不登录，直接进入",
        "恢复跳过登录文案",
    ),
]


def main() -> int:
    root = Path.cwd()
    target = root / TARGET

    if not target.exists():
        print(f"[kill_auth] 未找到目标文件: {TARGET}")
        print("[kill_auth] 请把脚本放到项目根目录后再运行。")
        return 1

    original = target.read_text(encoding="utf-8")
    updated = original
    applied: list[str] = []

    for old, new, label in REPLACEMENTS:
        if old in updated:
            updated = updated.replace(old, new)
            applied.append(label)

    if updated == original:
        if "emit('skip')" in original and "不登录，直接进入" in original:
            print("[kill_auth] 已经是可跳过登录版本，无需重复处理。")
            return 0
        print("[kill_auth] 没找到可替换的旧逻辑，脚本未修改任何文件。")
        return 1

    target.write_text(updated, encoding="utf-8")
    print(f"[kill_auth] 已修复 {TARGET}")
    for item in applied:
        print(f"[kill_auth] - {item}")
    print("[kill_auth] 现在点击“不登录”会直接进入程序，可自行填写自定义 API。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
