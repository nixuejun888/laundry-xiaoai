#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
晶御 / Home Connect 中国区官方 API 监听（hc_listen.py）

作用：用官方开发者 API 订阅洗衣机、烘干机的「程序完成」事件，直接调用本机
bridge.py 的 /washer、/dryer 接口让小爱播报。这样就不再依赖微信通知，
也不需要在手机上用 MacroDroid 抓通知。

只用 Python 标准库，Termux 里装 Python 就能跑。

前置条件（一次性）：
  1. 注册 Home Connect 开发者账号并创建应用，拿到 client_id / client_secret；
     中国区必须在账号设置里打开「Sync to China」，API host 用 https://api.home-connect.cn
  2. 把 client_id / client_secret 填进 ~/.config/laundry-xiaoai/homeconnect.json
  3. 第一次登录授权：python hc_listen.py --login

常用命令：
  python hc_listen.py --login                 # 设备码流程(Device Flow)授权
  python hc_listen.py --login --auth-code     # 授权码流程(需要 redirect_uri，粘贴回跳 URL)
  python hc_listen.py --list                  # 列出账号下已配对的电器
  python hc_listen.py --dump                  # 只监听并打印所有事件（调试用）
  python hc_listen.py --run                   # 正式监听：完成事件 → 调 bridge 播报

