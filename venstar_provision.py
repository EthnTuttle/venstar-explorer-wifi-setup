#!/usr/bin/env python3
"""Provision WiFi on a Venstar Explorer / Explorer Mini in "Wireless Setup" (soft-AP) mode.

Protocol recovered from the Venstar Skyport Android app 7.4.1 (air.com.venstar.skyport).
Join this machine to the thermostat's THERMOSTAT-XXXX network (WPA2 password 123456789)
first, then:

  venstar_provision.py info                 read MAC / firmware / model (read-only)
  venstar_provision.py scan                 list WiFi networks the thermostat sees (read-only)
  venstar_provision.py config "<SSID>" [-]  send WiFi settings; "-" or omitted = prompt for
                                            the password without echo [security: 0=None
                                            1=WEP 2=WPA 3=WPA2, default 3]
  venstar_provision.py name "<name>"        set device name (protobuf NAME)
  venstar_provision.py complete             POST /completed -> leave setup mode and join WiFi
  venstar_provision.py selftest             encode a sample WIFICONFIG offline
"""
import struct, sys, urllib.request

BASE = "http://192.168.1.1:8190"
CMD = dict(LOGIN=2, NAME=16, WIFICONFIG=120, WIFISCANRESULTS=121, SUCCESS=126, FAILURE=127)

def varint(n):
    out = b""
    while True:
        b = n & 0x7F; n >>= 7
        if n: out += bytes([b | 0x80])
        else: return out + bytes([b])
def key(field, wt): return varint((field << 3) | wt)
def f_varint(field, v): return key(field, 0) + varint(v)
def f_bytes(field, b):
    if isinstance(b, str): b = b.encode()
    return key(field, 2) + varint(len(b)) + b

def message(command, sub_field=None, sub=b""):
    body = f_bytes(sub_field, sub) if sub_field is not None else b""
    body += f_varint(1000, command) + f_bytes(1001, "Venstar")   # same order as app's protobufjs
    return struct.pack(">I", len(body)) + body          # 4-byte BE length prefix

def wificonfig(ssid, password, sec=3, dhcp=True, static=None):
    b = f_bytes(1, ssid) + f_varint(2, sec) + f_varint(3, 1 if dhcp else 0)
    if sec != 0: b += f_bytes(4, password)
    if not dhcp:  # static: ip, mask, gw, dns as uint32 (see app ipToInt)
        ip, mask, gw, dns = static
        for fld, v in zip((5, 6, 7, 8), (ip, mask, gw, dns)):
            b += f_varint(fld, v)
    return message(CMD["WIFICONFIG"], 120, b)

def decode_raw(buf):
    """Minimal protobuf walker -> {field: [values]} (nested left as bytes)."""
    i, out = 0, {}
    while i < len(buf):
        k, i = _rv(buf, i); f, wt = k >> 3, k & 7
        if wt == 0: v, i = _rv(buf, i)
        elif wt == 2:
            l, i = _rv(buf, i); v = buf[i:i+l]; i += l
        elif wt == 5: v = buf[i:i+4]; i += 4
        elif wt == 1: v = buf[i:i+8]; i += 8
        else: raise ValueError(wt)
        out.setdefault(f, []).append(v)
    return out
def _rv(b, i):
    s = n = 0
    while True:
        c = b[i]; i += 1; n |= (c & 0x7F) << s; s += 7
        if not c & 0x80: return n, i

def post(path, data=b""):
    r = urllib.request.Request(BASE + path, data=data, method="POST")
    return urllib.request.urlopen(r, timeout=10).read()
def get(path): return urllib.request.urlopen(BASE + path, timeout=10).read()

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit()
    if a[0] == "selftest":
        m = wificonfig("MyWiFi", "secret123")
        d = decode_raw(m[4:]); print(m.hex()); print(d); print(decode_raw(d[120][0])); sys.exit()
    if a[0] == "info":
        d = decode_raw(get("/info")[4:]); print({k: v for k, v in decode_raw(d[2][0]).items()})  # LOGIN: 1 mac,2 fwVer,3 model,4 name
    elif a[0] == "scan":
        d = decode_raw(post("/command", message(CMD["WIFISCANRESULTS"]))[4:])
        for it in decode_raw(d[121][0]).get(1, []):
            x = decode_raw(it); print(x[1][0].decode(errors="replace"), "sec=%d" % x[2][0], "rssi=%d" % (x[3][0] - 256))
    elif a[0] == "config":
        # Password "-" (or omitted) = prompt without echo, so it never hits argv/history.
        pw = a[2] if len(a) > 2 and a[2] != "-" else __import__("getpass").getpass("WiFi password for %s: " % a[1])
        sec = int(a[3]) if len(a) > 3 else 3
        print(decode_raw(post("/command", wificonfig(a[1], pw, sec))[4:]))
    elif a[0] == "name":
        print(decode_raw(post("/command", message(CMD["NAME"], 16, f_bytes(1, a[1])))[4:]))
    elif a[0] == "complete":
        print(post("/completed"))
