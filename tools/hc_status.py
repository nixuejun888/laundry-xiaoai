#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查看晶御/Home Connect 官方 API 里到底有哪些状态字段
（用来确认有没有“洗衣液不足/柔顺剂不足”这类信息）。

用法（Termux）：
  python ~/laundry-xiaoai/tools/hc_status.py
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CFG = Path.home() / ".config" / "laundry-xiaoai" / "homeconnect.json"
TOK = Path.home() / ".config" / "laundry-xiaoai" / "homeconnect_token.json"
ACCEPT = "application/vnd.bsh.sdk.v1+json"
KEYWORDS = (
    "detergent", "softener", "salt", "dosing", "dispens", "consumable",
    "level", "supply", "tank", "remaining", "duration", "water", "rinse",
)


def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def http(method, url, *, data=None, headers=None, form=False, timeout=30):
    hdrs = dict(headers or {})
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            body = json.dumps(data).encode()
            hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.getcode(), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc).encode()


def parse(raw):
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return raw.decode("utf-8", "replace")


def refresh_token(cfg, tok):
    host = cfg.get("api_host", "https://api.home-connect.cn").rstrip("/")
    form = {"grant_type": "refresh_token", "refresh_token": tok.get("refresh_token"),
            "client_id": cfg.get("client_id")}
    if cfg.get("client_secret"):
        form["client_secret"] = cfg["client_secret"]
    st, raw = http("POST", host + "/security/oauth/token", data=form, form=True)
    payload = parse(raw)
    if st == 200 and isinstance(payload, dict) and payload.get("access_token"):
        tok.update({
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token") or tok.get("refresh_token"),
            "expires_at": time.time() + int(payload.get("expires_in") or 86400),
        })
        TOK.write_text(json.dumps(tok, ensure_ascii=False, indent=2), encoding="utf-8")
        print("（已自动刷新访问令牌）")
        return tok
    print("❌ 刷新令牌失败：", payload)
    return None


def api(cfg, tok, path):
    host = cfg.get("api_host", "https://api.home-connect.cn").rstrip("/")
    return http("GET", host + path, headers={
        "Authorization": "Bearer " + tok["access_token"], "Accept": ACCEPT})


def dump_endpoint(label, payload):
    """打印一个接口返回的 key=value 列表，返回可能和耗材/余量有关的条目。"""
    hits = []
    if not isinstance(payload, dict):
        print(f"\n{label}: {payload}")
        return hits
    data = payload.get("data", payload)
    entries = None
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                entries = v
                break
    if entries is None:
        print(f"\n{label}: {json.dumps(data, ensure_ascii=False)[:800]}")
        return hits
    print(f"\n{label}（{len(entries)} 条）：")
    for e in entries:
        if not isinstance(e, dict):
            print("  ", e)
            continue
        key = str(e.get("key", ""))
        val = e.get("value")
        shown = json.dumps(val, ensure_ascii=False) if isinstance(val, (dict, list)) else val
        line = f"  {key} = {shown}"
        print(line)
        if any(w in key.lower() for w in KEYWORDS):
            hits.append((key, shown, label))
    return hits


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 70)
    print("晶御 API 状态字段清单")
    print("=" * 70)
    cfg = load_json(CFG, {})
    tok = load_json(TOK, None)
    if not cfg.get("client_id") or not tok:
        print("❌ 还没配置 client_id 或还没授权，先跑一键接入。")
        return
    if tok.get("expires_at", 0) < time.time() + 60:
        tok = refresh_token(cfg, tok)
        if not tok:
            return

    st, raw = api(cfg, tok, "/api/homeappliances")
    payload = parse(raw)
    if st != 200:
        print(f"❌ 获取设备列表失败 HTTP {st}: {payload}")
        return
    apps = (payload.get("data") or {}).get("homeappliances") or []

    all_hits = []
    for a in apps:
        ha = a.get("haId")
        print("\n" + "=" * 70)
        print(f"设备：{a.get('name')} | type={a.get('type')} | vib={a.get('vib')} | haId={ha}")
        for path, label in (
            ("/status", "① /status 状态"),
            ("/settings", "② /settings 设置"),
            ("/programs/active", "③ /programs/active 当前程序"),
            ("/programs/selected", "④ /programs/selected 已选程序"),
        ):
            st, raw = api(cfg, tok, f"/api/homeappliances/{ha}{path}")
            if st != 200:
                print(f"\n{label}: HTTP {st} {parse(raw)}")
                continue
            all_hits.extend(dump_endpoint(label, parse(raw)))

    print("\n" + "=" * 70)
    print("可能和耗材/余量有关的字段：")
    if not all_hits:
        print("  （没有找到 — 说明官方 API 大概率没有暴露洗衣液/柔顺剂余量这类信息；")
        print("    只能靠晶御 App 自己的提醒或微信通知来兜底）")
    else:
        for key, val, label in all_hits:
            print(f"  [{label}] {key} = {val}")
    print("=" * 70)
    print("把上面完整输出发我，我按实际字段补上播报翻译。")


if __name__ == "__main__":
    main()
