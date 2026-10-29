#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检测局域网 DLNA 播放能力（为“绕开小米云 TTS”做准备）。

用法（Termux，手机连家里 WiFi）：
    python ~/laundry-xiaoai/tools/dlna_check.py

操作前请先在小爱音箱 App 里打开：
    小爱音箱 App → 设置 → 音乐体验 → 打开「DLNA 音乐」
然后跑本脚本；如果能发现音箱，就说明可以走本地播放。
"""
import re
import socket
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

SSDP_ADDR = ("239.255.255.250", 1900)


def msearch(st, timeout=4):
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        f"ST: {st}\r\n\r\n"
    ).encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    s.settimeout(1)
    try:
        s.sendto(msg, SSDP_ADDR)
    except Exception as exc:  # noqa: BLE001
        print("  ⚠️ 发送 SSDP 失败：", exc)
        return []
    found = {}
    start = time.time()
    while time.time() - start < timeout:
        try:
            data, addr = s.recvfrom(65507)
        except socket.timeout:
            continue
        text = data.decode("utf-8", "replace")
        loc = None
        st_val = ""
        for line in text.splitlines():
            if line.upper().startswith("LOCATION:"):
                loc = line.split(":", 1)[1].strip()
            if line.upper().startswith("ST:"):
                st_val = line.split(":", 1)[1].strip()
        if loc and loc not in found:
            found[loc] = (addr[0], st_val)
    s.close()
    return [(loc, *rest) for loc, rest in found.items()]


def fetch_desc(url, timeout=5):
    req = urllib.request.Request(url, headers={"User-Agent": "dlna-check"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(200000)


def parse_desc(xml_bytes):
    info = {}
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return info
    ns = {"d": "urn:schemas-upnp-org:device-1-0"}
    dev = root.find("d:device", ns)
    if dev is None:
        return info
    for tag in ("friendlyName", "modelName", "manufacturer", "modelNumber"):
        el = dev.find(f"d:{tag}", ns)
        if el is not None and el.text:
            info[tag] = el.text.strip()
    svcs = dev.find("d:serviceList", ns)
    if svcs is not None:
        info["services"] = []
        for svc in svcs.findall("d:service", ns):
            item = {}
            for tag in ("serviceType", "controlURL"):
                el = svc.find(f"d:{tag}", ns)
                if el is not None and el.text:
                    item[tag] = el.text.strip()
            if item:
                info["services"].append(item)
    return info


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("局域网 DLNA 播放能力检测")
    print("=" * 60)
    print("检测中（约 10 秒）…\n")

    all_found = {}
    for st in (
        "urn:schemas-upnp-org:device:MediaRenderer:1",
        "urn:schemas-upnp-org:device:MediaServer:1",
        "ssdp:all",
    ):
        for loc in msearch(st):
            all_found.setdefault(loc[0], loc[1:])
        time.sleep(0.5)

    if not all_found:
        print("❌ 没有发现任何 DLNA/UPnP 设备。")
        print()
        print("可能原因：")
        print("  1. 小爱音箱 App 里还没打开「DLNA 音乐」开关：")
        print("     小爱音箱 App → 设置 → 音乐体验 → DLNA 音乐（打开）")
        print("  2. 手机和音箱不在同一个 2.4G WiFi 网段（DLNA 通常要求同网段）；")
        print("  3. 路由器开启了 AP 隔离/客户端隔离，需要关闭；")
        print("  4. 这台手机/网络屏蔽了 UDP 组播（部分安卓系统会）。")
        print()
        print("打开开关后重跑本脚本即可。")
        return 1

    renderers = []
    for loc, (ip, st) in all_found.items():
        print(f"发现设备：{ip}")
        print(f"  ST: {st}")
        print(f"  描述: {loc}")
        try:
            desc = parse_desc(fetch_desc(loc))
        except Exception as exc:  # noqa: BLE001
            print("  ⚠️ 读取描述失败：", exc)
            print()
            continue
        name = desc.get("friendlyName") or "(未知)"
        model = desc.get("modelName") or ""
        maker = desc.get("manufacturer") or ""
        print(f"  名称: {name} | 型号: {model} | 厂商: {maker}")
        is_renderer = any("MediaRenderer" in (s.get("serviceType") or "")
                          for s in desc.get("services") or [])
        if is_renderer:
            renderers.append((name, ip, loc, desc))
            print("  ✅ 支持 MediaRenderer（可接收播放）")
        else:
            print("  ℹ️ 不是播放器（可能是媒体服务器/其他设备）")
        print()

    print("=" * 60)
    if renderers:
        print(f"✅ 发现 {len(renderers)} 个可播放设备：")
        for name, ip, loc, desc in renderers:
            print(f"  - {name}（{ip}）")
        print()
        print("结论：可以走 **本地 DLNA 播放**，完全绕开小米账号/TTS 云端。")
        print("下一步：把这份输出发给维护者，我给你出一键本地播报方案。")
        return 0
    print("⚠️ 发现了 UPnP 设备，但没有 MediaRenderer。")
    print("请确认小爱音箱 App 的「DLNA 音乐」已打开，或把上面输出发我。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
