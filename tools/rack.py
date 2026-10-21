#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""晾衣架联动配置向导（播报后自动控制米家设备，如晾衣架下降）。

用法（Termux）：
    python ~/laundry-xiaoai/tools/rack.py            # 交互式向导（推荐）
    python ~/laundry-xiaoai/tools/rack.py --list     # 列出账号下的米家设备
    python ~/laundry-xiaoai/tools/rack.py --spec DID # 打印设备 MIoT 规格
    python ~/laundry-xiaoai/tools/rack.py --set DID 2 5 2       # 测试设置属性
    python ~/laundry-xiaoai/tools/rack.py --action DID 2 1 0    # 测试调用动作

配置写到 ~/.config/laundry-xiaoai/config.json 的 post_actions，bridge 播报成功后执行。
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

HOME = Path.home()
CFG_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_HOME") or (HOME / ".config" / "laundry-xiaoai"))
TOKEN = CFG_DIR / "mi.token"
CONFIG = CFG_DIR / "config.json"


def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        CONFIG.chmod(0o600)
    except OSError:
        pass


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


async def get_service(cfg: dict):
    from miservice import MiAccount, MiIOService
    account = MiAccount(None, cfg.get("username") or "", cfg.get("password") or "", str(TOKEN))
    return MiIOService(account)


def _code(result) -> int:
    if isinstance(result, int):
        return result
    if isinstance(result, dict):
        return int(result.get("code", -1))
    if isinstance(result, list) and result:
        return _code(result[0])
    return -1


async def list_devices(svc, show_all=False):
    devices = await svc.device_list("full")
    rows = []
    for d in devices or []:
        name = d.get("name") or ""
        if show_all or any(k in name for k in ("晾衣", "衣架", "rack", "Rack")):
            rows.append(d)
    if not rows:
        rows = devices or []
    for i, d in enumerate(rows, 1):
        print(f"  {i:2d}. {d.get('name')} | did={d.get('did')} | model={d.get('model')}")
    return rows


async def dump_spec(svc, did: str):
    devices = await svc.device_list("full")
    model = next((d.get("model") for d in devices or [] if str(d.get("did")) == str(did)), None)
    if not model:
        print("❌ 找不到该 did 的 model")
        return None
    spec = await svc.miot_spec(model)
    if not isinstance(spec, dict):
        print("⚠️ 拿不到 MIoT 规格：", str(spec)[:300])
        return None
    print(f"\n设备 {did} 的 MIoT 规格（model={model}）：")
    for svc_item in spec.get("services") or []:
        siid = svc_item.get("iid")
        desc = svc_item.get("description") or ""
        print(f"\n  service siid={siid}  {desc}")
        for p in svc_item.get("properties") or []:
            values = p.get("value-list") or p.get("valueList") or []
            vals = ", ".join(f"{v.get('value')}={v.get('description')}" for v in values) if values else ""
            print(f"    property piid={p.get('iid')}  {p.get('description')}  "
                  f"format={p.get('format')}  {('[' + vals + ']') if vals else ''}")
        for a in svc_item.get("actions") or []:
            print(f"    action aiid={a.get('iid')}  {a.get('description')}")
    return spec


def guess_control(spec, keyword=("升降", "位置", "下降", "position", "Position")):
    for svc_item in (spec or {}).get("services") or []:
        for p in svc_item.get("properties") or []:
            desc = (p.get("description") or "") + " " + str(p.get("type") or "")
            if any(k in desc for k in keyword):
                return svc_item.get("iid"), p.get("iid"), p.get("description")
    return None, None, None


async def try_set(svc, did, siid, piid, value):
    code = _code(await svc.miot_set_prop(str(did), (int(siid), int(piid)), value))
    print(f"  miot_set_prop did={did} siid={siid} piid={piid} value={value} -> code={code}"
          f"{' ✅' if code == 0 else ' ❌'}")
    return code == 0


async def try_action(svc, did, siid, aiid, args):
    code = _code(await svc.miot_action(str(did), (int(siid), int(aiid)), list(args or [])))
    print(f"  miot_action did={did} siid={siid} aiid={aiid} args={args} -> code={code}"
          f"{' ✅' if code == 0 else ' ❌'}")
    return code == 0


def ask(prompt, default=""):
    try:
        v = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        raise SystemExit(1)
    return v or default


