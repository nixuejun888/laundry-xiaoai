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


def guess_control(spec):
    """优先找 Motor Control（带 Down 枚举），其次 Control/升降，最后才 Position。"""
    candidates = []
    for svc_item in (spec or {}).get("services") or []:
        siid = svc_item.get("iid")
        for p in svc_item.get("properties") or []:
            desc = (p.get("description") or "").lower()
            vals = p.get("value-list") or p.get("valueList") or []
            down_val = None
            for v in vals:
                if str(v.get("description", "")).lower() in ("down", "下降"):
                    down_val = v.get("value")
            score = 0
            if "motor control" in desc or "motor" in desc:
                score += 20
            elif "control" in desc or "升降" in desc:
                score += 10
            if down_val is not None:
                score += 10
            if "position" in desc:
                score -= 15
            if score > 0:
                candidates.append((score, siid, p.get("iid"), p.get("description"), down_val))
    if not candidates:
        return None, None, None, None
    candidates.sort(reverse=True)
    _, siid, piid, desc, down_val = candidates[0]
    return siid, piid, desc, down_val


def guess_lower_status(spec):
    """找“停止下限位/到底”的状态属性，用于精确等待降到底。"""
    for svc_item in (spec or {}).get("services") or []:
        siid = svc_item.get("iid")
        for p in svc_item.get("properties") or []:
            for v in (p.get("value-list") or p.get("valueList") or []):
                desc = str(v.get("description", "")).lower()
                if ("lower" in desc and ("limit" in desc or "stop" in desc)) or "下限位" in desc:
                    return siid, p.get("iid"), v.get("value")
    return None


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
    siid, piid, desc, down_default = guess_control(spec) if spec else (None, None, None, None)
    if siid is not None:
        print(f"\n建议：siid={siid}, piid={piid}（{desc}）")
    else:
        print("\n没自动识别到控制属性，请参考上面的规格手动填。")

    siid = ask(f"siid（回车={siid or 2}）：", str(siid or 2))
    piid = ask(f"piid（回车={piid or 5}）：", str(piid or 5))
    mode = ask("控制方式：1=设置属性(miot_set_prop) / 2=调用动作(miot_action)（回车=1）：", "1")
    down_val = ask(f"下降用值（回车={down_default if down_default is not None else 2}）：",
                   str(down_default if down_default is not None else 2))
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

    ok = False
    for attempt in range(3):
        ok = ask("晾衣架有反应吗？(y/N)：", "n").lower() == "y"
        if ok:
            break
        print("可以调整参数再试：")
        siid = ask(f"siid（回车={siid}）：", str(siid))
        piid = ask(f"piid（回车={piid}）：", str(piid))
        down_val = ask(f"下降值（回车={down_val}）：", str(down_val))
        print("重新测试…")
        if action.get("type") == "miot_action":
            aiid = ask(f"aiid（回车={action.get('aiid', 1)}）：", str(action.get("aiid", 1)))
            await try_action(svc, did, siid, aiid, action.get("args") or [])
            action.update({"siid": int(siid), "aiid": int(aiid)})
        else:
            await try_set(svc, did, siid, piid, int(down_val))
            action.update({"siid": int(siid), "piid": int(piid), "value": int(down_val)})
    if not ok:
        print("那这次先不保存。可以把 `python ~/laundry-xiaoai/tools/rack.py --spec <did>` 的输出发我，我帮你确认参数。")
        return
    correct = ask("方向是「下降」对吗？(Y/n)：", "y").lower() != "n"
    if not correct and action.get("type") != "miot_action":
        new_val = ask("那换一个下降值（上升/下降可能相反，如 1）：", "")
        if new_val.strip():
            action["value"] = int(new_val)
            print("重新测试…")
            await try_set(svc, did, action.get("siid", siid), action.get("piid", piid), int(new_val))
            confirm = ask("这次是下降了吗？(y/N)：", "n").lower() == "y"
            if not confirm:
                print("方向仍不对，先不保存；把规格输出发我帮你确认。")
                return
    action["delay_sec"] = int(ask("延迟几秒执行（回车=3）：", "3") or 3)
    travel = int(ask("晾衣架从顶部降到底部大约几秒？（用于降到底后播报，回车=20）：", "20") or 20)
    followup = ask("降到底后播报什么？（回车=晾衣架已准备就绪，去晾衣服吧）：",
                   "晾衣架已准备就绪，去晾衣服吧")
    action["followup_text"] = followup
    status = guess_lower_status(spec) if spec else None
    if status:
        s_siid, s_piid, s_val = status
        action["followup_on_status"] = {
            "siid": int(s_siid), "piid": int(s_piid), "value": s_val,
            "timeout_sec": max(travel + 30, 60), "poll_sec": 2,
        }
        action["followup_delay_sec"] = 0
        print(f"已启用“降到底检测”：轮询 siid={s_siid} piid={s_piid} 直到值={s_val}，再播报")
    else:
        action["followup_delay_sec"] = travel
        print(f"没识别到底部状态，使用固定延迟 {travel} 秒")
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
        did, siid, aiid, raw_args = args.action
        arg_list = [int(x) for x in str(raw_args).replace("，", ",").split(",") if x.strip()]
        svc = await get_service(cfg)
        ok = await try_action(svc, did, siid, aiid, arg_list)
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
    parser.add_argument("--action", nargs=4, metavar=("DID", "SIID", "AIID", "ARGS"),
                        help="测试调用动作（ARGS 用逗号分隔）")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
