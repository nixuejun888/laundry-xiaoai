#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小爱洗衣提醒桥（bridge.py）

作用：在手机上（Termux）常驻一个本地 HTTP 服务。手机端任意能发 HTTP 请求的
自动化 App（MacroDroid / Tasker / 通知转发类 App）收到「博世洗衣完成」的微信
通知后，GET 一下本服务，本服务调用小米云 MiNA 接口，让小爱音箱语音播报。

只用标准库 + miservice（miservice 自带 urllib 后备客户端，Termux 里
`pip install miservice` 即可，不需要 aiohttp）。

常用命令
--------
  python bridge.py --login            # 首次/重新登录，交互输入小米账号密码(可能要短信验证码)
  python bridge.py --login --save-password   # 登录并把密码也存进配置文件（重启免登录）
  python bridge.py --list             # 用已保存的 token 列出账号下的小爱设备
  python bridge.py                    # 常驻服务，默认监听 127.0.0.1:8765
  python bridge.py --dry-run          # 不连小米，只测试 HTTP 流程
  python bridge.py --test washer      # 真播报一次预设文案（washer/dryer/linger/generic）
  python bridge.py --test-text "你好"  # 真播报一段任意文字
  python bridge.py --classify "洗衣已完成，请及时晾晒"   # 只测试关键词分类，不发请求

HTTP 接口（只绑定 127.0.0.1，仅本机可访问）
------------------------------------------
  GET  /health                健康检查
  GET  /washer                播报「洗衣完成」
  GET  /dryer                 播报「烘干完成」
  GET  /linger                播报「衣物滞留提醒」
  GET  /generic               播报通用提醒
  GET  /test?text=xxx         播报任意文本
  GET/POST /notify?text=xxx   按关键词自动分类后播报（关键词没命中则不播报）

