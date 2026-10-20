#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""填写晶御 / Home Connect 开发者应用凭据，并可立即授权登录。

用法（Termux）：
    python ~/laundry-xiaoai/tools/hc_config.py

（需要先在 https://developer.home-connect.cn/user/register 注册并创建应用）
"""
import json
import subprocess
import sys
from pathlib import Path

CONFIG = Path.home() / ".config" / "laundry-xiaoai" / "homeconnect.json"
APP_DIR = Path.home() / "laundry-xiaoai"
HC_LISTEN = APP_DIR / "hc_listen.py"

DEFAULT = {
    "api_host": "https://api.home-connect.cn",
    "client_id": "",
    "client_secret": "",
    "scope": "IdentifyAppliance Monitor Washer-Monitor Dryer-Monitor",
    "redirect_uri": "https://api.home-connect.com",
    "bridge_url": "http://127.0.0.1:8765",
    "dryer_ignore_program_finished": True,
    "allow_operation_state_finished": False,
    "appliance_targets": {},
    "announce": {
        "mode": "finished",
        "global_min_interval_sec": 20,
        "per_key_min_interval_sec": 60,
        "remaining_thresholds_min": [60, 30, 10, 5, 1],
        "progress_thresholds_pct": [50, 75],
        "speak_unknown": False,
        "fill_level_min_interval_sec": 1800,
    },
}


def load():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("配置晶御 / Home Connect 开发者应用")
    print("-" * 60)
    print("还没注册的话，先去（Account Type 选 Individual，邮箱全部小写）：")
    print("  https://developer.home-connect.cn/user/register")
    print("建应用时注意：勾 Sync to China；")
    print("  Home Connect User Account for Testing 填晶御 +86 手机号（无空格）；")
    print("  应用类型选 Device Flow（手机端最省事）。")
    print("-" * 60)

    cfg = dict(DEFAULT)
    cfg.update(load())
    ann = dict(DEFAULT["announce"])
    ann.update(cfg.get("announce") or {})
    cfg["announce"] = ann

    cid = input("client_id（回车保留原值）：").strip() or cfg.get("client_id", "")
    csec = input("client_secret（Device Flow 应用通常没有，回车跳过）：").strip() or cfg.get("client_secret", "")
    ruri = input(f"redirect_uri（回车用 {cfg.get('redirect_uri') or 'https://api.home-connect.com'}）：").strip() \
        or cfg.get("redirect_uri") or "https://api.home-connect.com"
    cfg.update({"client_id": cid, "client_secret": csec, "redirect_uri": ruri})
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        CONFIG.chmod(0o600)
    except OSError:
        pass
    print("\n✅ 已保存：", CONFIG)
    if not cid:
        print("❌ client_id 为空，无法授权。")
        return 1
    if not HC_LISTEN.exists():
        print("❌ 找不到 hc_listen.py，请先运行一键安装或 tools/fix.py。")
        return 1

    ans = input("\n现在进行授权登录吗？(y/N)：").strip().lower()
    if ans != "y":
        print("稍后手动运行：python ~/laundry-xiaoai/hc_listen.py --login")
        return 0
    rc = subprocess.run([sys.executable, str(HC_LISTEN), "--login"], cwd=str(APP_DIR)).returncode
    if rc == 0:
        print("\n✅ 授权完成。接着运行下面的命令启用/重启监听：")
        print("  python ~/laundry-xiaoai/tools/fix.py")
        print("然后可以先看设备列表：")
        print("  python ~/laundry-xiaoai/hc_listen.py --list")
    return rc


if __name__ == "__main__":
    sys.exit(main())
