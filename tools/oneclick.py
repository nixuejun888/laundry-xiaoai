#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小爱洗衣提醒 · 一键中心（菜单）

用法（Termux）：
    python ~/laundry-xiaoai/tools/oneclick.py

一键全自动（无需选菜单）：
    python ~/laundry-xiaoai/tools/oneclick.py --auto

也可以直接远程运行（无需本地文件）：
    python -c "import urllib.request as u;exec(u.urlopen('http://192.168.5.15:8788/oneclick.py',timeout=60).read().decode())"

菜单覆盖：一键体检+自动修复 / 修小米登录 / 双方案自检 / 重启服务 / 测试播报 /
切换播报模式 / 看日志 / 停止播放 / 更新本地工具。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path.home()
APP_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_DIR") or (HOME / "laundry-xiaoai"))
CFG_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_HOME") or (HOME / ".config" / "laundry-xiaoai"))
BRIDGE = "http://127.0.0.1:8765"
REPO_RAW = "https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main"
LAN_BASE = "http://192.168.5.15:8788"
GHFAST_BASE = "https://ghfast.top/https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main"
GHPROXY_BASE = "https://gh-proxy.com/https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main"

# 仓库文件 -> 本地相对路径
FILES = [
    ("bridge.py", "bridge.py"),
    ("hc_listen.py", "hc_listen.py"),
    ("tools/fix.py", "tools/fix.py"),
    ("tools/verify.py", "tools/verify.py"),
    ("tools/fix_login.py", "tools/fix_login.py"),
    ("tools/diag.py", "tools/diag.py"),
    ("tools/showlog.py", "tools/showlog.py"),
    ("tools/selftest.py", "tools/selftest.py"),
    ("tools/stop.py", "tools/stop.py"),
    ("tools/hc_status.py", "tools/hc_status.py"),
    ("tools/hc_announce.py", "tools/hc_announce.py"),
    ("tools/hc_config.py", "tools/hc_config.py"),
    ("tools/oneclick.py", "tools/oneclick.py"),
    ("tools/fix_token.py", "tools/fix_token.py"),
    ("tools/miot_check.py", "tools/miot_check.py"),
    ("tools/dlna_check.py", "tools/dlna_check.py"),
    ("tools/rack.py", "tools/rack.py"),
]


def banner(t):
    print("\n" + "=" * 62)
    print(t)
    print("=" * 62)


def read_text(p, default=""):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return default


