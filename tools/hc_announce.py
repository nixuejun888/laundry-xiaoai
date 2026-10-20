#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""切换事件播报模式（写入 ~/.config/laundry-xiaoai/homeconnect.json 并重启监听）。

用法（Termux）：
    python ~/laundry-xiaoai/tools/hc_announce.py
"""
import json
import subprocess
import sys
from pathlib import Path

CFG = Path.home() / ".config" / "laundry-xiaoai" / "homeconnect.json"
FIX = Path.home() / "laundry-xiaoai" / "tools" / "fix.py"

DEFAULT_ANN = {
    "mode": "finished",
    "global_min_interval_sec": 20,
    "per_key_min_interval_sec": 60,
    "remaining_thresholds_min": [60, 30, 10, 5, 1],
    "progress_thresholds_pct": [50, 75],
    "speak_unknown": False,
    "fill_level_min_interval_sec": 1800,
}


def load():
    try:
        return json.loads(CFG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("晶御事件播报模式切换")
    print("=" * 60)
    cfg = load()
    ann = dict(DEFAULT_ANN)
    ann.update(cfg.get("announce") or {})
    print("当前模式：", ann.get("mode"))
    print()
    print("1) finished   只说完成（最安静）")
    print("2) minimal    完成 + 耗材不足（洗衣液/柔顺剂）← 推荐")
    print("3) important  完成 + 开始/暂停/开关门/报警/耗材")
    print("4) all        全部事件（含剩余时间/进度，会比较吵，带节流）")
    choice = input("\n选择 1/2/3/4（直接回车不改）：").strip()
    mode = {"1": "finished", "2": "minimal", "3": "important", "4": "all"}.get(
        choice, ann.get("mode") or "finished")
    ann["mode"] = mode
    if mode == "all":
        unk = input("是否也播报没翻译的未知事件？(y/N)：").strip().lower() == "y"
        ann["speak_unknown"] = unk
    cfg["announce"] = ann
    CFG.parent.mkdir(parents=True, exist_ok=True)
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        CFG.chmod(0o600)
    except OSError:
        pass
    print("\n✅ 已保存：announce.mode =", mode)

    ans = input("\n现在重启监听让它生效吗？(Y/n)：").strip().lower()
    if ans == "n":
        print("稍后手动运行：python ~/laundry-xiaoai/tools/fix.py")
        return 0
    print("\n重启监听（执行 tools/fix.py）…")
    try:
        return subprocess.run([sys.executable, str(FIX)], check=False).returncode
    except Exception as exc:  # noqa: BLE001
        print("⚠️ 自动重启失败，请手动运行：python ~/laundry-xiaoai/tools/fix.py\n", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
