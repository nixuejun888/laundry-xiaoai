#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键检查「方案 A（微信通知）」和「方案 B（晶御官方 API）」是否都通。

用法（Termux）：
    python ~/laundry-xiaoai/tools/verify.py

注意：检查会真的让小爱说一句测试播报（用于确认音箱链路）。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
APP_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_DIR") or (HOME / "laundry-xiaoai"))
CFG_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_HOME") or (HOME / ".config" / "laundry-xiaoai"))
BRIDGE = "http://127.0.0.1:8765"
RESULTS = []


def record(name, ok, detail=""):
    """ok=None 表示仅信息，不计入失败。"""
    RESULTS.append((name, ok, detail))
    icon = "✅" if ok is True else ("ℹ️" if ok is None else "❌")
    print(f"{icon} {name}" + (f" — {detail}" if detail else ""))


def http_json(url, payload=None, timeout=10):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tail(path: Path, n=400):
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except Exception:
        return []


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 64)
    print("小爱洗衣提醒 · 方案 A / 方案 B 连通性检查")
    print("=" * 64)

    # 0. bridge 服务
    health = {}
    try:
        health = http_json(BRIDGE + "/health", timeout=5)
        record("bridge 服务", health.get("ok") is True,
               f"token={health.get('token_exists')} speaker={health.get('speaker')} "
               f"quiet_hours={health.get('quiet_hours')}")
    except Exception as exc:  # noqa: BLE001
        record("bridge 服务", False, f"起不来：{exc}（运行 python ~/laundry-xiaoai/tools/fix.py）")

    # 方案 A：模拟一条微信通知
    try:
        r = http_json(BRIDGE + "/notify", {
            "text": "文件传输助手: 洗衣已完成，请及时晾晒",
            "package": "com.tencent.mm",
        })
        ok = bool(r.get("ok")) and (bool(r.get("spoken")) or r.get("skipped") in ("cooldown", "quiet-hours"))
        record("方案A：模拟微信通知 → bridge", ok, json.dumps(r, ensure_ascii=False)[:180])
    except Exception as exc:  # noqa: BLE001
        record("方案A：模拟微信通知 → bridge", False, str(exc))

    # 方案 A：日志里是否收到过真实微信通知
    real = [ln for ln in tail(CFG_DIR / "bridge.log") if "收到通知：package=com.tencent.mm" in ln]
    record("方案A：真实微信通知记录", True if real else None,
           real[-1][:130] if real else
           "还没有收到过真实微信通知：手机锁屏后，用电脑/另一台手机给微信发「洗衣已完成」，再跑一次本检查")

    # 方案 B：hc_listen 进程
    pid_path = CFG_DIR / "hc_listen.pid"
    pid = None
    alive = False
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        alive = Path(f"/proc/{pid}").exists()
    except Exception:
        pass
    record("方案B：hc_listen 进程", alive,
           f"pid={pid}" if alive else "未运行（运行 python ~/laundry-xiaoai/tools/fix.py）")

    # 方案 B：令牌
    tok_ok, tok_detail = False, ""
    try:
        tok = json.loads((CFG_DIR / "homeconnect_token.json").read_text(encoding="utf-8"))
        exp = float(tok.get("expires_at") or 0)
        tok_ok = exp > time.time() + 60
        tok_detail = time.strftime("有效期至 %Y-%m-%d %H:%M", time.localtime(exp)) if exp else "缺少过期时间"
    except Exception as exc:  # noqa: BLE001
        tok_detail = f"没有令牌：{exc}"
    record("方案B：晶御令牌", tok_ok, tok_detail)

    # 方案 B：设备列表（会消耗 1 次 API 请求）
    try:
        cp = subprocess.run([sys.executable, str(APP_DIR / "hc_listen.py"), "--list"],
                            cwd=str(APP_DIR), capture_output=True, text=True, timeout=90)
        out = (cp.stdout or "") + (cp.stderr or "")
        found = [x for x in ("洗衣机", "干衣机", "Washer", "Dryer") if x in out]
        record("方案B：设备列表", bool(found), "、".join(found) if found else out.strip()[-180:])
    except Exception as exc:  # noqa: BLE001
        record("方案B：设备列表", False, str(exc))

    # 方案 B：SSE 事件通道
    hc_lines = tail(CFG_DIR / "hc_listen.log")
    conns = [ln for ln in hc_lines if "事件通道已连接" in ln]
    record("方案B：SSE 事件通道", bool(conns),
           conns[-1][:130] if conns else "日志里没有连接记录（看 hc_listen.log）")

    # 方案 B：最近完成事件（仅供确认，不算失败）
    fin = [ln for ln in hc_lines if "检测到完成事件" in ln]
    record("方案B：最近完成事件", True if fin else None,
           fin[-1][:130] if fin else "暂无（等下次洗/烘完成会出现，不影响其他检查）")

    # 汇总
    print()
    print("=" * 64)
    fails = [x for x in RESULTS if x[1] is False]
    infos = [x for x in RESULTS if x[1] is None]
    print(f"通过 {len(RESULTS) - len(fails) - len(infos)} / {len(RESULTS) - len(infos)}，"
          f"待验证 {len(infos)} 项")
    if fails:
        print("结论：⚠️ 有未通过项，按上面提示处理")
        for name, _, detail in fails:
            print(f"  - {name}：{detail}")
    else:
        print("结论：✅ 两个方案的链路都正常")
        if infos:
            print("（标 ℹ️ 的项只是还没有真实触发记录，不影响日常使用）")
    print("=" * 64)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
