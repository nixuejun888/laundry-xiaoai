#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小爱洗衣提醒 · 从零一键安装（Termux / Android）

在 Termux 里粘一行即可开始：

    python -c "import urllib.request as u;exec(u.urlopen('https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main/install.py').read().decode())"

也支持先下载再运行：

    python install.py --base https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main

可用环境变量 / 参数：
    LAUNDRY_XIAOAI_BASE   下载源（默认 GitHub raw；国内可换镜像，见 README）
    LAUNDRY_XIAOAI_DIR    安装目录（默认 ~/laundry-xiaoai）
    LAUNDRY_XIAOAI_SKIP_LOGIN=1   跳过小米账号登录交互
    LAUNDRY_XIAOAI_HC=1   非交互地启用晶御官方 API 配置
    --base URL / --dir PATH / --skip-login / --skip-deps / --skip-test / --no-start / --hc / --no-hc
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main"
CDN_BASE = "https://cdn.jsdelivr.net/gh/nixuejun888/laundry-xiaoai@main"
FILES = [
    "bridge.py",
    "hc_listen.py",
    "tools/fix.py",
    "tools/diag.py",
    "tools/showlog.py",
    "tools/selftest.py",
    "tools/stop.py",
    "tools/hc_status.py",
    "tools/hc_announce.py",
    "tools/hc_config.py",
    "tools/verify.py",
    "tools/oneclick.py",
    "tools/rack.py",
    "tools/airer_diag.py",
    "tools/fix_token.py",
    "tools/fix_login.py",
    "examples/config.example.json",
    "examples/homeconnect.example.json",
    "README.md",
]

IS_TERMUX = "com.termux" in (os.environ.get("PREFIX") or "")
HOME = Path.home()
APP_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_DIR") or (HOME / "laundry-xiaoai"))
CFG_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_HOME") or (HOME / ".config" / "laundry-xiaoai"))


def log(msg=""):
    print(msg, flush=True)


def step(n, total, title):
    log()
    log(f"── 第 {n}/{total} 步：{title} " + "─" * 20)


def read_text(path: Path, default=""):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return default


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def download(base: str, rel: str, dest: Path):
    url = f"{base.rstrip('/')}/{rel}"
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "laundry-xiaoai-installer"})
            data = urllib.request.urlopen(req, timeout=40).read()
            if len(data) < 200:
                raise RuntimeError(f"内容太小（{len(data)} 字节）")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return len(data)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"下载 {rel} 失败：{last}")


def ensure_deps():
    try:
        import miservice  # noqa: F401
        log("✅ Python 依赖 miservice 已安装")
        return True
    except Exception:
        pass
    log("⏳ 安装 Python 依赖 miservice（可能需要 1~2 分钟）…")
    cmds = [
        [sys.executable, "-m", "pip", "install", "--upgrade", "miservice",
         "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"],
        [sys.executable, "-m", "pip", "install", "--upgrade", "miservice"],
    ]
    for cmd in cmds:
        try:
            rc = subprocess.run(cmd, check=False, timeout=300).returncode
            if rc == 0:
                import importlib
                importlib.invalidate_caches()
                try:
                    import miservice  # noqa: F401
                    log("✅ miservice 安装成功")
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    log("⚠️ miservice 安装失败（或超时）。可以稍后手动执行：")
    log("   pip install miservice -i https://pypi.tuna.tsinghua.edu.cn/simple")
    return False


def ensure_mi_token():
    token = CFG_DIR / "mi.token"
    if token.exists():
        log("✅ 已存在小米登录令牌，跳过登录")
        return True
    log("接下来需要登录小米账号（用于调用小爱音箱 TTS）。")
    log("按提示输入小米账号/密码；密码不会保存（除非之后用 --save-password 重启登录）。")
    rc = subprocess.run([sys.executable, str(APP_DIR / "bridge.py"), "--login"],
                        cwd=str(APP_DIR)).returncode
    if rc != 0:
        log("❌ 小米登录失败，请检查账号密码后重新运行安装。")
        return False
    return (CFG_DIR / "mi.token").exists()


