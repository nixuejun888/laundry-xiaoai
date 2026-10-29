#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复/更新脚本与启动脚本，并重启播报服务（Termux）。

用法（Termux）：
    python ~/laundry-xiaoai/tools/fix.py

更新下载源可用环境变量覆盖（国内 GitHub 不稳时）：
    LAUNDRY_XIAOAI_BASE=https://ghproxy.net/https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main \
      python ~/laundry-xiaoai/tools/fix.py
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main"
HOME = Path.home()
APP_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_DIR") or (HOME / "laundry-xiaoai"))
CFG_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_HOME") or (HOME / ".config" / "laundry-xiaoai"))
BOOT_DIR = HOME / ".termux" / "boot"
CFG_DIR.mkdir(parents=True, exist_ok=True)
BOOT_DIR.mkdir(parents=True, exist_ok=True)

# 需要同步的文件：仓库相对路径 -> 安装目录相对路径
FILES = [
    ("bridge.py", "bridge.py"),
    ("xcloud.py", "xcloud.py"),
    ("hc_listen.py", "hc_listen.py"),
    ("tools/diag.py", "tools/diag.py"),
    ("tools/showlog.py", "tools/showlog.py"),
    ("tools/selftest.py", "tools/selftest.py"),
    ("tools/stop.py", "tools/stop.py"),
    ("tools/hc_status.py", "tools/hc_status.py"),
    ("tools/hc_announce.py", "tools/hc_announce.py"),
    ("tools/hc_config.py", "tools/hc_config.py"),
    ("tools/verify.py", "tools/verify.py"),
    ("tools/oneclick.py", "tools/oneclick.py"),
    ("tools/rack.py", "tools/rack.py"),
    ("tools/airer_diag.py", "tools/airer_diag.py"),
    ("tools/fix_token.py", "tools/fix_token.py"),
    ("tools/miot_check.py", "tools/miot_check.py"),
    ("tools/dlna_check.py", "tools/dlna_check.py"),
    ("tools/fix_login.py", "tools/fix_login.py"),
    ("sounds/washer.mp3", "sounds/washer.mp3"),
    ("sounds/dryer.mp3", "sounds/dryer.mp3"),
    ("sounds/linger.mp3", "sounds/linger.mp3"),
    ("sounds/supply.mp3", "sounds/supply.mp3"),
    ("sounds/rack_ready.mp3", "sounds/rack_ready.mp3"),
    ("sounds/generic.mp3", "sounds/generic.mp3"),
]

RUN_LOOP = r'''#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null
cd "$HOME/laundry-xiaoai" || exit 1
PID="$HOME/.config/laundry-xiaoai/bridge.pid"
SUP="$HOME/.config/laundry-xiaoai/supervisor.pid"
echo $$ > "$SUP"
while true; do
  if [ -f "$PID" ]; then
    p="$(cat "$PID" 2>/dev/null)"
    if [ -n "$p" ] && [ -r "/proc/$p/cmdline" ] && grep -q "bridge.py" "/proc/$p/cmdline" 2>/dev/null; then
      sleep 30
      continue
    fi
  fi
  python bridge.py >> "$HOME/.config/laundry-xiaoai/bridge.out" 2>&1
  sleep 10
done
'''

HC_LOOP = r'''#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null
cd "$HOME/laundry-xiaoai" || exit 1
echo $$ > "$HOME/.config/laundry-xiaoai/hc_loop.pid"
while true; do
  python hc_listen.py --run >> "$HOME/.config/laundry-xiaoai/hc_listen.out" 2>&1
  sleep 15
done
'''

BOOT_BASE = r'''#!/data/data/com.termux/files/usr/bin/bash
# 小爱洗衣提醒：开机自启 bridge 守护循环（以及可选的晶御官方 API 监听）
SUP="$HOME/.config/laundry-xiaoai/supervisor.pid"
BRIDGE_RUNNING=0
if [ -f "$SUP" ]; then
  p="$(cat "$SUP" 2>/dev/null)"
  if [ -n "$p" ] && [ -r "/proc/$p/cmdline" ] && grep -q "run-loop.sh" "/proc/$p/cmdline" 2>/dev/null; then
    BRIDGE_RUNNING=1
  fi
fi
if [ "$BRIDGE_RUNNING" = "0" ]; then
  nohup bash "$HOME/laundry-xiaoai/run-loop.sh" >/dev/null 2>&1 &
fi
'''

BOOT_HC = r'''
HC_LOOP="$HOME/laundry-xiaoai/hc-loop.sh"
if [ -f "$HC_LOOP" ]; then
  HCPID="$HOME/.config/laundry-xiaoai/hc_loop.pid"
  HC_RUNNING=0
  if [ -f "$HCPID" ]; then
    p="$(cat "$HCPID" 2>/dev/null)"
    if [ -n "$p" ] && [ -r "/proc/$p/cmdline" ] && grep -q "hc-loop.sh" "/proc/$p/cmdline" 2>/dev/null; then
      HC_RUNNING=1
    fi
  fi
  if [ "$HC_RUNNING" = "0" ]; then
    nohup bash "$HC_LOOP" >/dev/null 2>&1 &
  fi
fi
'''