async def wizard(cfg):
    svc = await get_service(cfg)
    print("\n① 账号下的晾衣架/相关设备：")
    rows = await list_devices(svc)
    if not rows:
        print("❌ 没找到设备")
        return
    idx = ask(f"选择设备序号（1-{len(rows)}，回车=1）：", "1")
    try:
        dev = rows[int(idx) - 1]
    except Exception:
        print("序号无效")
        return
    did = str(dev.get("did"))
    print(f"\n已选：{dev.get('name')} | did={did} | model={dev.get('model')}")

    print("\n② 读取 MIoT 规格，自动找升降控制…")
    spec = await dump_spec(svc, did)
    siid, piid, desc = guess_control(spec) if spec else (None, None, None)
    if siid is not None:
        print(f"\n建议：siid={siid}, piid={piid}（{desc}）")
    else:
        print("\n没自动识别到控制属性，请参考上面的规格手动填。")

    siid = ask(f"siid（回车={siid or 2}）：", str(siid or 2))
    piid = ask(f"piid（回车={piid or 5}）：", str(piid or 5))
    mode = ask("控制方式：1=设置属性(miot_set_prop) / 2=调用动作(miot_action)（回车=1）：", "1")
    down_val = ask("下降用值（回车=2）：", "2")
    if mode == "2":
        aiid = ask("aiid（回车=1）：", "1")
        args = ask("动作参数，逗号分隔（回车为空）：", "")
        arg_list = [int(x) for x in args.replace("，", ",").split(",") if x.strip()]
        print("\n③ 测试动作…")
        await try_action(svc, did, siid, aiid, arg_list)
        action = {"type": "miot_action", "did": did, "siid": int(siid),
                  "aiid": int(aiid), "args": arg_list}
    else:
        print("\n③ 测试下降…")
        await try_set(svc, did, siid, piid, int(down_val))
        action = {"type": "miot_set_prop", "did": did, "siid": int(siid),
                  "piid": int(piid), "value": int(down_val)}

    ok = ask("晾衣架有反应吗？(y/N)：", "n").lower() == "y"
    if not ok:
        print("那这次先不保存。可以再跑一次向导，换 siid/piid/值 或改成动作方式。")
        return
    action["delay_sec"] = int(ask("延迟几秒执行（回车=3）：", "3") or 3)
    cats = ask("播报哪个类别后执行？1=洗衣完成 2=烘干完成 3=两者都（回车=1）：", "1")
    cfg.setdefault("post_actions", {})
    pa = cfg["post_actions"]
    pa["enabled"] = True
    if cats in ("1", "3"):
        pa["washer"] = [action]
    if cats in ("2", "3"):
        pa["dryer"] = [dict(action)]
    save_config(cfg)
    print("\n✅ 已写入配置：")
    print(json.dumps({"post_actions": pa}, ensure_ascii=False, indent=2))
    print("\n重启 bridge 生效：python ~/laundry-xiaoai/tools/fix.py")


async def main_async(args):
    cfg = load_config()
    if not cfg.get("username"):
        print("❌ config.json 里没有小米账号，先跑 bridge.py --login")
        return 1
    if args.list:
        svc = await get_service(cfg)
        print("账号下的设备：")
        await list_devices(svc, show_all=True)
        return 0
    if args.spec:
        svc = await get_service(cfg)
        await dump_spec(svc, args.spec)
        return 0
    if args.set:
        did, siid, piid, value = args.set
        svc = await get_service(cfg)
        ok = await try_set(svc, did, siid, piid, value)
        return 0 if ok else 1
    if args.action:
        did, siid, aiid, *rest = args.action
        svc = await get_service(cfg)
        ok = await try_action(svc, did, siid, aiid, rest)
        return 0 if ok else 1
    await wizard(cfg)
    return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="晾衣架联动配置（播报后自动控制）")
    parser.add_argument("--list", action="store_true", help="列出账号下设备")
    parser.add_argument("--spec", metavar="DID", help="打印设备的 MIoT 规格")
    parser.add_argument("--set", nargs=4, metavar=("DID", "SIID", "PIID", "VALUE"),
                        help="测试设置属性")
    parser.add_argument("--action", nargs="+", metavar=("DID", "SIID", "AIID", "ARGS"),
                        help="测试调用动作")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