def configure_speaker():
    cfg_path = CFG_DIR / "config.json"
    cfg = {}
    try:
        cfg = json.loads(read_text(cfg_path, "{}"))
    except Exception:
        cfg = {}
    if cfg.get("speaker"):
        log(f"✅ 当前只播报音箱：{cfg['speaker']}")
    log()
    log("列出账号下的音箱…")
    subprocess.run([sys.executable, str(APP_DIR / "bridge.py"), "--list"], cwd=str(APP_DIR))
    ans = input("\n只让某一台小爱播报？输入音箱名称关键字（回车=全部）：").strip()
    if ans:
        cfg["speaker"] = ans
        write_json(cfg_path, cfg)
        log(f"✅ 已设置 speaker = {ans}")
    else:
        log("✅ 保持全部音箱")


def test_speak():
    log()
    ans = input("现在测试播报（会让小爱说一句话），继续？(Y/n)：").strip().lower()
    if ans == "n":
        return False
    rc = subprocess.run([sys.executable, str(APP_DIR / "bridge.py"), "--test", "washer"],
                        cwd=str(APP_DIR)).returncode
    if rc == 0:
        log("✅ 测试播报完成")
    else:
        log("⚠️ 测试播报返回非 0，可稍后用 tools/diag.py 诊断")
    return rc == 0


def maybe_configure_hc(args):
    hc_cfg = CFG_DIR / "homeconnect.json"
    existing = {}
    try:
        existing = json.loads(read_text(hc_cfg, "{}"))
    except Exception:
        existing = {}
    want = args.hc
    if want is None:
        hc_env = os.environ.get("LAUNDRY_XIAOAI_HC")
        if hc_env == "1":
            want = True
        elif hc_env == "0":
            want = False
        elif existing.get("client_id"):
            want = True
        else:
            want = None
    if want is None:
        ans = input("\n要现在配置「晶御官方 API」（方案 B，需开发者 client_id）吗？(y/N)：").strip().lower()
        want = ans == "y"
    if not want:
        log("⏭ 跳过晶御官方 API（之后可运行 tools/hc_config.py 随时添加）")
        return False
    if not existing.get("client_id"):
        log("请粘贴开发者门户里的 client_id（Device Flow 应用）：")
        cid = input("client_id：").strip()
        if not cid:
            log("⏭ 没填 client_id，跳过")
            return False
        existing["client_id"] = cid
        secret = input("client_secret（通常没有，回车跳过）：").strip()
        existing["client_secret"] = secret
        write_json(hc_cfg, existing)
        log("✅ 已保存晶御配置")
    rc = subprocess.run([sys.executable, str(APP_DIR / "hc_listen.py"), "--login"],
                        cwd=str(APP_DIR)).returncode
    if rc != 0:
        log("⚠️ 晶御授权未完成，可稍后运行：python ~/laundry-xiaoai/tools/hc_config.py")
        return False
    return True