配置文件：~/.config/laundry-alert/config.json
登录缓存：~/.config/laundry-alert/mi.token
运行日志：~/.config/laundry-alert/bridge.log
"""

import argparse
import asyncio
import copy
import json
import logging
import os
import sys
import threading
import time
from getpass import getpass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_NAME = "laundry-xiaoai"
CONFIG_DIR = Path.home() / ".config" / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"
TOKEN_PATH = CONFIG_DIR / "mi.token"
LOG_PATH = CONFIG_DIR / "bridge.log"
PID_PATH = CONFIG_DIR / "bridge.pid"

DEFAULT_CONFIG = {
    # 小米账号：--login 会自动写入。password 默认不保存（安全），
    # 需要重启后自动续期可加 --save-password。
    "username": "",
    "password": "",
    # 音箱选择：留空 = 播报到账号下所有小爱音箱；填设备名称关键字 = 只播该台。
    # 名字可以用 `python bridge.py --list` 查看。
    "speaker": "",
    # 播报前把音量设成多少（0-100）；null = 不动音量。
    "volume": None,
    # 播报通道：auto = 自动（新型号 OH2/OH2P 这类走 MIoT play-text 指令，其它走 MiNA 云端 TTS）
    # mina = 强制走 MiNA 云端 TTS；miot = 强制走 MIoT play-text
    "tts_channel": "auto",
    # 手动指定 MIoT play-text 的 siid/aiid，例如 {"siid": 5, "aiid": 3}；一般不用填（auto 会按型号查表）
    "miot_tts": {},
    # Web 服务监听地址。只给手机本机用就保持 127.0.0.1。
    "listen_host": "127.0.0.1",
    "listen_port": 8765,
    # 去抖：同一类别 N 秒内只播一次，防止微信通知重复/刷新导致复读。
    "cooldown_sec": 300,
    "cooldown_linger_sec": 1800,
    # 全局最小播报间隔（秒）：防止两个触发源同时到达时，第二条 TTS 打断正在播的第一句。
    # 0 = 关闭该保护。
    "min_gap_sec": 4,
    # 免打扰时段：在这个时间段内不播报（适合半夜洗完的衣服）。
    # enabled=false 关闭；支持跨零点，例如 23:00 -> 07:30。
    "quiet_hours": {"enabled": False, "start": "23:00", "end": "07:30"},
    # 播报文案，按需改成你喜欢的说法。
    "messages": {
        "washer": "洗衣机洗好了，记得及时晾晒哦",
        "dryer": "衣服烘干了，记得及时取出哦",
        "linger": "衣服还在洗衣机里，记得及时取出，防止褶皱和异味",
        "supply": "洗衣液或柔顺剂不足了，记得补充哦",
        "generic": "有新的洗衣提醒，请查看手机",
    },
    # 关键词分类（按顺序匹配，命中第一个就停）。
    # 收到真实通知后可以把原文里的特征词补进来，再用 --classify 验证。
    "keywords": {
        "supply": ["洗衣液不足", "柔顺剂不足", "洗涤剂不足", "补充洗衣液",
                   "请添加洗衣液", "请补充柔顺剂", "耗材不足", "请补充洗涤剂"],
        "washer": ["洗衣已完成", "洗涤完成", "洗衣完成", "请及时晾晒", "洗涤结束"],
        "dryer": ["烘干已完成", "烘干完成", "烘衣完成", "烘干结束"],
        "linger": ["长时间在筒内滞留", "筒内滞留", "桶内滞留"],
    },
    # 通知转发 App（如 Notifikator）会在 /notify 的 JSON 里带 package 字段；
    # 这里限定只处理微信的通知，避免其他 App 的文本误触发。
    # 留空 [] = 不按包名过滤；请求里没带 package 时也按不过滤处理。
    "notify_package_allow": ["com.tencent.mm"],
    # 播报成功后的联动动作（例如：洗衣机洗完 → 晾衣架自动下降）。
    # 用 tools/rack.py 配置和测试；enabled=false 时全部不执行。
    "post_actions": {
        "enabled": False,
        # washer / dryer 等类别名 -> 动作列表，按顺序执行
        # 动作类型：
        #   miot_set_prop: {"did":"...","siid":2,"piid":5,"value":2,"delay_sec":3}
        #   miot_action : {"did":"...","siid":2,"aiid":1,"args":[],"delay_sec":0}
        #   http        : {"url":"http://...","method":"GET","delay_sec":0}
        # 每个动作可选 followup_text / followup_delay_sec：
        #   动作成功后延迟 N 秒再播报一句（例如晾衣架降到底后提醒去晾衣服）
        "washer": [],
        "dryer": [],
    },
}

log = logging.getLogger(APP_NAME)
LOCK = threading.Lock()
LAST_SPOKEN = {}  # category -> monotonic timestamp
LAST_ANY_SPOKEN = [0.0]  # 上一次真正开始播报的时间（全局，防 TTS 互相打断）
SPEAK_EXEC_LOCK = threading.Lock()  # 串行化 TTS 调用，避免并发命令互相抢占


# --------------------------------------------------------------------------- #
# 配置 / 日志
# --------------------------------------------------------------------------- #
def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass


def deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def save_config(cfg: dict):
    ensure_dirs()
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(CONFIG_PATH)


def load_config() -> dict:
    ensure_dirs()
    data = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as exc:  # 配置损坏时用默认值，但别覆盖用户文件
            log.warning("配置文件解析失败(%s)，本次使用默认配置", exc)
            data = {}
    cfg = deep_merge(DEFAULT_CONFIG, data)
    if not CONFIG_PATH.exists():
        save_config(cfg)
    return cfg


def setup_logging(verbose: bool = False):
    ensure_dirs()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    try:
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.setLevel(logging.DEBUG if verbose else logging.INFO)
        root.addHandler(fh)
    except OSError:
        pass
    logging.getLogger("miservice").setLevel(logging.WARNING)


def classify(text: str, cfg: dict):
    """按关键词把通知文本分类；命中不了返回 None。"""
    t = text or ""
    for cat in ("supply", "washer", "dryer", "linger"):
        for kw in cfg["keywords"].get(cat, []):
            if kw and kw in t:
                return cat
    return None


def _parse_hhmm(value) -> "int | None":
    """'23:30' -> 23*60+30；解析失败返回 None。"""
    try:
        hh, mm = str(value).strip().split(":")
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except (ValueError, AttributeError):
        pass
    return None


def in_quiet_hours(cfg: dict, now=None) -> bool:
    """当前是否处于免打扰时段（支持跨零点，如 23:00-07:30）。"""
    qh = cfg.get("quiet_hours") or {}
    if not qh.get("enabled"):
        return False
    start = _parse_hhmm(qh.get("start", "23:00"))
    end = _parse_hhmm(qh.get("end", "07:30"))
    if start is None or end is None or start == end:
        return False
    t = now or time.localtime()
    cur = t.tm_hour * 60 + t.tm_min
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


# --------------------------------------------------------------------------- #
# 小米云：MiNA 小爱音箱 TTS
# --------------------------------------------------------------------------- #
def _import_miservice():
    from miservice import MiAccount, MiNAService  # 延迟导入，--dry-run 不依赖
    return MiAccount, MiNAService


async def _miio_service_async(cfg: dict):
    """用本机保存的小米账号构造 MiIOService（用于联动控制其他米家设备）。"""
    from miservice import MiAccount, MiIOService
    account = MiAccount(None, cfg.get("username") or "", cfg.get("password") or "",
                        str(TOKEN_PATH))
    return MiIOService(account)


def _code_of(result) -> int:
    if isinstance(result, int):
        return result
    if isinstance(result, dict):
        return int(result.get("code", -1))
    if isinstance(result, list) and result:
        return _code_of(result[0])
    return -1


async def _miot_set_prop_async(cfg: dict, did: str, siid: int, piid: int, value):
    service = await _miio_service_async(cfg)
    return _code_of(await service.miot_set_prop(str(did), (siid, piid), value))


async def _miot_action_async(cfg: dict, did: str, siid: int, aiid: int, args):
    service = await _miio_service_async(cfg)
    return _code_of(await service.miot_action(str(did), (siid, aiid), list(args or [])))


def _fmt_devices(devices) -> str:
    lines = []
    for i, d in enumerate(devices or [], 1):
        lines.append(
            f"{i}. name={d.get('name')} | hardware={d.get('hardware')} "
            f"| deviceID={d.get('deviceID')} | miotDID={d.get('miotDID')}"
        )
    return "\n".join(lines) if lines else "(空)"


def pick_targets(devices, speaker: str):
    if not speaker:
        return list(devices or [])
    needle = speaker.strip().lower()
    return [
        d for d in (devices or [])
        if needle in (d.get("name") or "").lower()
        or needle in (d.get("hardware") or "").lower()
        or needle == str(d.get("miotDID") or "").lower()
    ]


# 不同型号的 MIoT play-text 指令 (siid, aiid)。
# 来源：mi-gpt / xiaomi-speaker 等项目的型号兼容表（OH2 = Xiaomi 智能音箱，OH2P = Pro）。
# MiNA 的 mibrain/text_to_speech 在部分新型号上会返回成功但不出声，需要改用 MIoT 指令。
MIOT_TTS_COMMANDS = {
    "OH2": (5, 3),
    "OH2P": (7, 3),
}


def pick_tts_channel(cfg: dict, device: dict):
    """返回 (channel, iid)；channel 为 'miot' 时 iid=(siid, aiid)。"""
    mode = str(cfg.get("tts_channel") or "auto").lower()
    hw = (device.get("hardware") or "").upper()
    custom = cfg.get("miot_tts") or {}
    try:
        custom_iid = (int(custom["siid"]), int(custom["aiid"]))
    except Exception:
        custom_iid = None

    if mode == "mina":
        return "mina", None
    if mode == "miot":
        return "miot", custom_iid or MIOT_TTS_COMMANDS.get(hw) or (5, 3)
    # auto
    if custom_iid:
        return "miot", custom_iid
    if hw in MIOT_TTS_COMMANDS:
        return "miot", MIOT_TTS_COMMANDS[hw]
    return "mina", None


async def speak_async(text: str, cfg: dict, dry_run: bool = False) -> dict:
    if dry_run:
        log.info("[dry-run] 本应播报: %s", text)
        return {"ok": True, "dry_run": True, "spoken": text, "devices": ["dry-run"]}

    try:
        MiAccount, MiNAService = _import_miservice()
    except Exception:
        return {"ok": False, "error": "未安装 miservice：请先执行 pip install miservice"}

    account = MiAccount(
        None,
        cfg.get("username") or "",
        cfg.get("password") or "",
        str(TOKEN_PATH),
    )
    try:
        service = MiNAService(account)
        devices = await service.device_list()
        if not devices:
            return {
                "ok": False,
                "error": "账号下没有找到小爱音箱（MiNA 设备为空）。请确认账号正确、"
                         "音箱已绑定米家，或运行 python bridge.py --list 查看。",
            }
        targets = pick_targets(devices, cfg.get("speaker") or "")
        if not targets:
            return {
                "ok": False,
                "error": f"没有匹配到 speaker={cfg.get('speaker')!r} 的音箱。"
                         f"账号下设备：\n{_fmt_devices(devices)}",
            }

        spoken, failed = [], []
        channels = {}
        miio = None
        for d in targets:
            did = d.get("deviceID")
            name = d.get("name") or str(did)
            channel, iid = pick_tts_channel(cfg, d)
            channels[name] = channel
            try:
                if cfg.get("volume") is not None:
                    await service.player_set_volume(did, int(cfg["volume"]))
                ok = False
                if channel == "miot":
                    miot_did = str(d.get("miotDID") or "")
                    try:
                        from miservice import MiIOService
                        miio = miio or MiIOService(account)
                        code = await miio.miot_action(miot_did, iid, [text])
                        log.info("MIoT play-text %s siid=%s aiid=%s -> code=%s", name, iid[0], iid[1], code)
                        ok = (code == 0)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("MIoT 播报失败，回退 MiNA：%s", exc)
                if not ok:
                    ok = await service.text_to_speech(did, text)
                (spoken if ok else failed).append(name)
            except Exception as exc:
                log.exception("播报失败 %s: %s", name, exc)
                failed.append(name)

        result = {"ok": bool(spoken), "spoken": spoken, "failed": failed, "channels": channels}
        if failed and not spoken:
            result["error"] = "所有音箱播报失败，详见日志"
        return result
    except Exception as exc:
        msg = str(exc)
        hint = ""
        low = msg.lower()
        if any(k in low for k in ("login", "auth", "401", "token")):
            hint = "（登录可能失效：在 Termux 里运行 python bridge.py --login 重新登录）"
        log.exception("调用小米云失败: %s", exc)
        return {"ok": False, "error": msg + hint}


async def login_async(cfg: dict, save_password: bool, only_list: bool = False) -> int:
    MiAccount, MiNAService = _import_miservice()

    username = (cfg.get("username") or "").strip()
    password = cfg.get("password") or ""
    if not only_list:
        if not username:
            username = input("小米账号（手机号/邮箱）：").strip()
        if not password:
            password = getpass("小米账号密码（输入不显示，不会上传到别处）：")

    if not username:
        print("缺少小米账号。")
        return 2

    account = MiAccount(None, username, password, str(TOKEN_PATH))
    service = MiNAService(account)
    try:
        devices = await service.device_list()
    except Exception as exc:
        print(f"\n登录/请求失败：{exc}")
        print("常见处理：")
        print("  1) 有短信/邮箱验证码时，直接在本终端按提示输入；")
        print("  2) 提示风控(KJZH001 等)时，换手机流量/稍后重试，或先用电脑登录一次；")
        print("  3) 确认账号密码正确，账号已绑定小爱音箱。")
        return 1

    cfg["username"] = username
    cfg["password"] = password if save_password else ""
    save_config(cfg)

    print("\n登录成功，token 已保存到：", TOKEN_PATH)
    print("账号下的小爱设备：")
    print(_fmt_devices(devices))
    if not devices:
        print("\n注意：没有找到 MiNA 设备。请确认该小米账号已绑定小爱音箱。")
    return 0


async def list_async(cfg: dict) -> int:
    return await login_async(cfg, save_password=False, only_list=True)


# --------------------------------------------------------------------------- #
# HTTP 服务
# --------------------------------------------------------------------------- #
class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "LaundryXiaoAi/1.1"
    cfg: dict = {}
    dry_run: bool = False
    last_result: dict = {}

    # 覆盖默认的 access log 走 logging
    def log_message(self, fmt, *args):
        log.info("%s " + fmt, self.address_string(), *args)

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    # ---------------- 内部 ----------------
    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if not length:
            return {}
        try:
            raw = self.rfile.read(length).decode("utf-8", "replace")
        except Exception:
            return {}
        if not raw:
            return {}
        ctype = (self.headers.get("Content-Type") or "").lower()
        if "x-www-form-urlencoded" in ctype:
            form = parse_qs(raw)
            return {"text": (form.get("text") or [""])[0]}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {"text": raw}
        except Exception:
            return {"text": raw}

    def _write_json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _route(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)
        text = (qs.get("text") or [""])[0]
        pkg = (qs.get("package") or [""])[0]
        if method == "POST":
            body = self._read_json()
            text = body.get("text") or text
            pkg = body.get("package") or pkg

        try:
            if path == "/":
                return self._write_json(200, {
                    "ok": True,
                    "service": APP_NAME,
                    "endpoints": ["/health", "/washer", "/dryer", "/linger",
                                  "/generic", "/test?text=...", "/say?text=...", "/notify?text=..."],
                })
            if path == "/health":
                return self._write_json(200, {
                    "ok": True,
                    "dry_run": self.dry_run,
                    "token_exists": TOKEN_PATH.exists(),
                    "speaker": self.cfg.get("speaker") or "(全部)",
                    "quiet_hours": in_quiet_hours(self.cfg),
                    "last": self.last_result,
                })
            if path == "/say":
                if not text:
                    return self._write_json(400, {"ok": False, "error": "缺少 text 参数"})
                # 播报任意文本，不做类别去抖（调用方自己做节流），但免打扰时段仍然生效
                return self._speak("say", text, bypass_cooldown=True)
            if path == "/test":
                if not text:
                    return self._write_json(400, {"ok": False, "error": "缺少 text 参数"})
                return self._speak("test", text)
            if path == "/notify":
                if not text:
                    return self._write_json(400, {"ok": False, "error": "缺少 text 参数"})
                log.info("收到通知：package=%s text=%r", pkg or "(未提供)", (text or "")[:150])
                allow = self.cfg.get("notify_package_allow") or []
                if allow and pkg and pkg not in allow:
                    log.info("通知被包名过滤掉：package=%s（允许列表=%s）", pkg, allow)
                    return self._write_json(200, {
                        "ok": True, "skipped": "package-filtered",
                        "package": pkg, "allow": allow,
                    })
                cat = classify(text, self.cfg)
                if cat is None:
                    log.info("通知关键词没命中，跳过：%r", (text or "")[:150])
                    return self._write_json(200, {
                        "ok": True, "skipped": "no-keyword",
                        "hint": "关键词没命中，可编辑 config.json 的 keywords 后重启",
                        "text": text,
                    })
                log.info("通知命中分类 %s，开始播报", cat)
                return self._speak(cat, self.cfg["messages"].get(cat) or self.cfg["messages"]["generic"])

            cat = path.lstrip("/")
            if cat in ("washer", "dryer", "linger", "supply", "generic"):
                return self._speak(cat, self.cfg["messages"].get(cat) or self.cfg["messages"]["generic"])

            return self._write_json(404, {"ok": False, "error": f"未知路径 {path}"})
        except Exception as exc:  # 不让 handler 崩掉服务
            log.exception("处理请求失败: %s", exc)
            return self._write_json(500, {"ok": False, "error": str(exc)})

    def _do_speak(self, category: str, text: str, bypass_cooldown: bool = False) -> dict:
        """执行一次播报并返回结果 dict（不写 HTTP 响应，供后台任务复用）。"""
        if in_quiet_hours(self.cfg):
            log.info("免打扰时段，跳过播报 category=%s", category)
            return {"ok": True, "skipped": "quiet-hours", "category": category}
        now = time.monotonic()
        gap = float(self.cfg.get("min_gap_sec") or 0)
        cooldown = self.cfg["cooldown_linger_sec"] if category == "linger" else self.cfg["cooldown_sec"]
        with LOCK:
            last_any = LAST_ANY_SPOKEN[0]
            if gap > 0 and last_any and now - last_any < gap:
                remain = int(gap - (now - last_any)) + 1
                log.info("全局防打断跳过 category=%s（%ss 内刚播过）", category, remain)
                return {"ok": True, "skipped": "too-soon",
                        "category": category, "remain_sec": remain}
            if not bypass_cooldown:
                last = LAST_SPOKEN.get(category)
                if last is not None and now - last < cooldown:
                    remain = int(cooldown - (now - last))
                    log.info("去抖跳过 category=%s，%ss 后可再播", category, remain)
                    return {"ok": True, "skipped": "cooldown",
                            "category": category, "remain_sec": remain}
                # 先占位，避免同一通知的并发触发（如 App 重试/通知刷新）重复播报；
                # 播报失败时下面再释放。
                LAST_SPOKEN[category] = now
            LAST_ANY_SPOKEN[0] = now

        # 串行化真正的 TTS 调用：两条播报命令重叠时，小爱往往只读到一半就被打断
        with SPEAK_EXEC_LOCK:
            result = asyncio.run(speak_async(text, self.cfg, self.dry_run))
        result.update({"category": category, "text": text})
        if result.get("ok") and not bypass_cooldown:
            with LOCK:
                LAST_SPOKEN[category] = time.monotonic()
        type(self).last_result = dict(result, ts=time.strftime("%Y-%m-%d %H:%M:%S"))
        if result.get("ok"):
            self._run_post_actions(category)
        return result

    def _speak(self, category: str, text: str, bypass_cooldown: bool = False):
        result = self._do_speak(category, text, bypass_cooldown)
        code = 200 if result.get("ok") else 500
        return self._write_json(code, result)

    def _speak_followup(self, text: str, delay: float):
        """联动动作完成后（如晾衣架降到底）再播报一句。"""
        if delay > 0:
            time.sleep(delay)
        result = self._do_speak("rack_ready", text, bypass_cooldown=True)
        log.info("联动后续播报：%s -> %s", text,
                 result.get("skipped") or ("ok" if result.get("ok") else result.get("error")))

    # ---------------- 播报后联动动作 ----------------
    def _run_post_actions(self, category: str):
        cfg_actions = self.cfg.get("post_actions") or {}
        if not cfg_actions.get("enabled") or self.dry_run:
            return
        actions = cfg_actions.get(category) or []
        for action in actions:
            try:
                threading.Thread(target=self._run_action, args=(dict(action),),
                                 daemon=True).start()
            except Exception as exc:  # noqa: BLE001
                log.warning("联动动作线程创建失败：%s", exc)

    def _run_action(self, action: dict):
        delay = float(action.get("delay_sec") or 0)
        if delay > 0:
            time.sleep(delay)
        typ = (action.get("type") or "").strip()
        try:
            if typ == "miot_set_prop":
                code = asyncio.run(_miot_set_prop_async(
                    self.cfg, action["did"], int(action["siid"]), int(action["piid"]),
                    action.get("value")))
                ok = code == 0
                log.info("联动动作 miot_set_prop did=%s siid=%s piid=%s value=%s -> code=%s",
                         action.get("did"), action.get("siid"), action.get("piid"),
                         action.get("value"), code)
            elif typ == "miot_action":
                code = asyncio.run(_miot_action_async(
                    self.cfg, action["did"], int(action["siid"]), int(action["aiid"]),
                    action.get("args") or []))
                ok = code == 0
                log.info("联动动作 miot_action did=%s siid=%s aiid=%s args=%s -> code=%s",
                         action.get("did"), action.get("siid"), action.get("aiid"),
                         action.get("args"), code)
            elif typ == "http":
                req = urllib.request.Request(action["url"], method=action.get("method", "GET"))
                with urllib.request.urlopen(req, timeout=15) as resp:
                    ok = 200 <= resp.status < 300
                log.info("联动动作 http %s -> %s", action["url"], ok)
            else:
                log.warning("未知联动动作类型：%r", typ)
                return
            if not ok:
                log.warning("联动动作失败：%s", action)
                return
            followup = action.get("followup_text")
            if followup:
                delay2 = float(action.get("followup_delay_sec") or 0)
                log.info("联动动作成功，%ss 后播报：%s", int(delay2), followup)
                threading.Thread(target=self._speak_followup,
                                 args=(str(followup), delay2), daemon=True).start()
        except Exception as exc:  # noqa: BLE001
            log.warning("联动动作异常（%s）：%s", typ, exc)


def run_server(cfg: dict, dry_run: bool, host: str, port: int):
    BridgeHandler.cfg = cfg
    BridgeHandler.dry_run = dry_run
    httpd = ThreadingHTTPServer((host, port), BridgeHandler)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    log.info("服务已启动：http://%s:%s （dry_run=%s）", host, port, dry_run)
    log.info("健康检查：http://%s:%s/health", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("收到 Ctrl-C，退出")
    finally:
        httpd.server_close()
        try:
            PID_PATH.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="小爱洗衣提醒桥：本地 HTTP -> 小米云 -> 小爱音箱播报",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--login", action="store_true", help="交互登录小米账号（首次必做）")
    parser.add_argument("--save-password", action="store_true", help="登录时把密码也存进配置文件")
    parser.add_argument("--list", action="store_true", help="用已保存 token 列出小爱设备")
    parser.add_argument("--test", choices=["washer", "dryer", "linger", "generic"],
                        help="真播报一次预设文案")
    parser.add_argument("--test-text", metavar="TEXT", help="真播报一段任意文字")
    parser.add_argument("--classify", metavar="TEXT", help="只测试关键词分类，不发请求")
    parser.add_argument("--dry-run", action="store_true", help="不连小米，只跑 HTTP 流程")
    parser.add_argument("--host", help="覆盖监听地址（默认取配置）")
    parser.add_argument("--port", type=int, help="覆盖监听端口（默认取配置）")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    cfg = load_config()

    if args.classify is not None:
        cat = classify(args.classify, cfg)
        print(json.dumps({"text": args.classify, "category": cat}, ensure_ascii=False))
        return 0

    if args.login:
        return asyncio.run(login_async(cfg, args.save_password))
    if args.list:
        return asyncio.run(list_async(cfg))
    if args.test or args.test_text:
        text = args.test_text if args.test_text else cfg["messages"].get(args.test)
        result = asyncio.run(speak_async(text, cfg, dry_run=False))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    host = args.host or cfg.get("listen_host") or "127.0.0.1"
    port = int(args.port or cfg.get("listen_port") or 8765)
    try:
        run_server(cfg, args.dry_run, host, port)
    except OSError as exc:
        print(f"端口 {host}:{port} 启动失败：{exc}", file=sys.stderr)
        print("可能已经有另一个 bridge.py 在运行，或换端口：python bridge.py --port 8766", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
