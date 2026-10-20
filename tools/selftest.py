#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自测：模拟 Notifikator 测试通知 和 微信洗衣通知，然后打印 bridge 日志最后几行。
用法（Termux）：
  python ~/laundry-xiaoai/tools/selftest.py
"""
import json
import sys
import urllib.request
from pathlib import Path


def post(payload):
    req = urllib.request.Request(
        "http://127.0.0.1:8765/notify",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=15).read().decode("utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("bridge 侧自测（模拟 Notifikator 转发两种通知）")
    print("-" * 60)

    print("① 模拟 Notifikator 自带的测试通知（预期：被包名过滤，不播报）")
    try:
        print("   ->", post({"title": "Test Notification",
                             "text": "Test notifcation from Notifikator",
                             "package": "org.scottmconway.notifikator"}))
    except Exception as exc:  # noqa: BLE001
        print("   ❌ 请求失败（服务没启动？）：", exc)
        return

    print("② 模拟微信的洗衣完成通知（预期：小爱播报）")
    try:
        print("   ->", post({"title": "微信",
                             "text": "文件传输助手: 洗衣已完成，请及时晾晒",
                             "package": "com.tencent.mm"}))
    except Exception as exc:  # noqa: BLE001
        print("   ❌ 请求失败：", exc)

    log = Path.home() / ".config" / "laundry-xiaoai" / "bridge.log"
    print("-" * 60)
    print("bridge.log 最后 10 行：")
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(lines[-10:]))
    except Exception as exc:  # noqa: BLE001
        print("(读日志失败：", exc, ")")

    print("-" * 60)
    print("如果上面的日志里出现了「收到通知：package=org.scottmconway.notifikator」")
    print("就说明 Notifikator 的发送链路是通的；接下来只需要在 Notifikator 里")
    print("点 Send Notification，日志里就会出现同样的记录。")
    print("② 如果小爱说话了，说明微信通知这条链路也通了。")
    print("=" * 60)


if __name__ == "__main__":
    main()
