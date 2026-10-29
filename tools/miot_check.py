#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MIoT 通道诊断：判断 -127 client withdraw 是账号级还是音箱级问题。

用法（Termux）：
    python ~/laundry-xiaoai/tools/miot_check.py

会依次：
1. 登录 micoapi（MiNA）并列出小爱音箱；
2. 登录 xiaomiio（MIoT）；
3. 用 MIoT 读一个普通设备属性（晾衣架状态，只读无副作用）；
4. 用 MIoT 给音箱发 play-text；
5. 用 MiNA TTS 发一句；
打印每一步的返回，最后给出结论。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

HOME = Path.home()
APP_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_DIR") or (HOME / "laundry-xiaoai"))
CFG_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_HOME") or (HOME / ".config" / "laundry-xiaoai"))
CONFIG = CFG_DIR / "config.json"
TOKEN = CFG_DIR / "mi.token"
AIRER_DID = "993652924"


def load_cfg():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _code(v):
    if isinstance(v, int):
        return v
    if isinstance(v, dict):
        return int(v.get("code", -1))
    if isinstance(v, list) and v:
        return _code(v[0])
    return -1


async def main_async():
    cfg = load_cfg()
    if not (cfg.get("username") and cfg.get("password")):
        print("❌ config.json 里缺少账号/密码，先跑 一键中心 2 登录（并保存密码）")
        return 1
    sys.path.insert(0, str(APP_DIR))
    import bridge  # 复用 bridge 里的 _new_account / 会话逻辑
    bridge.TOKEN_PATH = TOKEN
    bridge.CONFIG_PATH = CONFIG

    account = bridge._new_account(cfg.get("username") or "", cfg.get("password") or "")
    from miservice import MiIOService, MiNAService

    print("① micoapi（MiNA）登录 + 设备列表…")
    try:
        devices = await MiNAService(account).device_list()
        print("   ✅ 设备数：", len(devices or []))
        for d in devices or []:
            print(f"   - {d.get('name')} | hardware={d.get('hardware')} | deviceID={d.get('deviceID')} | miotDID={d.get('miotDID')}")
    except Exception as exc:  # noqa: BLE001
        print("   ❌ MiNA 失败：", exc)
        return 1
    speaker = (devices or [{}])[0]
    did_miot = str(speaker.get("miotDID") or "")
    did_mina = speaker.get("deviceID") or ""

    print("\n② xiaomiio（MIoT）登录…")
    try:
        ok = await account.login("xiaomiio")
        print("   ✅" if ok else "   ❌", "xiaomiio 登录返回：", ok)
    except Exception as exc:  # noqa: BLE001
        print("   ❌ xiaomiio 登录失败：", exc)
        return 1

    svc = MiIOService(account)

    print(f"\n③ MIoT 只读测试（晾衣架 {AIRER_DID} status 2.2）…")
    try:
        value = await svc.miot_get_prop(AIRER_DID, (2, 2))
        print("   ✅ miotspec/prop/get 正常，status =", value)
        account_ok = True
    except Exception as exc:  # noqa: BLE001
        print("   ❌ miotspec/prop/get 失败：", exc)
        account_ok = False

    print(f"\n④ 音箱 play-text（{did_miot} siid=5 aiid=3）…")
    try:
        code = await svc.miot_action(did_miot, (5, 3), ["测试播报"])
        print("   code =", code, "（0 表示成功）")
        speaker_ok = code == 0
    except Exception as exc:  # noqa: BLE001
        print("   ❌ 失败：", exc)
        speaker_ok = False

    print("\n⑤ MiNA TTS…")
    try:
        ok = await MiNAService(account).text_to_speech(did_mina, "测试播报")
        print("   返回：", ok, "（OH2 上可能为 True 但无声）")
    except Exception as exc:  # noqa: BLE001
        print("   ❌ 失败：", exc)

    print("\n" + "=" * 56)
    print("结论：")
    if account_ok and speaker_ok:
        print("✅ MIoT 通道恢复正常（不需要处理）")
    elif account_ok and not speaker_ok:
        print("⚠️ 账号级 MIoT 正常，但**音箱**的 play-text 被拒（-127）。")
        print("   建议：① 给音箱断电 10 秒再通电；② 米家 App 里确认能控制该音箱；")
        print("   ③ 等 1~2 分钟后重跑一键中心 → 1；仍不行把本输出发我。")
    else:
        print("❌ 账号级 MIoT 也被拒（-127）：说明小米云端会话异常。")
        print("   建议：① 在米家 App 里退出账号再登录一次；② 跑一键中心 → 13 重新登录；")
        print("   ③ 仍不行把本输出发我。")
    print("=" * 56)
    return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
