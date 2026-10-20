#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小爱播报诊断：列出设备/能力 → 设置音量 → TTS 测试 → 播放测试提示音 → 打印状态。
在 Termux 里运行（复用 bridge 的登录令牌）：
  python ~/laundry-xiaoai/tools/diag.py
"""
import asyncio
import json
import sys
from pathlib import Path

# bridge.py 实际使用的配置目录（先找 laundry-xiaoai，兼容旧文档里的 laundry-alert）
BASE = None
for name in ("laundry-xiaoai", "laundry-alert"):
    d = Path.home() / ".config" / name
    if (d / "config.json").exists() or (d / "mi.token").exists():
        BASE = d
        break
CONFIG = (BASE / "config.json") if BASE else Path.home() / ".config" / "laundry-xiaoai" / "config.json"
TOKEN = (BASE / "mi.token") if BASE else Path.home() / ".config" / "laundry-xiaoai" / "mi.token"


def load_cfg():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def jdump(obj):
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return repr(obj)


async def main():
    from miservice import MiAccount, MiNAService

    cfg = load_cfg()
    print("=" * 64)
    print("小爱播报诊断")
    print("配置目录：", BASE)
    print("配置文件：", CONFIG, "存在" if CONFIG.exists() else "不存在")
    print("登录令牌：", TOKEN, "存在" if TOKEN.exists() else "不存在")
    print("配置里的 speaker =", repr(cfg.get("speaker")))
    print("-" * 64)

    if not TOKEN.exists():
        print("❌ 没有找到登录令牌。先在 Termux 里运行：")
        print("   cd ~/laundry-xiaoai && python bridge.py --login")
        return
    if not cfg.get("username"):
        print("⚠️ 配置里没有用户名（可能配置文件路径不对）。仍尝试用已有令牌。")

    # 不主动用空密码登录，避免账号被风控；有令牌就直接用令牌
    account = MiAccount(None, cfg.get("username") or "", "", str(TOKEN))
    service = MiNAService(account)

    try:
        devices = await service.device_list()
    except Exception as exc:  # noqa: BLE001
        print("❌ 用现有令牌请求设备列表失败：", exc)
        print("   如果提示登录失败，请在 Termux 里重新登录：")
        print("   cd ~/laundry-xiaoai && python bridge.py --login")
        return
    if not devices:
        print("❌ 账号下没有 MiNA 设备（音箱没绑在这个小米账号？）")
        return
    print("账号下的音箱设备：")
    for i, d in enumerate(devices, 1):
        print(f"  {i}. {jdump(d)}")

    target = None
    needle = (cfg.get("speaker") or "").strip().lower()
    if needle:
        for d in devices:
            if needle in (d.get("name") or "").lower() or needle in (d.get("hardware") or "").lower():
                target = d
                break
        if target is None:
            print(f"\n⚠️ 配置里的 speaker={needle!r} 没匹配到设备，改用第一台")
    target = target or devices[0]
    did = target.get("deviceID")
    name = target.get("name")
    print("\n目标设备：", name, "| hardware =", target.get("hardware"), "| deviceID =", did)
    print("capabilities =", jdump(target.get("capabilities")))
    print("-" * 64)

    try:
        print("① TTS 前播放状态：", jdump(await service.player_get_status(did)))
    except Exception as e:  # noqa: BLE001
        print("① 获取状态失败：", e)

    try:
        print("② 设置音量到 70：", await service.player_set_volume(did, 70))
    except Exception as e:  # noqa: BLE001
        print("② 设置音量失败：", e)

    try:
        print("③ 云端 TTS（应为小爱说话）：", await service.text_to_speech(did, "这是一条测试播报，一二三四五"))
    except Exception as e:  # noqa: BLE001
        print("③ 云端 TTS 失败：", e)
    await asyncio.sleep(2.5)
    try:
        print("   TTS 后播放状态：", jdump(await service.player_get_status(did)))
    except Exception as e:  # noqa: BLE001
        print("   TTS 后获取状态失败：", e)

    try:
        print("④ 广播 TTS（所有音箱）：", await service.send_message(devices, -1, "广播测试，一二三四五"))
    except Exception as e:  # noqa: BLE001
        print("④ 广播失败：", e)
    await asyncio.sleep(2.5)

    # ⑤ 已移除：之前用 play_by_url 播 mp3，OH2 会走音乐播放通道导致卡住/反复“嘀嘀嘀”。
    print("⑤ （已跳过 mp3 测试：OH2 的音乐通道会卡住，已从诊断里移除）")

    # ⑥ MIoT play-text：OH2/OH2P 这类新型号的正确播报通道
    hw = (target.get("hardware") or "").upper()
    iid = {"OH2": (5, 3), "OH2P": (7, 3)}.get(hw)
    if iid:
        try:
            from miservice import MiIOService
            miio = MiIOService(account)
            code = await miio.miot_action(str(target.get("miotDID")), iid, ["MIoT 指令测试，一二三四五"])
            print("⑥ MIoT play-text", iid, "-> code =", code, "（应该能听到“MIoT 指令测试，一二三四五”）")
        except Exception as e:  # noqa: BLE001
            print("⑥ MIoT play-text 失败：", e)
    else:
        print("⑥ 型号未在 MIoT 映射表里（OH2/OH2P 才有），跳过")

    print("-" * 64)
    print("诊断结束。请把上面完整输出发给我。")
    print("判读方法：")
    print("  - ③ 有声、⑤ 有声 → 全通；之前可能只是音量低/没注意听")
    print("  - ③ 无声、⑤ 有声 → 这个型号云端 TTS 通道不响，我改用 MIoT play-text")
    print("  - ③ 无声、⑤ 无声 → 音量/静音/音箱离线/硬件问题，先对小爱喊“音量调到 50”验证")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