def write_json(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass


def find(*names):
    """在 APP_DIR 与 APP_DIR/tools 下找脚本。"""
    for name in names:
        for base in (APP_DIR, APP_DIR / "tools"):
            p = base / name
            if p.exists():
                return p
    return None


def http_json(url, payload=None, timeout=5):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bridge_health():
    try:
        return http_json(BRIDGE + "/health", timeout=4)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# 下载/更新
# --------------------------------------------------------------------------- #
def pick_base():
    env = (os.environ.get("LAUNDRY_XIAOAI_BASE") or "").rstrip("/")
    if env:
        return env
    for cand in (LAN_BASE, GHFAST_BASE, GHPROXY_BASE, REPO_RAW):
        try:
            req = urllib.request.Request(cand + "/bridge.py", method="HEAD")
            with urllib.request.urlopen(req, timeout=4) as r:
                if r.status == 200:
                    return cand
        except Exception:
            continue
    return REPO_RAW


def update_tools(verbose=True):
    base = pick_base()
    if verbose:
        print(f"更新源：{base}")
    ok = 0
    for rel, dest in FILES:
        name = Path(rel).name
        last_err = None
        for url in (f"{base}/{rel}", f"{base}/{name}"):
            try:
                data = urllib.request.urlopen(url, timeout=30).read()
                if len(data) < 500:
                    last_err = RuntimeError("内容太小")
                    continue
                target = APP_DIR / dest
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                ok += 1
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        if last_err is not None and verbose:
            print(f"  ⚠️ {rel} 更新失败：{last_err}")
    if verbose:
        print(f"✅ 本地工具已更新（{ok}/{len(FILES)} 个文件）")
    return ok


# --------------------------------------------------------------------------- #
# 服务控制
# --------------------------------------------------------------------------- #
def restart_service(quiet=False):
    fix = find("fix.py")
    if not fix:
        if not quiet:
            print("❌ 找不到 fix.py，先选 9 更新本地工具")
        return False
    print("⏳ 重启服务…" if not quiet else "⏳ 重启服务…")
    try:
        run_script(fix, timeout=600, base_env=pick_base())
    except Exception as exc:  # noqa: BLE001
        print("❌ 重启失败：", exc)
        return False
    return bridge_health() is not None


def ensure_service():
    h = bridge_health()
    if h and h.get("ok"):
        print("✅ bridge 已在线")
        return True
    print("bridge 不在线，尝试重启…")
    if restart_service():
        h = bridge_health() or {}
        print("✅ bridge 已恢复：", json.dumps(h, ensure_ascii=False)[:120])
        return True
    print("❌ bridge 起不来，日志：")
    for name in ("bridge.log", "bridge.out"):
        p = CFG_DIR / name
        if p.exists():
            print(f"--- {name} ---")
            print("\n".join(read_text(p).splitlines()[-15:]))
    return False


def token_ok():
    h = bridge_health() or {}
    return bool(h.get("token_exists"))


def run_script(path, args=(), timeout=600, base_env=None):
    env = dict(os.environ)
    if base_env:
        env["LAUNDRY_XIAOAI_BASE"] = base_env
    try:
        return subprocess.run([sys.executable, str(path), *args], timeout=timeout, env=env).returncode
    except Exception as exc:  # noqa: BLE001
        print("⚠️ 运行失败：", exc)
        return 1


# --------------------------------------------------------------------------- #
# 检查项
# --------------------------------------------------------------------------- #
def check_running():
    h = bridge_health()
    if not h:
        print("❌ bridge 不在线")
        return False
    print(f"✅ bridge 在线 — token={h.get('token_exists')} speaker={h.get('speaker')} "
          f"quiet_hours={h.get('quiet_hours')}")
    if not h.get("token_exists"):
        print("   ⚠️ 没有小米 token，选 2 修复登录")
    return True


def check_a():
    try:
        r = http_json(BRIDGE + "/notify", {"text": "文件传输助手: 洗衣已完成，请及时晾晒",
                                           "package": "com.tencent.mm"}, timeout=60)
        ok = bool(r.get("ok")) and (bool(r.get("spoken")) or r.get("skipped") in
                                    ("cooldown", "quiet-hours"))
        print(("✅" if ok else "❌"), "方案A：模拟微信通知 →", json.dumps(r, ensure_ascii=False)[:160])
        return ok
    except Exception as exc:  # noqa: BLE001
        print("❌ 方案A：模拟微信通知失败：", exc)
        return False


def check_b():
    """调用 tools/verify.py 做完整检查。"""
    v = find("verify.py")
    if not v:
        print("❌ 找不到 verify.py，先选 9 更新本地工具")
        return False
    print("⏳ 运行双方案自检…")
    rc = run_script(v, timeout=600)
    return rc == 0


def check_basic():
    check_running()
    if token_ok():
        check_a()
    else:
        print("⏭ 跳过播报测试（先修登录）")


# --------------------------------------------------------------------------- #
# 菜单动作
# --------------------------------------------------------------------------- #
def action_full_auto():
    banner("一键体检 + 自动修复")
    update_tools(verbose=False)
    ensure_service()
    if not token_ok():
        print("\n⚠️ 检测到没有小米 token，进入登录修复…")
        f = find("fix_login.py")
        if f:
            run_script(f)
        else:
            print("❌ 找不到 fix_login.py，先选 9 更新本地工具")
    print()
    print("测试播报…")
    b = find("bridge.py")
    if b:
        run_script(b, ("--test", "washer"), timeout=120)
    print()
    print("等 6 秒再自检（避免测试播报和自检播报互相打断）…")
    time.sleep(6)
    check_b()
    print("\n如果还有 ❌，把上面的输出发我。")


def action_login():
    banner("修复小米登录")
    f = find("fix_login.py")
    if not f:
        print("❌ 找不到 fix_login.py，先选 9 更新本地工具")
        return
    run_script(f)


def action_verify():
    banner("双方案自检")
    check_basic()
    check_b()


def action_restart():
    banner("重启服务")
    ensure_service()


def action_test_speak():
    banner("测试播报")
    b = find("bridge.py")
    if not b:
        print("❌ 找不到 bridge.py，先选 9 更新本地工具")
        return
    run_script(b, ("--test", "washer"), timeout=120)


def action_announce():
    banner("切换晶御播报模式")
    f = find("hc_announce.py")
    if not f:
        print("❌ 找不到 hc_announce.py，先选 9 更新本地工具")
        return
    run_script(f)


def action_logs():
    banner("最近日志")
    for name, path in (
        ("bridge.log", CFG_DIR / "bridge.log"),
        ("hc_listen.log", CFG_DIR / "hc_listen.log"),
    ):
        print(f"\n--- {name} ---")
        print("\n".join(read_text(path).splitlines()[-15:]) or "(空)")
    s = find("showlog.py")
    if s:
        print("\n提示：也可以运行", s)


def action_stop():
    banner("停止音箱播放")
    f = find("stop.py")
    if not f:
        print("❌ 找不到 stop.py，先选 9 更新本地工具")
        return
    run_script(f)


def action_hc_reauth():
    banner("晶御重新授权（方案 B）")
    hc = find("hc_listen.py")
    if not hc:
        print("❌ 找不到 hc_listen.py，先选 9 更新本地工具")
        return
    cfg_path = CFG_DIR / "homeconnect.json"
    try:
        cfg = json.loads(read_text(cfg_path, "{}"))
    except Exception:
        cfg = {}
    if not cfg.get("client_id"):
        print("还没配置 client_id，进入配置向导（需要开发者门户的 Client ID）…")
        c = find("hc_config.py")
        if not c:
            print("❌ 找不到 hc_config.py，先选 9 更新本地工具")
            return
        run_script(c)
        return
    print(f"当前 client_id：{str(cfg['client_id'])[:18]}…")
    ans = input("确定要重新走一次设备码授权吗？(y/N)：").strip().lower()
    if ans != "y":
        print("已取消。")
        return
    rc = run_script(hc, ("--login",), timeout=1200)
    if rc != 0:
        print("❌ 授权未完成。可重试，或把上面的输出发我。")
        return
    print("✅ 授权完成，重启服务让新令牌生效…")
    ensure_service()
    print("建议再选 3 做一次完整自检。")


def action_rack():
    banner("晾衣架联动设置")
    r = find("rack.py")
    if not r:
        print("❌ 找不到 rack.py，先选 9 更新本地工具")
        return
    run_script(r, timeout=1200)


def action_test_rack():
    banner("测试晾衣架联动")
    cfg_path = CFG_DIR / "config.json"
    try:
        cfg = json.loads(read_text(cfg_path, "{}"))
    except Exception:
        cfg = {}
    pa = cfg.get("post_actions") or {}
    print("当前 post_actions：")
    print(json.dumps(pa, ensure_ascii=False, indent=2) if pa else "(未配置)")
    if not pa.get("enabled") or not (pa.get("washer") or pa.get("dryer")):
        print("❌ 还没配置联动动作，请先选 11 配置晾衣架")
        return
    print()
    print("1) 只执行动作（不播报，测试晾衣架）")
    print("2) 完整测试（播报 + 动作）")
    mode = input("选择 1/2（回车=1）：").strip() or "1"
    b = find("bridge.py")
    if not b:
        print("❌ 找不到 bridge.py，先选 9 更新本地工具")
        return
    if mode == "2":
        print("发送 /washer（会播报并触发联动）…")
        try:
            with urllib.request.urlopen(BRIDGE + "/washer", timeout=120) as r:
                print("bridge 返回：", r.read().decode("utf-8", "replace")[:300])
        except Exception as exc:
            print("❌ 请求失败：", exc)
        print("等待联动和后续播报（约 10 秒）…")
        time.sleep(10)
    else:
        run_script(b, ("--run-actions", "washer"), timeout=120)
        time.sleep(6)
    print()
    print("看晾衣架是否下降；下面是对应日志：")
    try:
        lines = read_text(CFG_DIR / "bridge.log").splitlines()
        hit = [l for l in lines[-200:] if ("联动" in l or "MIoT play-text" in l)]
        print("\n".join(hit[-12:]) if hit else "(日志里没有联动记录)")
    except Exception:
        pass
    print()
    print("如果没反应：检查 DID/siid/piid 是否正确（选 11 重新配置或跑 rack.py --spec）。")


def action_fix_token():
    banner("小米 token 一键修复")
    f = find("fix_token.py")
    if not f:
        print("❌ 找不到 fix_token.py，先选 9 更新本地工具")
        return
    run_script(f, timeout=600)


def action_miot_check():
    banner("MIoT 通道诊断（-127 client withdraw）")
    f = find("miot_check.py")
    if not f:
        print("❌ 找不到 miot_check.py，先选 9 更新本地工具")
        return
    run_script(f, timeout=600)


def action_dlna_check():
    banner("局域网 DLNA 播放检测（绕开小米云的备选方案）")
    f = find("dlna_check.py")
    if not f:
        print("❌ 找不到 dlna_check.py，先选 9 更新本地工具")
        return
    run_script(f, timeout=300)


def action_update():
    banner("更新本地工具")
    n = update_tools()
    print(f"\n已保存到：{APP_DIR}（tools/ 子目录）")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="小爱洗衣提醒一键中心")
    parser.add_argument("--auto", action="store_true", help="全自动：更新工具→修复服务→必要时登录→测试→自检")
    parser.add_argument("--base", default="", help="更新源（可选）")
    args, _unknown = parser.parse_known_args()
    if args.base:
        os.environ["LAUNDRY_XIAOAI_BASE"] = args.base
    print("=" * 62)
    print("小爱洗衣提醒 · 一键中心")
    print("=" * 62)
    print(f"程序目录：{APP_DIR}")
    print(f"配置目录：{CFG_DIR}")

    # 首次运行先把工具补齐，后续菜单才能用
    if not find("bridge.py") or not find("verify.py"):
        print("\n首次运行：先补齐本地工具…")
        update_tools(verbose=False)

    while True:
        print("\n" + "-" * 62)
        print("请选择操作：")
        print("  1) 一键体检 + 自动修复（推荐）")
        print("  2) 修复小米登录")
        print("  3) 双方案自检")
        print("  4) 重启服务")
        print("  5) 测试播报")
        print("  6) 切换晶御播报模式")
        print("  7) 看最近日志")
        print("  8) 停止音箱播放")
        print("  9) 更新本地工具到最新")
        print(" 10) 晶御重新授权（方案 B）")
        print(" 11) 晾衣架联动设置（播报后自动下降）")
        print(" 12) 测试晾衣架联动（不播报/完整）")
        print(" 13) 小米 token 一键修复")
        print(" 14) MIoT 通道诊断（没声音时用）")
        print(" 15) 检测本地 DLNA 播放（更稳方案的可行性）")
        print("  0) 退出")
        try:
            choice = input("输入 1-15 或 0：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出。")
            return 0
        try:
            if choice == "1":
                action_full_auto()
            elif choice == "2":
                action_login()
            elif choice == "3":
                action_verify()
            elif choice == "4":
                action_restart()
            elif choice == "5":
                action_test_speak()
            elif choice == "6":
                action_announce()
            elif choice == "7":
                action_logs()
            elif choice == "8":
                action_stop()
            elif choice == "9":
                action_update()
            elif choice == "10":
                action_hc_reauth()
            elif choice == "11":
                action_rack()
            elif choice == "12":
                action_test_rack()
            elif choice == "13":
                action_fix_token()
            elif choice == "14":
                action_miot_check()
            elif choice == "15":
                action_dlna_check()
            elif choice == "0":
                print("再见。")
                return 0
            else:
                print("请输入 1-15 或 0。")
        except KeyboardInterrupt:
            print("\n已取消当前操作。")
        except Exception as exc:  # noqa: BLE001
            print("⚠️ 操作出错：", exc)


if __name__ == "__main__":
    sys.exit(main())