配置文件：~/.config/laundry-xiaoai/homeconnect.json
令牌缓存：~/.config/laundry-xiaoai/homeconnect_token.json
日志：    ~/.config/laundry-xiaoai/hc_listen.log
"""

import argparse
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

APP_NAME = "laundry-xiaoai"
# 默认 ~/.config/laundry-xiaoai；可用环境变量覆盖（自动化测试/多实例时方便）
CONFIG_DIR = Path(os.environ.get("LAUNDRY_XIAOAI_HOME")
                  or (Path.home() / ".config" / APP_NAME))
CONFIG_PATH = CONFIG_DIR / "homeconnect.json"
TOKEN_PATH = CONFIG_DIR / "homeconnect_token.json"
LOG_PATH = CONFIG_DIR / "hc_listen.log"
PID_PATH = CONFIG_DIR / "hc_listen.pid"

DEFAULT_CONFIG = {
    # 中国区固定用这个 host；全球区用 https://api.home-connect.com
    "api_host": "https://api.home-connect.cn",
    "client_id": "",
    "client_secret": "",
    # 需要的权限：识别设备 + 监控 + 洗衣机/烘干机监控
    "scope": "IdentifyAppliance Monitor Washer-Monitor Dryer-Monitor",
    # 授权码流程用；必须和开发者门户里登记的 Redirect URI 完全一致。
    # 可以填一个 https 页面（如 https://api.home-connect.com），登录后浏览器会跳到
    # 该地址并带上 ?code=...，把地址栏整条 URL 粘贴回脚本即可。
    "redirect_uri": "https://api.home-connect.com",
    # 本机 bridge.py 的地址（播报服务）
    "bridge_url": "http://127.0.0.1:8765",
    # 烘干机开了防皱(WrinkleGuard)时，ProgramFinished 会延后到防皱结束才发，
    # 所以烘干机默认忽略 ProgramFinished，只用 DryingProcessFinished。
    "dryer_ignore_program_finished": True,
    # 警告：官方定义 OperationState=Finished 表示「程序已完成 或 已被成功中止」，
    # 用它当"洗完"判据会在用户中途取消/暂停时误报。默认关闭，只认 ProgramFinished /
    # DryingProcessFinished。个别机型不吐 ProgramFinished 时才考虑打开并自行验证。
    "allow_operation_state_finished": False,
    # 如果设备类型识别不准，可手动指定：{"<haId>": "washer" / "dryer" / "ignore"}
    "appliance_targets": {},
    # 事件播报模式：
    #   "finished"  = 只在程序完成时播报（默认，最安静）
    #   "minimal"   = 完成 + 耗材不足（洗衣液/柔顺剂），适合只想听这两种
    #   "important" = 完成 + 开始/暂停/门开关/报警/耗材
    #   "all"       = 重要事件 + 剩余时间/进度/阶段等（带节流，会比较吵）
    "announce": {
        "mode": "finished",
        "global_min_interval_sec": 20,      # 任意两条播报之间至少间隔
        "per_key_min_interval_sec": 60,     # 同一个事件 key 的最小间隔
        "remaining_thresholds_min": [60, 30, 10, 5, 1],  # 剩余时间在哪些分钟数播报
        "progress_thresholds_pct": [50, 75],             # 进度在哪些百分比播报
        "speak_unknown": False,             # all 模式下是否把没翻译的事件也念出来
        "fill_level_min_interval_sec": 1800,  # 洗衣液/柔顺剂不足：同一条提醒最短重复间隔
    },
}

log = logging.getLogger("hc_listen")

# 事件播报用的状态（跨线程共享）
ANNOUNCE_LOCK = threading.Lock()
ANNOUNCE_LAST_KEY = {}      # (haId, key) -> 时间戳
ANNOUNCE_LAST_GLOBAL = [0.0]
ANNOUNCE_DONE = {}          # (haId, kind) -> 已播报过的阈值集合
ANNOUNCE_LAST_VAL = {}      # (haId, kind) -> 上一次的数值（用于判断是否跨过阈值）

# 常见程序名翻译（不认识的会直接念英文 key 的最后一段）
PROGRAM_NAMES = {
    "Cotton": "棉织物", "Cottons": "棉织物", "CottonEco": "棉织物节能",
    "EasyCare": "易护理", "Mix": "混合", "SuperClean": "超净",
    "Steaming": "蒸汽护理", "SteamDegerm": "蒸汽除菌",
    "Delicate": "精细", "Quick30": "快速30分", "Quick45": "快速45分",
    "SuperQuick15": "快速15分", "Rinse": "漂洗", "Spin": "脱水", "DrumClean": "筒清洁",
    "Wool": "羊毛", "Synthetic": "化纤", "Shirts": "衬衫", "Sportswear": "运动服",
    "Down": "羽绒", "Silk": "丝绸", "Bedding": "床品", "Hygiene": "除菌",
    "Sensitive": "敏感/精细", "PlushToy": "毛绒玩具", "SportFitness": "运动健身",
    "DarkWash": "深色衣物", "CottonHygiene": "棉织物除菌",
    "ActiveOxygenWash": "活氧洗", "LargeItems": "大件",
}

# 洗涤阶段（ProcessPhase）翻译
PROCESS_PHASES = {
    "Prewash": "预洗", "MainWash": "主洗", "Rinse": "漂洗", "Drain": "排水",
    "IntermediateSpin": "中间脱水", "FinalSpin": "最终脱水", "Idle": "待机",
    "Drying": "烘干", "Ironing": "熨烫", "Steaming": "蒸汽",
}


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging(verbose=False):
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
        root.addHandler(fh)
    except OSError:
        pass


def load_config():
    ensure_dirs()
    data = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("配置文件解析失败：%s", exc)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(data or {})
    if not CONFIG_PATH.exists():
        save_config(cfg)
    return cfg


def save_config(cfg):
    ensure_dirs()
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(CONFIG_PATH)


def http_request(method, url, *, data=None, headers=None, form=False, timeout=30):
    """返回 (status, headers_dict, body_bytes)。不自动抛异常。"""
    hdrs = dict(headers or {})
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif isinstance(data, dict):
            body = json.dumps(data).encode()
            hdrs.setdefault("Content-Type", "application/json")
        else:
            body = data
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.getcode(), dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()
    except urllib.error.URLError as exc:
        return 0, {}, str(exc).encode()


def _json_or_text(raw):
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except Exception:
        return text


# --------------------------------------------------------------------------- #
# OAuth / 令牌
# --------------------------------------------------------------------------- #
def load_token():
    if TOKEN_PATH.exists():
        try:
            return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_token(token):
    ensure_dirs()
    tmp = TOKEN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(token, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(TOKEN_PATH)


def token_valid(token):
    if not token or not token.get("access_token"):
        return False
    return time.time() < float(token.get("expires_at") or 0) - 60


def token_request(cfg, form_data):
    url = cfg["api_host"].rstrip("/") + "/security/oauth/token"
    status, headers, body = http_request("POST", url, data=form_data, form=True)
    payload = _json_or_text(body)
    return status, payload


def refresh_token(cfg, token):
    form = {
        "grant_type": "refresh_token",
        "refresh_token": token.get("refresh_token", ""),
        "client_id": cfg["client_id"],
    }
    if cfg.get("client_secret"):
        form["client_secret"] = cfg["client_secret"]
    status, payload = token_request(cfg, form)
    if status != 200 or not isinstance(payload, dict) or "access_token" not in payload:
        raise RuntimeError(f"刷新令牌失败 HTTP {status}: {payload}")
    new = dict(token)
    new.update({
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token") or token.get("refresh_token"),
        "expires_at": time.time() + int(payload.get("expires_in") or 86400),
        "scope": payload.get("scope") or token.get("scope"),
    })
    save_token(new)
    log.info("access_token 已刷新，有效期 %s 秒", payload.get("expires_in"))
    return new


# 多个监听线程共用一个令牌，避免同时刷新把 refresh_token 用废。
TOKEN_LOCK = threading.Lock()
TOKEN_STATE = {}


def get_access_token(cfg):
    with TOKEN_LOCK:
        token = TOKEN_STATE.get("token") or load_token()
        if token and token_valid(token):
            TOKEN_STATE["token"] = token
            return token["access_token"]
        if token and token.get("refresh_token"):
            log.info("access_token 过期，尝试用 refresh_token 刷新…")
            token = refresh_token(cfg, token)
            TOKEN_STATE["token"] = token
            return token["access_token"]
        raise RuntimeError("还没有授权令牌，请先运行：python hc_listen.py --login")


def force_refresh(cfg):
    with TOKEN_LOCK:
        token = load_token() or TOKEN_STATE.get("token")
        if not token or not token.get("refresh_token"):
            raise RuntimeError("没有可用的 refresh_token，请重新运行 --login")
        token = refresh_token(cfg, token)
        TOKEN_STATE["token"] = token
        return token["access_token"]


def ensure_token(cfg):
    """兼容旧调用：返回完整 token 字典。"""
    access = get_access_token(cfg)
    with TOKEN_LOCK:
        token = TOKEN_STATE.get("token") or load_token()
    if not token:
        token = {"access_token": access, "expires_at": time.time() + 3600}
    return token


def device_flow_login(cfg):
    url = cfg["api_host"].rstrip("/") + "/security/oauth/device_authorization"
    status, _, body = http_request("POST", url, form=True, data={
        "client_id": cfg["client_id"],
        "scope": cfg["scope"],
    })
    payload = _json_or_text(body)
    if status != 200 or not isinstance(payload, dict) or "device_code" not in payload:
        print(f"\n设备码授权失败 HTTP {status}: {payload}")
        print("排查：1) client_id/secret 是否填对；2) 开发者门户里创建的应用是不是 Device Flow 类型；")
        print("      3) 是否在建应用时勾选 Sync to China、并使用 api.home-connect.cn；")
        print("      4) 注册邮箱是否全小写（大写会导致 OAuth 400）；")
        print("      5) 测试账号手机号是否和晶御一致（+86、无空格）。")
        print("也可以改用授权码流程：python hc_listen.py --login --auth-code")
        return 1
    device_code = payload["device_code"]
    verification = payload.get("verification_uri_complete") or payload.get("verification_uri")
    user_code = payload.get("user_code")
    # verification.home-connect.cn 的根路径没有页面（会显示 Cannot GET /），
    # 必须带 ?user_code=XXXX-XXXX 才能打开授权页。
    if verification and user_code and "user_code=" not in verification:
        sep = "&" if "?" in verification else "?"
        verification = f"{verification}{sep}user_code={user_code}"
    interval = int(payload.get("interval") or 5)
    expires_in = int(payload.get("expires_in") or 300)
    print("\n================ 请在浏览器/手机 App 中完成授权 ================")
    print("1. 复制并打开下面这个【完整地址】（必须带 ?user_code=）：")
    print("   ", verification)
    if user_code:
        print("   验证码：", user_code)
    print("   ⚠️ 不要只打开 https://verify.home-connect.cn 根地址，会显示 Cannot GET /")
    print("2. 用你的晶御/Home Connect 账号登录并同意授权")
    print("3. 完成后回到这里等脚本自动继续（%s 秒内有效，期间不要关 Termux）" % expires_in)
    print("==============================================================\n")
    deadline = time.time() + expires_in
    grant_types = ["device_code", "urn:ietf:params:oauth:grant-type:device_code"]
    while time.time() < deadline:
        time.sleep(interval)
        form = {
            "grant_type": grant_types[0],
            "device_code": device_code,
            "client_id": cfg["client_id"],
        }
        status, resp = token_request(cfg, form)
        # 有些部署只认 RFC 标准的 grant_type URN，遇到不支持就自动换一种再试
        if (status == 400 and isinstance(resp, dict)
                and resp.get("error") in ("unsupported_grant_type", "invalid_request", "invalid_grant")
                and len(grant_types) > 1):
            grant_types.pop(0)
            form["grant_type"] = grant_types[0]
            status, resp = token_request(cfg, form)
        if status == 200 and isinstance(resp, dict) and resp.get("access_token"):
            token = {
                "access_token": resp["access_token"],
                "refresh_token": resp.get("refresh_token"),
                "expires_at": time.time() + int(resp.get("expires_in") or 86400),
                "scope": resp.get("scope"),
            }
            save_token(token)
            print("\n授权成功，令牌已保存：", TOKEN_PATH)
            return 0
        err = (resp or {}).get("error") if isinstance(resp, dict) else str(resp)
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err == "access_denied":
            print("\n用户拒绝了授权。")
            return 1
        if err == "expired_token":
            print("\n设备码已过期，请重新运行 --login。")
            return 1
        print(f"\n轮询令牌出错 HTTP {status}: {resp}")
        return 1
    print("\n等待授权超时，请重新运行 --login。")
    return 1


def auth_code_login(cfg):
    redirect_uri = (cfg.get("redirect_uri") or "").strip()
    if not redirect_uri:
        print("请先在配置里填写 redirect_uri（要和开发者门户里登记的一致）。")
        return 1
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": cfg["scope"],
        "state": "laundry-xiaoai",
    }
    url = cfg["api_host"].rstrip("/") + "/security/oauth/authorize?" + urllib.parse.urlencode(params)
    print("\n1. 打开下面地址，用晶御/Home Connect 账号登录并同意授权：\n")
    print(url)
    print("\n2. 登录成功后浏览器会跳转到 redirect_uri，地址栏里带 ?code=...")
    print("   把【浏览器的完整跳转后地址】粘贴到这里（直接回车取消）：")
    raw = input("> ").strip()
    if not raw:
        return 1
    query = urllib.parse.urlparse(raw).query or raw
    code = (urllib.parse.parse_qs(query).get("code") or [""])[0]
    if not code:
        print("没有从粘贴内容里找到 code，请确认粘贴的是跳转后的完整 URL。")
        return 1
    status, payload = token_request(cfg, {
        "client_id": cfg["client_id"],
        "client_secret": cfg.get("client_secret", ""),
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code": code,
    })
    if status != 200 or not isinstance(payload, dict) or "access_token" not in payload:
        print(f"\n换取令牌失败 HTTP {status}: {payload}")
        return 1
    save_token({
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": time.time() + int(payload.get("expires_in") or 86400),
        "scope": payload.get("scope"),
    })
    print("\n授权成功，令牌已保存：", TOKEN_PATH)
    return 0


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def api_get(cfg, token, path, timeout=30):
    url = cfg["api_host"].rstrip("/") + path
    # Home Connect 的 REST 接口要求这个 vendor media type，用 application/json 会返回 406
    status, headers, body = http_request("GET", url, headers={
        "Authorization": "Bearer " + token["access_token"],
        "Accept": "application/vnd.bsh.sdk.v1+json",
    }, timeout=timeout)
    return status, headers, _json_or_text(body)


def list_appliances(cfg):
    token = ensure_token(cfg)
    status, _, payload = api_get(cfg, token, "/api/homeappliances")
    if status == 401:
        token = {"access_token": force_refresh(cfg), "expires_at": time.time() + 3600}
        status, _, payload = api_get(cfg, token, "/api/homeappliances")
    if status != 200:
        raise RuntimeError(f"获取设备列表失败 HTTP {status}: {payload}")
    appliances = (payload or {}).get("data", {}).get("homeappliances", [])
    return token, appliances


def appliance_target(cfg, appliance):
    ha_id = appliance.get("haId", "")
    override = (cfg.get("appliance_targets") or {}).get(ha_id)
    if override:
        return override
    atype = (appliance.get("type") or "").lower()
    if "washer" in atype:
        return "washer"
    if "dryer" in atype:
        return "dryer"
    return None


# --------------------------------------------------------------------------- #
# 事件解析与触发
# --------------------------------------------------------------------------- #
def iter_sse_events(lines):
    """把 SSE 行流解析成 (event_name, data_dict/None) 迭代器。"""
    event_name = None
    data_lines = []
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        line = line.rstrip("\r\n")
        if line == "":
            if data_lines:
                raw = "\n".join(data_lines)
                try:
                    data = json.loads(raw)
                except Exception:
                    data = None
                yield event_name or "message", data
            event_name = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if ":" in line:
            field, value = line.split(":", 1)
            value = value[1:] if value.startswith(" ") else value
        else:
            field, value = line, ""
        if field == "event":
            event_name = value
        elif field == "data":
            data_lines.append(value)


def event_items(data):
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
    return []


def decide_trigger(cfg, appliance, items):
    """根据一条事件里的 items 判断要不要播报，返回 'washer'/'dryer'/None。"""
    target = appliance_target(cfg, appliance)
    if target in (None, "ignore"):
        return None
    for item in items:
        key = (item or {}).get("key") or ""
        value = (item or {}).get("value")
        is_present = isinstance(value, str) and value.endswith("EventPresentState.Present")
        if key == "BSH.Common.Event.ProgramFinished" and is_present:
            if target == "dryer" and cfg.get("dryer_ignore_program_finished", True):
                continue  # 防皱会延后 ProgramFinished，烘干机用 DryingProcessFinished
            return target
        if key == "LaundryCare.Dryer.Event.DryingProcessFinished" and is_present:
            return "dryer"
        # OperationState=Finished 官方定义包含「程序被成功中止(aborted)」，
        # 默认不触发，避免用户中途取消时误播报；只有显式打开开关才认。
        if key == "BSH.Common.Status.OperationState" and isinstance(value, str) \
                and value.endswith("OperationState.Finished"):
            if not cfg.get("allow_operation_state_finished", False):
                continue
            if target == "dryer" and cfg.get("dryer_ignore_program_finished", True):
                continue
            return target
    return None


def notify_bridge(cfg, target, appliance):
    """调用本机 bridge.py 的播报接口。"""
    url = (cfg.get("bridge_url") or "http://127.0.0.1:8765").rstrip("/") + "/" + target
    try:
        status, _, body = http_request("GET", url, timeout=10)
        payload = _json_or_text(body) if body else {}
        name = appliance.get("name", appliance.get("haId", "?"))
        log.info("bridge 播报[%s] %s -> HTTP %s %s", target, name, status, payload)
        return status == 200
    except Exception as exc:  # noqa: BLE001
        log.exception("调用 bridge 失败：%s", exc)
        return False


def say_bridge(cfg, text, appliance):
    """让 bridge 播报任意文本（走 /say，不做类别去抖，由本脚本节流）。"""
    base = (cfg.get("bridge_url") or "http://127.0.0.1:8765").rstrip("/")
    url = base + "/say?" + urllib.parse.urlencode({"text": text})
    try:
        status, _, body = http_request("GET", url, timeout=15)
        log.info("事件播报[%s] %s -> HTTP %s", appliance.get("name"), text, status)
        return status == 200
    except Exception as exc:  # noqa: BLE001
        log.exception("事件播报失败：%s", exc)
        return False


def _announce_cfg(cfg):
    a = dict(DEFAULT_CONFIG["announce"])
    a.update(cfg.get("announce") or {})
    return a


def _may_announce(ha_id, key, a, low_priority=False, min_interval_sec=None):
    now = time.time()
    with ANNOUNCE_LOCK:
        # 全局最小间隔只约束“低优先级”的密集事件（剩余时间/进度等），
        # 重要事件（开始/暂停/门开关/报警）不受它影响，但仍受同 key 间隔约束
        if low_priority and now - ANNOUNCE_LAST_GLOBAL[0] < float(a.get("global_min_interval_sec") or 0):
            return False
        interval = float(a.get("per_key_min_interval_sec") or 0)
        if min_interval_sec is not None:
            interval = max(interval, float(min_interval_sec))
        last = ANNOUNCE_LAST_KEY.get((ha_id, key))
        if last is not None and now - last < interval:
            return False
        ANNOUNCE_LAST_KEY[(ha_id, key)] = now
        ANNOUNCE_LAST_GLOBAL[0] = now
        return True


def _threshold_crossed(ha_id, kind, thresholds, value, decreasing=True):
    """判断本次数值是否刚跨过某个阈值（只记录上一次值，不标记已播）。"""
    key = (ha_id, kind)
    prev = ANNOUNCE_LAST_VAL.get(key)
    ANNOUNCE_LAST_VAL[key] = value
    if not thresholds or prev is None:
        return None
    done = ANNOUNCE_DONE.setdefault(key, set())
    for t in sorted(thresholds, reverse=True):
        if t in done:
            continue
        crossed = (value <= t and prev >= t) if decreasing else (value >= t and prev <= t)
        if crossed:
            return t
    return None


def _mark_threshold(ha_id, kind, t):
    ANNOUNCE_DONE.setdefault((ha_id, kind), set()).add(t)


def _program_name(value):
    """从程序 key 里取一个中文名（例如 ...Program.Mix.SuperClean.SuperClean -> 混合）。"""
    parts = str(value or "").split(".")
    if "Program" in parts:
        tail = parts[parts.index("Program") + 1:]
        for p in tail:
            if p in PROGRAM_NAMES:
                return PROGRAM_NAMES[p]
        if tail:
            return tail[0]
    for p in reversed(parts):
        if p in PROGRAM_NAMES:
            return PROGRAM_NAMES[p]
    return parts[-1] if parts else str(value)


def _appliance_kind(appliance):
    t = (appliance.get("type") or "").lower()
    if "washer" in t:
        return "洗衣机"
    if "dryer" in t:
        return "烘干机"
    return "设备"


def _fmt_value(value):
    try:
        f = float(value)
        return int(f) if abs(f - int(f)) < 0.01 else round(f, 1)
    except (TypeError, ValueError):
        return value


def _alarm_label(key):
    """把报警/耗材类事件 key 翻译成中文提示。"""
    k = key.lower()
    # i-DOS 两个投放仓的液位不足事件：IDos1FillLevelPoor / IDos2FillLevelPoor
    if "filllevel" in k:
        if "idos2" in k:
            return "柔顺剂不足，请补充"
        if "idos1" in k:
            return "洗衣液不足，请补充"
        return "洗涤剂液位不足，请补充"
    if "detergent" in k:
        return "洗衣液不足，请补充"
    if "softener" in k:
        return "柔顺剂不足，请补充"
    if "salt" in k:
        return "软水盐不足，请补充"
    if "dosing" in k or "dispens" in k:
        return "洗涤剂投放系统提示，请检查"
    return key.split(".")[-1]


def announce_texts(cfg, appliance, items):
    """把事件翻译成要播报的文本列表（按 announce.mode 决定）。"""
    a = _announce_cfg(cfg)
    mode = str(a.get("mode") or "finished").lower()
    if mode not in ("minimal", "important", "all"):
        return []
    allow_actions = mode in ("important", "all")
    ha_id = appliance.get("haId") or appliance.get("name") or "?"
    kind = _appliance_kind(appliance)
    texts = []
    for item in items:
        key = (item or {}).get("key") or ""
        value = (item or {}).get("value")
        # 完成事件由 decide_trigger 处理，这里跳过避免重复
        if key in ("BSH.Common.Event.ProgramFinished",
                   "LaundryCare.Dryer.Event.DryingProcessFinished"):
            continue
        if allow_actions and key == "BSH.Common.Root.ActiveProgram":
            if not value or not str(value).strip():
                continue
            if _may_announce(ha_id, "start", a):
                texts.append(f"{kind}开始运行：{_program_name(value)}")
        elif allow_actions and key == "BSH.Common.Status.OperationState":
            if not isinstance(value, str):
                continue
            if value.endswith("OperationState.Run"):
                if _may_announce(ha_id, "start", a):
                    texts.append(f"{kind}开始运行")
            elif value.endswith("OperationState.Pause"):
                if _may_announce(ha_id, "pause", a):
                    texts.append(f"{kind}已暂停")
            # Finished 不作为播报（完成由 ProgramFinished/DryingProcessFinished 负责，且含中止）
        elif allow_actions and key == "BSH.Common.Status.DoorState":
            if not isinstance(value, str):
                continue
            if value.endswith("DoorState.Open") and _may_announce(ha_id, "door", a):
                texts.append(f"{kind}门已打开")
            elif value.endswith("DoorState.Closed") and _may_announce(ha_id, "door", a):
                texts.append(f"{kind}门已关闭")
        elif mode == "all" and key == "BSH.Common.Option.RemainingProgramTime":
            try:
                minutes = int(round(float(value) / 60))
            except (TypeError, ValueError):
                continue
            t = _threshold_crossed(ha_id, "remaining", a.get("remaining_thresholds_min"), minutes, decreasing=True)
            if t is not None and _may_announce(ha_id, f"remaining-{t}", a, low_priority=True):
                _mark_threshold(ha_id, "remaining", t)
                texts.append(f"{kind}还剩约 {t} 分钟")
        elif mode == "all" and key == "BSH.Common.Option.ProgramProgress":
            try:
                pct = int(round(float(value)))
            except (TypeError, ValueError):
                continue
            t = _threshold_crossed(ha_id, "progress", a.get("progress_thresholds_pct"), pct, decreasing=False)
            if t is not None and _may_announce(ha_id, f"progress-{t}", a, low_priority=True):
                _mark_threshold(ha_id, "progress", t)
                texts.append(f"{kind}进度 {pct}%")
        elif mode == "all" and key == "LaundryCare.Common.Option.ProcessPhase":
            phase = str(value).split(".")[-1]
            cn = PROCESS_PHASES.get(phase)
            if cn and _may_announce(ha_id, "phase", a, low_priority=True):
                texts.append(f"{kind}进入{cn}阶段")
        elif any(w in key.lower() for w in (
                "alarm", "error", "warning", "fault", "filllevel",
                "detergent", "softener", "salt", "dosing", "dispens")):
            is_consumable = any(w in key.lower() for w in (
                "filllevel", "detergent", "softener", "salt", "dosing", "dispens"))
            # minimal 模式只播耗材不足，不播普通故障/报警
            if mode == "minimal" and not is_consumable:
                continue
            label = _alarm_label(key)
            is_fill = "filllevel" in key.lower()
            if is_fill:
                # 液位事件会在 Present/Off 之间抖动，只在 Present 时提醒
                if not str(value).endswith("Present"):
                    continue
                interval = a.get("fill_level_min_interval_sec") or 1800
            else:
                interval = None
            if _may_announce(ha_id, key, a, min_interval_sec=interval):
                if any(w in label for w in ("洗衣液", "柔顺剂", "软水盐", "投放系统")):
                    texts.append(f"{kind}{label}")
                else:
                    texts.append(f"{kind}报警：{label}（{_fmt_value(value)}）")
        elif mode == "all" and a.get("speak_unknown"):
            if _may_announce(ha_id, key, a):
                texts.append(f"{kind}事件：{key.split('.')[-1]}，值 {_fmt_value(value)}")
    return texts


def listen_appliance(cfg, appliance, dump=False):
    """为单个电器维持一条 SSE 事件通道，断了自动重连。"""
    ha_id = appliance.get("haId")
    name = appliance.get("name", ha_id)
    target = appliance_target(cfg, appliance) or "ignore"
    url = cfg["api_host"].rstrip("/") + f"/api/homeappliances/{ha_id}/events"
    # 重连间隔不要太小，避免掉线时把每天 1000 次请求额度刷爆
    backoff = 15
    while True:
        try:
            access_token = get_access_token(cfg)
            req = urllib.request.Request(url, headers={
                "Authorization": "Bearer " + access_token,
                "Accept": "text/event-stream",
            })
            with urllib.request.urlopen(req, timeout=300) as resp:
                log.info("事件通道已连接：%s（%s，haId=%s）", name, target, ha_id)
                backoff = 15
                for etype, data in iter_sse_events(resp):
                    if dump:
                        print(f"[{name}] {etype} {json.dumps(data, ensure_ascii=False, sort_keys=True)}")
                    if etype == "KEEP-ALIVE":
                        continue
                    if data is None:
                        continue
                    if etype == "DEPAIRED":
                        log.warning("设备被解绑：%s", name)
                        return
                    items = event_items(data)
                    picked = decide_trigger(cfg, appliance, items)
                    if picked:
                        if dump:
                            # --dump 只做调试观察，不触发播报
                            print(f"[{name}] ↑ 这个事件在 --run 模式下会触发 {picked} 播报")
                            continue
                        key = items[0].get("key") if items else "?"
                        log.info("检测到完成事件 key=%s，触发 %s 播报（%s）", key, picked, name)
                        notify_bridge(cfg, picked, appliance)
                        continue
                    # announce.mode = important / all 时，把其他事件也翻译成播报
                    texts = announce_texts(cfg, appliance, items)
                    if texts:
                        if dump:
                            print(f"[{name}] ↑ 这个事件在 --run 模式下会播报：{texts}")
                            continue
                        for t in texts:
                            log.info("事件播报：%s", t)
                            say_bridge(cfg, t, appliance)
            # 服务端正常关闭
            log.info("事件通道被关闭：%s，%ss 后重连", name, backoff)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                try:
                    log.info("访问令牌失效，刷新后重连：%s", name)
                    force_refresh(cfg)
                    time.sleep(2)
                    continue
                except Exception as refresh_exc:  # noqa: BLE001
                    log.error("刷新令牌失败：%s（可以重新运行 python hc_listen.py --login）", refresh_exc)
            elif exc.code == 429:
                retry = int(exc.headers.get("Retry-After") or 60)
                log.warning("触发限流，等待 %ss 后重连：%s", retry, name)
                time.sleep(retry)
                continue
            log.warning("事件通道 HTTP %s（%s）：%s", exc.code, name, exc.read()[:300])
        except Exception as exc:  # noqa: BLE001
            log.warning("事件通道断开（%s）：%s", name, exc)
        time.sleep(backoff)
        backoff = min(backoff * 2, 300)


def run_listener(cfg, dump=False):
    bridge_url = (cfg.get("bridge_url") or "http://127.0.0.1:8765").rstrip("/")
    try:
        b_status, _, _ = http_request("GET", bridge_url + "/health", timeout=5)
    except Exception:
        b_status = 0
    print("\n播报服务 bridge：", "✅ 正常" if b_status == 200
          else f"❌ 不可用（HTTP {b_status}）——完成事件能触发，但播报会失败，请先启动 bridge.py")
    if dump:
        print("（--dump 只观察事件，不会真的触发播报）")
    token, appliances = list_appliances(cfg)
    if not appliances:
        print("账号下没有已配对的电器。先在晶御/Home Connect App 里完成配对；")
        print("另外检查：开发者应用的「测试账号手机号」是否就是晶御账号（+86 无空格）、建应用时是否勾了 Sync to China。")
        return 1
    print("\n账号下的电器：")
    for a in appliances:
        print(f"  - {a.get('name')} | type={a.get('type')} | brand={a.get('brand')} "
              f"| vib={a.get('vib')} | connected={a.get('connected')} | target={appliance_target(cfg, a)}")
    threads = []
    for a in appliances:
        if appliance_target(cfg, a) in ("ignore", None):
            log.info("跳过不支持的电器：%s（type=%s），可在 appliance_targets 里手动指定",
                     a.get("name"), a.get("type"))
            continue
        t = threading.Thread(target=listen_appliance, args=(cfg, a, dump), daemon=True)
        t.start()
        threads.append(t)
    if not threads:
        print("没有可用于播报的洗衣机/烘干机。")
        return 1
    if not dump:
        try:
            PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass
    print(f"\n已开启 {len(threads)} 条事件通道，Ctrl-C 退出。")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n退出。")
    finally:
        if not dump:
            try:
                PID_PATH.unlink()
            except OSError:
                pass
    return 0


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="晶御/Home Connect 官方 API 监听：完成事件 -> 触发小爱播报",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--login", action="store_true", help="授权登录（默认设备码流程）")
    group.add_argument("--list", action="store_true", help="列出账号下已配对的电器")
    group.add_argument("--run", action="store_true", help="正式监听并触发播报")
    group.add_argument("--dump", action="store_true", help="只打印所有事件（调试）")
    parser.add_argument("--auth-code", action="store_true", help="--login 时改用授权码流程")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    cfg = load_config()
    if not cfg.get("client_id"):
        print("还没有配置 client_id。请先：")
        print(f"  1. 编辑 {CONFIG_PATH}，填入开发者门户拿到的 client_id / client_secret")
        print("  2. 中国区账号记得在开发者门户里勾选 Sync to China")
        print("  3. 再运行 python hc_listen.py --login")
        return 2

    try:
        if args.login:
            return auth_code_login(cfg) if args.auth_code else device_flow_login(cfg)
        if args.list:
            _, appliances = list_appliances(cfg)
            for a in appliances:
                print(f"{a.get('name')} | type={a.get('type')} | haId={a.get('haId')} "
                      f"| connected={a.get('connected')} | target={appliance_target(cfg, a)}")
            return 0
        if args.run:
            return run_listener(cfg, dump=False)
        if args.dump:
            return run_listener(cfg, dump=True)
        parser.print_help()
        return 0
    except RuntimeError as exc:
        print(f"\n{exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        log.exception("出错：%s", exc)
        print(f"\n出错：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
