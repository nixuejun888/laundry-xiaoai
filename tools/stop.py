#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""立刻停止所有小爱音箱的播放（用于测试提示音卡住/一直响的情况）。
用法（Termux）：
  python ~/laundry-xiaoai/tools/stop.py
"""
import asyncio
import json
import sys
from pathlib import Path

BASE = Path.home() / ".config" / "laundry-xiaoai"
CFG = BASE / "config.json"
TOKEN = BASE / "mi.token"


def load_cfg():
    try:
        return json.loads(CFG.read_text(encoding="utf-8"))
    except Exception:
        return {}


async def main():
    from miservice import MiAccount, MiNAService

    cfg = load_cfg()
    print("=" * 56)
    print("停止所有小爱音箱的播放")
    if not TOKEN.exists():
        print("❌ 没有找到登录令牌，先运行：cd ~/laundry-xiaoai && python bridge.py --login")
        return
    account = MiAccount(None, cfg.get("username") or "", "", str(TOKEN))
    service = MiNAService(account)
    devices = await service.device_list() or []
    if not devices:
        print("账号下没有设备")
        return
    for d in devices:
        did = d.get("deviceID")
        name = d.get("name") or did
        for label, fn in (("停止", service.player_stop), ("暂停", service.player_pause)):
            try:
                print(f"{name} {label} -> {await fn(did)}")
            except Exception as exc:  # noqa: BLE001
                print(f"{name} {label} 失败：{exc}")
        try:
            await service.player_set_loop(did, 1)  # 恢复列表循环
        except Exception:
            pass
    print("-" * 56)
    print("如果音箱还在响：")
    print("  1) 对它说“小爱同学，停止播放”或“小爱同学，关闭音乐”；")
    print("  2) 或把音箱电源拔掉 10 秒再插上。")
    print("（之前的滴滴声是诊断脚本里的 mp3 测试触发的，新诊断脚本已经去掉这一步。）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
