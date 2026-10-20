#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""显示 bridge 最近 30 行日志（排查通知有没有转发进来）。
用法（Termux）：
  python ~/laundry-xiaoai/tools/showlog.py
"""
import sys
from pathlib import Path


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    log = Path.home() / ".config" / "laundry-xiaoai" / "bridge.log"
    print("=" * 64)
    print("bridge.log 最后 30 行：", log)
    print("-" * 64)
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(lines[-30:]))
    except Exception as exc:  # noqa: BLE001
        print("读取失败：", exc)
    print("-" * 64)
    print("判读：")
    print("  · 有「收到通知：package=com.tencent.mm …」→ 微信通知已转发进来")
    print("  · 有「收到通知：package=org.scottmconway.notifikator …」→ 是 Notifikator 的测试按钮")
    print("  · 完全没有「收到通知」→ Notifikator 没转发（通知权限/后台/微信通知没弹出）")
    print("=" * 64)


if __name__ == "__main__":
    main()
