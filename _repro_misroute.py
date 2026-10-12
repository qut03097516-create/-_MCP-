# -*- coding: utf-8 -*-
"""复现：用「上传文件名」当 pv_file 调用，系统实际读的是谁的数据。"""
import io
import json
import sys
import uuid

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:8000"
UPLOADED = ("Timeseries_30.542_101.948_E5_1kWp_crystSi_14_v47deg_"
            "2005_2023_polluted_BeijingTime.csv")

s = requests.Session()
r = s.post(f"{BASE}/api/auth/login",
           json={"username": "mcp_test", "password": "McpTest@2026"}, timeout=60)
tok = r.json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}
MH = {"Content-Type": "application/json",
      "Accept": "application/json, text/event-stream",
      "Authorization": f"Bearer {tok}"}


def call(tool, args):
    payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()),
               "method": "tools/call", "params": {"name": tool, "arguments": args}}
    resp = requests.post(f"{BASE}/mcp", json=payload, headers=MH, timeout=300)
    body = resp.text
    if "\ndata:" in body or body.lstrip().startswith("data:"):
        body = "\n".join(l[5:].strip() for l in body.splitlines() if l.startswith("data:"))
    d = json.loads(body)
    res = d.get("result") or {}
    txt = "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
    try:
        return json.loads(txt)
    except Exception:
        return {"_raw": txt[:600], "_isError": res.get("isError")}


def show(title, obj):
    print("\n" + "=" * 66)
    print(title)
    print("=" * 66)
    print(json.dumps(obj, ensure_ascii=False, indent=1)[:1400])


# ── A. 服务端内置数据集清单 ────────────────────────────────────────────────
import urllib.request
req = urllib.request.Request(f"{BASE}/api/data/sites", headers=H)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        sites = json.loads(resp.read().decode("utf-8"))
    names = sites if isinstance(sites, list) else (sites.get("data") or sites.get("sites") or [])
    print("=" * 66)
    print("A. 内置数据集（pv_data.duckdb）共 %d 个" % len(names))
    print("=" * 66)
    for n in names[:12]:
        print("   ", n if isinstance(n, str) else json.dumps(n, ensure_ascii=False)[:150])
except Exception as e:
    print("A. 查询内置列表失败:", e)

# ── B. 用「上传文件名」调 get_site ─────────────────────────────────────────
show("B. get_site(pv_file = 上传文件名)",
     call("get_site", {"pv_file": UPLOADED}))

show("C. get_site(name = 上传文件名)",
     call("get_site", {"name": UPLOADED}))

# ── D. check_data_quality 用上传文件名 ─────────────────────────────────────
show("D. check_data_quality(pv_file = 上传文件名) —— 到底读了谁？",
     call("check_data_quality", {"pv_file": UPLOADED}))

# ── E. forecast_power ─────────────────────────────────────────────────────
show("E. forecast_power(pv_file = 上传文件名, historical)",
     call("forecast_power", {"pv_file": UPLOADED, "mode": "historical",
                             "start_date": "2023-12-30", "end_date": "2023-12-31"}))

# ── F. 对照：直接用内置四川全名 ───────────────────────────────────────────
SICHUAN = "四川 - Timeseries_30.542_101.948_E5_1kWp_crystSi_14_v47deg_2005_2023.csv"
show("F. 对照 check_data_quality(pv_file = 内置四川全名)",
     call("check_data_quality", {"pv_file": SICHUAN}))
