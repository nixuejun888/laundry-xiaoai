#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""米家云接口（api.mijia.tech）最小客户端。

协议来自 xgg / Do1e/mijia-api 5.0.0（GPL-3.0），这里用标准库重写，
用于：小爱音箱 play-text 播报、MIoT 属性读写。

认证文件格式与 xgg 的 auth.json 相同（userId/passToken/deviceId/cUserId/
serviceToken/ssecurity/ua/pass_o 等）。serviceToken 过期时用 passToken 自动刷新。
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CLOUD_BASE = "https://api.mijia.tech/app"
ACCOUNT_BASE = "https://account.xiaomi.com"
UA_DEFAULT = (
    "Android-7.1.1-1.0.0-ONEPLUS A3010-136-2E2C2C8B9A5C1A2B3C4D-"
    "APP/com.xiaomi.mihome/f3f2c1"
)


# ----------------------------- RC4 / 签名 ----------------------------- #
def _rc4(key: bytes, data: bytes) -> bytes:
    if not key:
        raise ValueError("empty rc4 key")
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) & 255
        state[i], state[j] = state[j], state[i]
    out = bytearray(len(data))
    i = j = 0
    for offset in range(-1024, len(data)):
        i = (i + 1) & 255
        j = (j + state[i]) & 255
        state[i], state[j] = state[j], state[i]
        if offset >= 0:
            out[offset] = data[offset] ^ state[(state[i] + state[j]) & 255]
    return bytes(out)


def _b64d(s: str) -> bytes:
    return base64.b64decode(s)


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _nonce() -> str:
    raw = os.urandom(8) + int(time.time() / 60).to_bytes(4, "big")
    return _b64e(raw)


def _signed_nonce(ssecurity: str, nonce: str) -> str:
    return _b64e(hashlib.sha256(_b64d(ssecurity) + _b64d(nonce)).digest())


def _signature(path: str, signed_nonce: str, params: dict) -> str:
    text = "&".join(["POST", path] + [f"{k}={v}" for k, v in params.items()] + [signed_nonce])
    return _b64e(hashlib.sha1(text.encode()).digest())


def encode_request(path: str, body: dict, ssecurity: str, nonce: str) -> str:
    signed = _signed_nonce(ssecurity, nonce)
    key = _b64d(signed)
    params = {"data": json.dumps(body, separators=(",", ":"), ensure_ascii=False)}
    params["rc4_hash__"] = _signature(path, signed, params)
    enc = {k: _b64e(_rc4(key, v.encode())) for k, v in params.items()}
    enc["signature"] = _signature(path, signed, enc)
    enc["ssecurity"] = ssecurity
    enc["_nonce"] = nonce
    return urllib.parse.urlencode(enc)


