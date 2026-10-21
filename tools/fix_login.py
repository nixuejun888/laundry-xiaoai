#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键修复小米登录令牌（mi.token 丢失 / 70016 登录验证失败）。

用法（Termux）：
    python ~/laundry-xiaoai/tools/fix_login.py

它会：
  1. 检查系统时间、网络代理、token 文件位置；
  2. 必要时引导重新登录小米账号（可重试、可用邮箱登录）；
  3. 可选保存密码（--save-password 自动续期）；
  4. 重启 bridge 并测试一句播报，最后给出结论。
"""
import asyncio
import getpass
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

HOME = Path.home()
APP_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_DIR") or (HOME / "laundry-xiaoai"))
CFG_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_HOME") or (HOME / ".config" / "laundry-xiaoai"))
TOKEN = CFG_DIR / "mi.token"
CONFIG = CFG_DIR / "config.json"
BRIDGE = "http://127.0.0.1:8765"


def banner(t):
    print("\n" + "=" * 62)
    print(t)
    print("=" * 62)


def check_clock():
    print("⏱  检查系统时间…")
    try:
        date_hdr = None
        try:
            with urllib.request.urlopen("https://www.mi.com/", timeout=10) as r:
                date_hdr = r.headers.get("Date")
        except urllib.error.HTTPError as exc:
            date_hdr = exc.headers.get("Date") if exc.headers else None
        if not date_hdr:
            raise RuntimeError("拿不到服务器时间")
        server = parsedate_to_datetime(date_hdr)
        skew = abs(time.time() - server.timestamp())
        if skew > 300:
            print(f"  ❌ 本机时间和服务器相差 {int(skew)} 秒，会被风控拦。")
            print("     处理：设置 → 系统 → 日期与时间 → 打开「自动设置」")
            return False
        print(f"  ✅ 时间正常（偏差 {int(skew)} 秒）")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ 无法校时（{exc}），请自行确认手机时间准确")
        return True


def check_proxy():
    proxies = {k: v for k, v in os.environ.items()
               if k.lower() in ("http_proxy", "https_proxy", "all_proxy") and v}
    if proxies:
        print("  ⚠️ 检测到代理环境变量：", proxies)
        print("     小米登录建议关掉 VPN/代理，用家庭 WiFi 或流量重试")
    return not proxies


def find_tokens():
    candidates = [
        TOKEN,
        HOME / ".mi.token",
        HOME / "laundry-xiaoai" / "mi.token",
        CFG_DIR / "mi.token.bak",
    ]
    found = [p for p in candidates if p.exists()]
    if found:
        print("  🔎 找到 token 文件：")
        for p in found:
            print(f"     {p}（{p.stat().st_size} B）")
        if TOKEN not in found:
            src = found[0]
            TOKEN.parent.mkdir(parents=True, exist_ok=True)
            TOKEN.write_bytes(src.read_bytes())
            try:
                TOKEN.chmod(0o600)
            except OSError:
                pass
            print(f"  ✅ 已复制 {src} → {TOKEN}")
    else:
        print("  🔎 没找到任何 mi.token")
    return TOKEN.exists()


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        CONFIG.chmod(0o600)
    except OSError:
        pass


class _Abort(Exception):
    pass


def ask(prompt):
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt) as exc:
        raise _Abort() from exc


def askpass(prompt):
    try:
        return getpass.getpass(prompt)
    except (EOFError, KeyboardInterrupt) as exc:
        raise _Abort() from exc


def ensure_miservice():
    try:
        import miservice  # noqa: F401
        return True
    except Exception:
        print("⏳ 安装 miservice…")
        for cmd in (
            [sys.executable, "-m", "pip", "install", "-q", "miservice",
             "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"],
            [sys.executable, "-m", "pip", "install", "-q", "miservice"],
        ):
            try:
                if subprocess.run(cmd, timeout=300).returncode == 0:
                    import importlib
                    importlib.invalidate_caches()
                    try:
                        import miservice  # noqa: F401
                        return True
                    except Exception:
                        continue
            except Exception:
                continue
        return False


async def do_login(username, password):
    from miservice import MiAccount, MiNAService
    account = MiAccount(str(TOKEN), username, password)
    await account.login(username, password)
    devices = await MiNAService(account).device_list()
    try:
        token = getattr(account, "token", None)
        if token:
            TOKEN.write_text(json.dumps(token, ensure_ascii=False), encoding="utf-8")
            TOKEN.chmod(0o600)
    except Exception:
        pass
    return account, devices


def login_with_retry(cfg, attempts=3):
    if not ensure_miservice():
        print("❌ miservice 安装失败，请手动：pip install miservice")
        return None
    default_user = cfg.get("username") or ""
    for i in range(1, attempts + 1):
        print(f"\n—— 第 {i}/{attempts} 次登录 ——")
        if default_user:
            print(f"（直接回车沿用上次账号：{default_user}）")
        username = ask("小米账号（手机号或邮箱）：").strip() or default_user
        if not username:
            print("❌ 账号不能为空")
            continue
        password = askpass("密码（输入不显示）：")
        if not password:
            print("❌ 密码不能为空")
            continue
        try:
            _, devices = asyncio.run(do_login(username, password))
            print(f"✅ 登录成功！账号下设备数：{len(devices or [])}")
            for d in (devices or [])[:10]:
                print(f"   - {d.get('name')}（{d.get('deviceID', '')[:8]}…）")
            cfg["username"] = username
            ans = ask("要保存密码以便自动续期吗？(y/N)：").strip().lower()
            if ans == "y":
                cfg["password"] = password
                print("✅ 已保存密码（仅本机 600 权限文件）")
            else:
                cfg.pop("password", None)
            save_config(cfg)
            return username
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            print(f"❌ 登录失败：{msg[:400]}")
            if "70016" in msg:
                print("   70016 = 小米账号登录验证失败（风控）。建议：")
                print("   1) 电脑浏览器打开 https://account.xiaomi.com 登录一次，完成短信验证；")
                print("   2) 确认手机时间和时区正确；")
                print("   3) 关掉 VPN/代理，必要时切 4G/5G 或换 WiFi；")
                print("   4) 试改用邮箱登录；")
                print("   5) 还不行等 30~60 分钟再试。")
            elif "密码" in msg or "password" in msg.lower():
                print("   提示：密码可能输错（隐藏输入容易错），可先用网页登录确认密码。")
            default_user = username
    return None


def restart_bridge():
    fix = APP_DIR / "tools" / "fix.py"
    if fix.exists():
        print("\n⏳ 重启服务…")
        subprocess.run([sys.executable, str(fix)], check=False)
    else:
        print("⚠️ 找不到 tools/fix.py，请手动重启 bridge")


def test_speak():
    print("\n⏳ 测试播报…")
    try:
        rc = subprocess.run([sys.executable, str(APP_DIR / "bridge.py"), "--test", "washer"],
                            cwd=str(APP_DIR), timeout=120).returncode
        if rc == 0:
            print("✅ 测试播报成功（小爱应该说话了）")
            return True
        print("⚠️ 测试播报返回非 0，请把上面的错误发我")
    except Exception as exc:  # noqa: BLE001
        print("⚠️ 测试播报异常：", exc)
    return False


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    banner("小米登录令牌一键修复")
    print(f"配置目录：{CFG_DIR}")
    cfg = load_config()

    print("\n① 检查 token 与基础环境")
    token_found = find_tokens()
    check_clock()
    check_proxy()

    print("\n② 尝试用现有 token 访问小米服务")
    ok = False
    if token_found:
        try:
            rc = subprocess.run([sys.executable, str(APP_DIR / "bridge.py"), "--list"],
                                cwd=str(APP_DIR), capture_output=True, text=True, timeout=90)
            out = (rc.stdout or "") + (rc.stderr or "")
            if rc.returncode == 0 and ("音箱" in out or "device" in out.lower() or "小爱" in out):
                print("✅ 现有 token 可用，无需重新登录")
                ok = True
            else:
                print("❌ 现有 token 不可用：", out.strip()[-300:])
        except Exception as exc:  # noqa: BLE001
            print("❌ 检查失败：", exc)
    else:
        print("❌ 没有 token，需要重新登录")

    if not ok:
        print("\n③ 重新登录小米账号")
        try:
            username = login_with_retry(cfg)
        except _Abort:
            print("\n已取消登录。")
            return 1
        if not username:
            print("\n❌ 登录仍未成功。请按上面的提示处理后再运行本脚本。")
            print("   （也可以把本脚本输出发我，我帮你判断）")
            return 1
        restart_bridge()
        test_speak()
    else:
        test_speak()

    banner("完成")
    print("建议再跑一次完整自检：")
    print("  python ~/laundry-xiaoai/tools/verify.py")
    print("如果播报正常，方案 A/B 就都通了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