def start_services():
    if not IS_TERMUX:
        log("ℹ️ 非 Termux 环境，跳过开机自启/守护脚本，只启动 bridge 供测试。")
        subprocess.Popen([sys.executable, str(APP_DIR / "bridge.py")], cwd=str(APP_DIR))
        return
    fix = APP_DIR / "tools" / "fix.py"
    log("启动守护循环并做健康检查…")
    rc = subprocess.run([sys.executable, str(fix)], cwd=str(APP_DIR)).returncode
    if rc != 0:
        log("⚠️ 守护脚本启动失败，可手动运行：python ~/laundry-xiaoai/tools/fix.py")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="小爱洗衣提醒一键安装")
    parser.add_argument("--base", default=os.environ.get("LAUNDRY_XIAOAI_BASE") or DEFAULT_BASE)
    parser.add_argument("--dir", default=os.environ.get("LAUNDRY_XIAOAI_DIR") or str(HOME / "laundry-xiaoai"))
    parser.add_argument("--skip-login", action="store_true", default=os.environ.get("LAUNDRY_XIAOAI_SKIP_LOGIN") == "1")
    parser.add_argument("--skip-deps", action="store_true", default=os.environ.get("LAUNDRY_XIAOAI_SKIP_DEPS") == "1")
    parser.add_argument("--skip-test", action="store_true", default=os.environ.get("LAUNDRY_XIAOAI_SKIP_TEST") == "1")
    parser.add_argument("--no-start", action="store_true", default=os.environ.get("LAUNDRY_XIAOAI_NO_START") == "1")
    parser.add_argument("--hc", dest="hc", action="store_true", default=None)
    parser.add_argument("--no-hc", dest="hc", action="store_false")
    args = parser.parse_args(argv)
    base = args.base.rstrip("/")
    app_dir = Path(args.dir).expanduser()
    global APP_DIR
    APP_DIR = app_dir
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    app_dir.mkdir(parents=True, exist_ok=True)

    log("=" * 64)
    log(" 小爱洗衣提醒 · 一键安装")
    log("=" * 64)
    log(f"安装目录：{app_dir}")
    log(f"配置目录：{CFG_DIR}")
    log(f"下载源：  {base}")
    log(f"环境：    {'Termux' if IS_TERMUX else sys.platform}")
    total = 6

    step(1, total, "下载程序文件")
    try:
        try:
            for rel in FILES:
                dest = app_dir / rel
                size = download(base, rel, dest)
                log(f"  ✅ {rel}（{size} bytes）")
        except Exception as first_exc:  # noqa: BLE001
            if base.rstrip("/") == DEFAULT_BASE.rstrip("/"):
                log(f"⚠️ GitHub 下载失败（{first_exc}），自动切换 jsDelivr CDN 重试…")
                base = CDN_BASE
                for rel in FILES:
                    dest = app_dir / rel
                    size = download(base, rel, dest)
                    log(f"  ✅ {rel}（{size} bytes）")
            else:
                raise
    except Exception as exc:  # noqa: BLE001
        log(f"❌ {exc}")
        log()
        log("如果 GitHub raw 被墙/很慢，请换镜像源，例如：")
        log("  LAUNDRY_XIAOAI_BASE=https://ghproxy.net/https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main \\")
        log("    python -c \"import urllib.request as u;exec(u.urlopen('https://raw.githubusercontent.com/nixuejun888/laundry-xiaoai/main/install.py').read().decode())\"")
        return 1

    step(2, total, "安装 Python 依赖")
    if args.skip_deps:
        log("⏭ 已跳过")
    else:
        ensure_deps()

    step(3, total, "登录小米账号")
    if args.skip_login:
        log("⏭ 已跳过（之后运行 python ~/laundry-xiaoai/bridge.py --login）")
    elif not ensure_mi_token():
        return 1

    step(4, total, "选择音箱并测试播报")
    if args.skip_test:
        log("⏭ 已跳过")
    else:
        try:
            configure_speaker()
            test_speak()
        except (EOFError, KeyboardInterrupt):
            log("⏭ 已跳过")

    step(5, total, "（可选）配置晶御官方 API")
    try:
        maybe_configure_hc(args)
    except (EOFError, KeyboardInterrupt):
        log("⏭ 已跳过")

    step(6, total, "启动服务")
    if args.no_start:
        log("⏭ 已跳过（手动启动：python ~/laundry-xiaoai/bridge.py）")
    else:
        start_services()

    log()
    log("=" * 64)
    log("✅ 安装完成！")
    log("=" * 64)
    log(f"程序目录：{app_dir}")
    log(f"配置目录：{CFG_DIR}")
    log()
    log("常用命令：")
    log("  查看状态： python ~/laundry-xiaoai/tools/diag.py")
    log("  看日志：   python ~/laundry-xiaoai/tools/showlog.py")
    log("  更新/重启：python ~/laundry-xiaoai/tools/fix.py")
    log("  自测：     python ~/laundry-xiaoai/tools/selftest.py")
    log("  停止播放： python ~/laundry-xiaoai/tools/stop.py")
    log()
    log("最后一步（手机上手动做）：安装通知转发 App 并配置 URL/JSON，见 README 的")
    log("「安卓端配置」章节；或者等洗衣服时让小爱直接播报。")
    log("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