def hc_configured():
    try:
        cfg = json.loads((CFG_DIR / "homeconnect.json").read_text(encoding="utf-8"))
        return bool(cfg.get("client_id"))
    except Exception:
        return False


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    base = (os.environ.get("LAUNDRY_XIAOAI_BASE") or DEFAULT_BASE).rstrip("/")
    MIRRORS = [
        "https://ghfast.top/https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main",
        "https://gh-proxy.com/https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main",
    ]
    print("=" * 60)
    print("修复/更新脚本并重启服务")
    print("安装目录：", APP_DIR)
    print("配置目录：", CFG_DIR)
    print("更新源：  ", base)
    print("晶御 API 已配置：", hc_configured())
    print("-" * 60)

    if not (APP_DIR / "bridge.py").exists():
        print("❌ 找不到", APP_DIR / "bridge.py")
        print("   请先运行一键安装：python -c \"import urllib.request as u;exec(u.urlopen('%s/install.py').read().decode())\"" % base)
        return 1

    # 1) 更新脚本（失败自动尝试国内镜像）
    bases = [base]
    if base.rstrip("/") == DEFAULT_BASE.rstrip("/"):
        bases += MIRRORS
    for try_base in bases:
        if try_base != base:
            print(f"⚠️ {base} 不可用，尝试镜像 {try_base.split('/')[2]} …")
        ok_all = True
        for rel, dest in FILES:
            try:
                data = urllib.request.urlopen(f"{try_base}/{rel}", timeout=30).read()
                if len(data) < 500:
                    print(f"⚠️ {rel} 内容太小，跳过")
                    continue
                target = APP_DIR / dest
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                print(f"✅ 已更新 {dest}（{len(data)} bytes）")
            except Exception as exc:  # noqa: BLE001
                print(f"⚠️ 更新 {rel} 失败：{exc}")
                ok_all = False
        if ok_all:
            base = try_base
            break


    # 2) 重新生成启动脚本
    (APP_DIR / "run-loop.sh").write_text(RUN_LOOP, encoding="utf-8")
    os.chmod(APP_DIR / "run-loop.sh", 0o755)
    boot = BOOT_BASE
    with_hc = hc_configured()
    if with_hc:
        (APP_DIR / "hc-loop.sh").write_text(HC_LOOP, encoding="utf-8")
        os.chmod(APP_DIR / "hc-loop.sh", 0o755)
        boot += BOOT_HC
    else:
        try:
            (APP_DIR / "hc-loop.sh").unlink()
        except OSError:
            pass
    (BOOT_DIR / "start-laundry.sh").write_text(boot, encoding="utf-8")
    os.chmod(BOOT_DIR / "start-laundry.sh", 0o755)
    print("✅ 已更新 run-loop.sh / hc-loop.sh / ~/.termux/boot/start-laundry.sh")

    # 3) 重启进程（加载新代码）
    for pat in ("run-loop.sh", "bridge.py", "hc-loop.sh", "hc_listen.py"):
        try:
            subprocess.run(["pkill", "-f", pat], capture_output=True, timeout=10)
        except Exception:
            pass
    time.sleep(1)

    # 4) 启动守护循环
    try:
        subprocess.Popen(["bash", str(APP_DIR / "run-loop.sh")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, cwd=str(APP_DIR))
        print("✅ 已启动 bridge 守护循环")
    except Exception as exc:  # noqa: BLE001
        print("❌ 启动 bridge 失败：", exc)
        return 1
    if with_hc:
        try:
            subprocess.Popen(["bash", str(APP_DIR / "hc-loop.sh")],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, cwd=str(APP_DIR))
            print("✅ 已启动晶御监听 hc-loop.sh")
        except Exception as exc:  # noqa: BLE001
            print("⚠️ 启动 hc-loop 失败：", exc)

    # 5) 健康检查
    ok = False
    for _ in range(10):
        time.sleep(1)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=3) as r:
                print("✅ 服务已就绪：", r.read().decode())
                ok = True
                break
        except Exception:
            continue
    if not ok:
        print("❌ 服务没起来，最近日志：")
        for name in ("bridge.out", "bridge.log"):
            p = CFG_DIR / name
            if p.exists():
                print(f"--- {name} ---")
                print("\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]))
    if with_hc:
        print("-" * 60)
        print("晶御监听日志：")
        for name in ("hc_listen.log", "hc_listen.out"):
            p = CFG_DIR / name
            if p.exists():
                print(f"--- {name} 最后几行 ---")
                print("\n".join(p.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
