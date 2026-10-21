#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""晾衣架控制诊断：读出真实状态，依次尝试各种控制方式，并打印返回码与状态变化。

用法（Termux）：
    python ~/laundry-xiaoai/tools/airer_diag.py
    python ~/laundry-xiaoai/tools/airer_diag.py --did 993652924

测试时人在旁边看着晾衣架，记录哪一步真的动了。
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

HOME = Path.home()
CFG_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_HOME") or (HOME / ".config" / "laundry-xiaoai"))
TOKEN = CFG_DIR / "mi.token"
CONFIG = CFG_DIR / "config.json"

STATUS_LABEL = {0: "停止-上限位", 1: "上升中", 2: "下降中", 3: "停止", 4: "停止-下限位"}


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


async def main_async(args):
    cfg = load_config()
    if not cfg.get("username"):
        print("❌ config.json 里没有小米账号，先跑 bridge.py --login")
        return 1
    from miservice import MiAccount, MiIOService
    account = MiAccount(None, cfg.get("username") or "", cfg.get("password") or "", str(TOKEN))
    svc = MiIOService(account)

    print("① 设备列表（找晾衣架）")
    devices = await svc.device_list("full")
    target = None
    for d in devices or []:
        name = d.get("name") or ""
        if str(d.get("did")) == str(args.did) or (not args.did and "晾衣" in name):
            target = d
        print(f"  - {name} | did={d.get('did')} | model={d.get('model')} "
              f"| online={d.get('isOnline', d.get('online'))}")
    if not target:
        print("❌ 没找到晾衣架，用 --did 指定")
        return 1
    did = str(target.get("did"))
    model = target.get("model")
    print(f"\n使用设备：{target.get('name')} | did={did} | model={model}")

    print("\n② MIoT 规格（Airer 服务，含读写权限）")
    spec = None
    try:
        spec = await svc.miot_spec(model)
    except Exception as exc:  # noqa: BLE001
        print("  ⚠️ 读取规格失败：", exc)
    if isinstance(spec, dict):
        for svc_item in spec.get("services") or []:
            if svc_item.get("iid") != 2:
                continue
            print(f"  service siid=2 {svc_item.get('description')}")
            for p in svc_item.get("properties") or []:
                vals = p.get("value-list") or p.get("valueList") or []
                vv = ", ".join(f"{v.get('value')}={v.get('description')}" for v in vals) if vals else ""
                print(f"    piid={p.get('iid')} {p.get('description')} "
                      f"format={p.get('format')} access={p.get('access')} {('[' + vv + ']') if vv else ''}")
            for a in svc_item.get("actions") or []:
                print(f"    action aiid={a.get('iid')} {a.get('description')}")

    async def read(siid, piid):
        try:
            return await svc.miot_get_prop(did, (siid, piid))
        except Exception as exc:  # noqa: BLE001
            return f"ERR:{exc}"

    async def write(siid, piid, value):
        try:
            res = await svc.miot_set_prop(did, (siid, piid), value)
            return json.dumps(res, ensure_ascii=False)[:160] if not isinstance(res, (int, str)) else res
        except Exception as exc:  # noqa: BLE001
            return f"ERR:{exc}"

    async def act(siid, aiid, args_):
        try:
            res = await svc.miot_action(did, (siid, aiid), args_)
            return json.dumps(res, ensure_ascii=False)[:160] if not isinstance(res, (int, str)) else res
        except Exception as exc:  # noqa: BLE001
            return f"ERR:{exc}"

    async def snapshot():
        status = await read(2, 2)
        motor = await read(2, 5)
        fault = await read(2, 1)
        extra = ""
        if isinstance(status, int):
            extra = f"（{STATUS_LABEL.get(status, '?')}）"
        print(f"   status(2,2)={status}{extra} | motor(2,5)={motor} | fault(2,1)={fault}")

    print("\n③ 当前状态")
    await snapshot()

    steps = [
        ("设置属性 Motor Control (siid=2, piid=5, value=2=下降)", lambda: write(2, 5, 2)),
        ("调用动作 service6 aiid=2 motor-control-down, args=[]", lambda: act(6, 2, [])),
        ("调用动作 service6 aiid=2 motor-control-down, args=[1]", lambda: act(6, 2, [1])),
        ("调用动作 service6 aiid=1 motor-control-up（对照，应上升）", lambda: act(6, 1, [])),
        ("调用动作 service6 aiid=3 motor-control-pause", lambda: act(6, 3, [])),
    ]
    for title, func in steps:
        print(f"\n④ 尝试：{title}")
        try:
            print("   返回：", await func())
        except Exception as exc:  # noqa: BLE001
            print("   异常：", exc)
        for _ in range(2):
            time.sleep(2)
            await snapshot()

    print("\n⑤ 结束状态")
    await snapshot()
    print("\n请告诉我：哪一步晾衣架真的动了（或全都没动），以及上面每一步的返回。")
    return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="晾衣架控制诊断")
    parser.add_argument("--did", default="", help="设备 DID（默认自动找名字带“晾衣”的）")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
