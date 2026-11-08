#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置晾衣架自动下降高度（百分比）。

用法（Termux）：
    python ~/laundry-xiaoai/tools/set_rack_height.py            # 交互输入，默认 70
    python ~/laundry-xiaoai/tools/set_rack_height.py 70         # 直接设 70%
    python ~/laundry-xiaoai/tools/set_rack_height.py 70 --no-restart

说明：0 = 顶部（最高），100 = 底部（最低）。设置后会把 post_actions 里的
晾衣架动作改为 miot_airer_to，下降时按目标高度自动停。
"""
import argparse
import json
import os
import signal
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
APP_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_DIR") or (HOME / "laundry-xiaoai"))
CFG_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_HOME") or (HOME / ".config" / "laundry-xiaoai"))
CONFIG = CFG_DIR / "config.json"
PID = CFG_DIR / "bridge.pid"
DEFAULT_TEXT = "晾衣架已准备就绪，去晾衣服吧"


def load_cfg() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cfg(cfg: dict) -> None:
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(CONFIG)


def convert_actions(cfg: dict, percent: int, categories) -> int:
    pa = cfg.setdefault("post_actions", {})
    pa["enabled"] = True
    changed = 0
    for cat in categories:
        actions = pa.get(cat) or []
        if not actions:
            print(f"⚠️ {cat} 没有配置联动动作，跳过（可先跑 rack.py 配置）")
            continue
        old = actions[0]
        did = str(old.get("did") or "")
        if not did:
            print(f"⚠️ {cat} 旧动作缺少 did，跳过")
            continue
        new = {
            "type": "miot_airer_to",
            "did": did,
            "position": percent,
            "delay_sec": float(old.get("delay_sec") or 3),
            "timeout_sec": 120,
            "poll_sec": 2,
            "followup_text": old.get("followup_text") or DEFAULT_TEXT,
            "followup_delay_sec": 0,
        }
        pa[cat] = [new] + [a for a in actions[1:] if a is not old]
        changed += 1
        print(f"✅ {cat}: 下降目标 {percent}%（did={did}）")
    cfg["rack_target_position"] = percent
    return changed


def restart_bridge() -> bool:
    try:
        pid = int(PID.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
        print(f"⏳ 已通知 bridge 重启（pid={pid}）…")
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 未找到 bridge pid（{exc}），请稍后手动重启")
        return False
    cfg = load_cfg()
    port = int(cfg.get("listen_port") or 8765)
    for _ in range(40):
        time.sleep(1)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    print("✅ bridge 已重启并在线")
                    return True
        except Exception:
            continue
    print("⚠️ 等待 bridge 重启超时，可运行 fix.py 或一键中心 4")
    return False


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="设置晾衣架自动下降高度")
    parser.add_argument("percent", nargs="?", type=int, help="0=顶部，100=底部")
    parser.add_argument("--category", action="append", default=None,
                        help="要设置的类别（默认自动：washer / dryer）")
    parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args()

    cfg = load_cfg()
    percent = args.percent
    if percent is None:
        raw = input("下降到多少百分比？（0=顶部，100=底部，默认 70）：").strip()
        percent = int(raw) if raw else 70
    if not 0 <= percent <= 100:
        print("❌ 百分比必须在 0~100 之间")
        return 1

    categories = args.category
    if not categories:
        pa = cfg.get("post_actions") or {}
        categories = [c for c in ("washer", "dryer") if pa.get(c)]
        if not categories:
            categories = ["washer"]
    if convert_actions(cfg, percent, categories) == 0:
        return 1
    save_cfg(cfg)
    print(f"✅ 已保存到 {CONFIG}")
    if not args.no_restart:
        restart_bridge()
    else:
        print("提示：配置已保存，重启 bridge 后生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