def decode_response(text: str, ssecurity: str, nonce: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        pass
    signed = _signed_nonce(ssecurity, nonce)
    raw = _rc4(_b64d(signed), _b64d(text.strip()))
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


# ----------------------------- 认证文件 ----------------------------- #
class CloudAuth:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict = {}
        self.load()

    def load(self) -> dict:
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}
        return self.data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @property
    def ready(self) -> bool:
        d = self.data
        return bool(d.get("serviceToken") and d.get("ssecurity") and d.get("cUserId") and d.get("passToken"))

    def _cookie(self) -> str:
        d = self.data
        return (
            f"cUserId={d.get('cUserId', '')};"
            f"yetAnotherServiceToken={d.get('serviceToken', '')};"
            f"serviceToken={d.get('serviceToken', '')};"
            "timezone_id=Asia/Shanghai;channel=MI_APP_STORE;countryCode=CN;"
            f"PassportDeviceId={d.get('deviceId', '')};locale=zh_CN"
        )

    # ------------------------- 请求 ------------------------- #
    def request(self, path: str, body: dict, _retry: bool = True) -> dict:
        if not self.ready:
            raise RuntimeError("云授权文件不可用（需要 userId/passToken/serviceToken/ssecurity/cUserId）")
        nonce = _nonce()
        payload = encode_request(path, body, self.data["ssecurity"], nonce)
        req = urllib.request.Request(
            CLOUD_BASE + path,
            data=payload.encode(),
            method="POST",
            headers={
                "User-Agent": self.data.get("ua") or UA_DEFAULT,
                "accept-encoding": "identity",
                "Content-Type": "application/x-www-form-urlencoded",
                "miot-accept-encoding": "GZIP",
                "miot-encrypt-algorithm": "ENCRYPT-RC4",
                "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
                "Cookie": self._cookie(),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                text = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403) and _retry:
                self.refresh()
                return self.request(path, body, _retry=False)
            raise
        data = decode_response(text, self.data["ssecurity"], nonce)
        code = int(data.get("code") or 0)
        if code in (3, 401, 403) and _retry:
            self.refresh()
            return self.request(path, body, _retry=False)
        if code != 0:
            raise RuntimeError(f"cloud error code={code}: {data}")
        return data.get("result", data)

    # ------------------------- 刷新 ------------------------- #
    @staticmethod
    def _account_cookie(d: dict) -> str:
        pairs = [
            ("deviceId", d.get("deviceId")),
            ("pass_o", d.get("pass_o")),
            ("passToken", d.get("passToken")),
            ("userId", d.get("userId")),
            ("cUserId", d.get("cUserId")),
            ("uLocale", "zh_CN"),
        ]
        return ";".join(f"{k}={v}" for k, v in pairs if v)

    def refresh(self) -> None:
        """用 passToken 刷新 serviceToken/ssecurity/cUserId。"""
        d = self.data
        if not d.get("passToken"):
            raise RuntimeError("passToken 缺失，需要重新扫码授权")
        url = ACCOUNT_BASE + "/pass/serviceLogin?_json=true&sid=mijia&_locale=zh_CN"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": d.get("ua") or UA_DEFAULT, "Cookie": self._account_cookie(d)},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read().decode("utf-8", "replace")
        data = json.loads(text.replace("&&&START&&&", ""))
        if data.get("code") != 0 or not data.get("location") or not data.get("ssecurity"):
            raise RuntimeError(f"刷新登录失败: {data}")
        d["ssecurity"] = data["ssecurity"]
        cookies: dict = {}
        location = data["location"]
        for _ in range(6):
            req = urllib.request.Request(
                location,
                headers={
                    "User-Agent": d.get("ua") or UA_DEFAULT,
                    "Cookie": ";".join(f"{k}={v}" for k, v in cookies.items()),
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    set_cookies = r.headers.get_all("Set-Cookie") or []
                    code = r.status
                    nxt = r.headers.get("Location")
            except urllib.error.HTTPError as exc:
                set_cookies = exc.headers.get_all("Set-Cookie") or []
                code = exc.code
                nxt = exc.headers.get("Location")
            for header in set_cookies:
                first = header.split(";", 1)[0]
                if "=" in first:
                    k, v = first.split("=", 1)
                    if k.strip() in ("serviceToken", "cUserId", "userId", "passToken"):
                        cookies[k.strip()] = v.strip()
            if code in (301, 302, 303, 307, 308) and nxt:
                location = urllib.parse.urljoin(location, nxt)
                continue
            break
        if not cookies.get("serviceToken"):
            raise RuntimeError("刷新未拿到 serviceToken，需要重新扫码授权")
        d.update({k: v for k, v in cookies.items() if v})
        self.save()

    # ------------------------- 业务 ------------------------- #
    def speak(self, did: str, text: str) -> dict:
        return self.request(
            "/miotspec/action",
            {"params": {"did": str(did), "siid": 5, "aiid": 3, "in": [text]}},
        )

    def set_prop(self, did: str, siid: int, piid: int, value) -> dict:
        return self.request(
            "/miotspec/prop/set",
            {"params": [{"did": str(did), "siid": int(siid), "piid": int(piid), "value": value}]},
        )

    def get_prop(self, did: str, siid: int, piid: int) -> dict:
        return self.request(
            "/miotspec/prop/get",
            {"params": [{"did": str(did), "siid": int(siid), "piid": int(piid)}]},
        )
