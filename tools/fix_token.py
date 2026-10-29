#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小米 token 一键修复：更新 bridge → 必要时重登 → 固定 deviceId → 重启服务 → 体检。

用法（Termux，家里 WiFi）：
    python -c "import urllib.request as u;exec(u.urlopen('http://192.168.5.15:8788/fix_token.py',timeout=60).read().decode())"

外网（CDN）：
    python -c "import urllib.request as u;exec(u.urlopen('https://ghfast.top/https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main/tools/fix_token.py',timeout=60).read().decode())"

可选参数：
    --check       只检查，不下载/不重启
    --base URL    指定更新源
"""
import argparse
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
TOKEN = CFG_DIR / "mi.token"
CONFIG = CFG_DIR / "config.json"
BRIDGE = "http://127.0.0.1:8765"
LAN_BASE = "http://192.168.5.15:8788"
GHFAST_BASE = "https://ghfast.top/https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main"
GHPROXY_BASE = "https://gh-proxy.com/https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main"
RAW_BASE = "https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main"


def banner(t):
    print("\n" + "=" * 62)
    print(t)
    print("=" * 62)


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def pick_base(explicit="") -> str:
    if explicit:
        return explicit.rstrip("/")
    env = (os.environ.get("LAUNDRY_XIAOAI_BASE") or "").rstrip("/")
    if env:
        return env
    for cand in (LAN_BASE, GHFAST_BASE, GHPROXY_BASE, RAW_BASE):
        try:
            req = urllib.request.Request(cand + "/bridge.py", method="HEAD")
            with urllib.request.urlopen(req, timeout=4) as r:
                if r.status == 200:
                    return cand
        except Exception:
            continue
    return GHFAST_BASE


def download(base: str, rel: str, dest: Path):
    last = None
    for url in (f"{base}/{rel}", f"{base}/{Path(rel).name}"):
        try:
            data = urllib.request.urlopen(url, timeout=30).read()
            if len(data) < 500:
                last = RuntimeError("内容太小")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return len(data)
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f"{rel}: {last}")


def health():
    try:
        with urllib.request.urlopen(BRIDGE + "/health", timeout=4) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def status():
    cfg = load_json(CONFIG, {})
    tok = load_json(TOKEN, {})
    h = health() or {}
    print("\n—— 当前状态 ——")
    print("  bridge 在线：", bool(h.get("ok")))
    print("  token_exists：", h.get("token_exists", TOKEN.exists()))
    print("  passToken：", bool(tok.get("passToken")))
    print("  deviceId：", tok.get("deviceId") or "(无)")
    print("  config.device_id：", cfg.get("device_id") or "(未保存)")
    print("  password_saved：", bool(cfg.get("password")))
    return cfg, tok, h


def login_if_needed(cfg):
    if cfg.get("username") and cfg.get("password") and TOKEN.exists() and load_json(TOKEN, {}).get("passToken"):
        print("✅ 账号密码和 passToken 都在，跳过登录")
        return True
    print("\n需要登录一次小米账号（会提示输入密码/验证码）…")
    rc = subprocess.run([sys.executable, str(APP_DIR / "bridge.py"), "--login", "--save-password"],
                        cwd=str(APP_DIR)).returncode
    return rc == 0


def remember_device_id():
    cfg = load_json(CONFIG, {})
    tok = load_json(TOKEN, {})
    dev = str(tok.get("deviceId") or "")
    if dev and cfg.get("device_id") != dev:
        cfg["device_id"] = dev
        save_json(CONFIG, cfg)
        print(f"✅ 已把 deviceId 写入配置（{dev[:8]}…），以后重登不会被当新设备")
    elif cfg.get("device_id"):
        print("✅ device_id 已保存")


def restart(base: str):
    fix = APP_DIR / "tools" / "fix.py"
    if not fix.exists():
        fix.parent.mkdir(parents=True, exist_ok=True)
        download(base, "tools/fix.py", fix)
    print("\n⏳ 重启服务（tools/fix.py）…")
    env = dict(os.environ, LAUNDRY_XIAOAI_BASE=base)
    return subprocess.run([sys.executable, str(fix)], cwd=str(APP_DIR), env=env).returncode


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="小米 token 一键修复")
    parser.add_argument("--check", action="store_true", help="只检查，不下载/不重启")
    parser.add_argument("--base", default="", help="更新源")
    args = parser.parse_args()
    base = pick_base(args.base)

    banner("小米 token 一键修复")
    print(f"程序目录：{APP_DIR}")
    print(f"配置目录：{CFG_DIR}")
    print(f"更新源：  {base}")

    status()

    if args.check:
        print("\n（--check 只检查，不做修改）")
        return 0

    # 1) 更新 bridge.py（保留 passToken 等新特性）
    print("\n⏳ 更新 bridge.py…")
    try:
        size = download(base, "bridge.py", APP_DIR / "bridge.py")
        print(f"✅ bridge.py 已更新（{size} bytes）")
    except Exception as exc:  # noqa: BLE001
        print("⚠️ 更新失败（用本地已有版本继续）：", exc)

    # 2) 确保登录信息
    cfg = load_json(CONFIG, {})
    if not login_if_needed(cfg):
        print("❌ 登录未完成，先把上面的输出发我")
        return 1
    cfg = load_json(CONFIG, {})

    # 3) 固定 deviceId
    remember_device_id()

    # 4) 重启 + 健康检查
    restart(base)
    time.sleep(2)
    status()

    h = health() or {}
    if h.get("ok") and h.get("token_exists"):
        banner("修复完成")
        print("✅ token 存在，服务在线。以后 token 过期会自动续期，不用每天重登。")
        print("建议再跑一次完整自检：python ~/laundry-xiaoai/tools/verify.py")
        return 0
    banner("修复未完全成功")
    print("❌ 服务或 token 仍异常，把上面的输出发我。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
