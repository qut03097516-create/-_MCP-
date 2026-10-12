# -*- coding: utf-8 -*-
"""用 MCP 处理用户提交的污染数据：登录 → 建站 → 上传 → 8 工具链。"""
import io
import json
import os
import sys
import time
import uuid

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:8000"
CSV = (r"C:\Users\35329\xwechat_files\wxid_pjg1hsjzpsxo12_0966\msg\file\2026-10"
       r"\Timeseries_30.542_101.948_E5_1kWp_crystSi_14_v47deg_2005_2023_polluted_BeijingTime.csv")

s = requests.Session()

def step(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

# ── 1. 登录 ────────────────────────────────────────────────────────────────
step("1. 登录")
r = s.post(f"{BASE}/api/auth/login", json={"username": "mcp_test", "password": "McpTest@2026"}, timeout=60)
r.raise_for_status()
tok = r.json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}
print(f"[OK] token 长度={len(tok)}")

# ── 2. 建站（PVGIS 头：30.542/101.948，Slope 47deg，1 kWp）────────────────
step("2. 创建电站")
body = {"name": "川西污染测试站", "lat": 30.542, "lon": 101.948,
        "tilt": 47, "azimuth": 0, "kwp": 1.0, "loss_pct": 14.0}
r = s.post(f"{BASE}/api/sites", headers=H, json=body, timeout=60)
print("HTTP", r.status_code, r.text[:400])
r.raise_for_status()
jr = r.json()
site = jr.get("site") or {}
site_id = site.get("site_id") or site.get("id")
if not site_id:
    print("FATAL: 建站未返回 site_id"); sys.exit(1)
print(f"[OK] site_id={site_id}  name={site.get('name')}")

# ── 3. 上传 CSV ────────────────────────────────────────────────────────────
step("3. 上传数据文件（8.54 MB / 166k 行）")
size = os.path.getsize(CSV)
print(f"文件大小 {size/1024/1024:.2f} MB")
t0 = time.time()
with open(CSV, "rb") as f:
    r = s.post(f"{BASE}/api/data-import/upload", headers=H,
               data={"site_id": str(site_id), "power_unit": "w"},
               files={"file": (os.path.basename(CSV), f, "text/csv")},
               timeout=900)
el = time.time() - t0
print(f"HTTP {r.status_code}  耗时 {el:.1f}s")
print(r.text[:800])

# ── 4. MCP 工具链 ─────────────────────────────────────────────────────────
MH = {"Content-Type": "application/json",
      "Accept": "application/json, text/event-stream",
      "Authorization": f"Bearer {tok}"}

def mcp(method, params=None, rid=None):
    payload = {"jsonrpc": "2.0", "id": rid or str(uuid.uuid4()),
               "method": method, "params": params or {}}
    resp = requests.post(f"{BASE}/mcp", json=payload, headers=MH, timeout=600)
    body = resp.text
    if body.lstrip().startswith("event:") or "\ndata:" in body or body.lstrip().startswith("data:"):
        body = "\n".join(l[5:].strip() for l in body.splitlines() if l.startswith("data:"))
    try:
        return resp.status_code, json.loads(body)
    except Exception:
        return resp.status_code, {"_raw": resp.text[:500]}

def call(tool, args, label=None):
    t = time.time()
    code, d = mcp("tools/call", {"name": tool, "arguments": args})
    el = (time.time() - t) * 1000
    res = d.get("result") or {}
    err = d.get("error")
    texts = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
    raw = "\n".join(texts)
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None
    is_err = bool(res.get("isError")) or err is not None
    okflag = (not is_err) and isinstance(parsed, dict) and parsed.get("success", True)
    print(f"[{'OK ' if okflag else 'ERR'}] {label or tool:<22} HTTP={code} {el:7.0f}ms  "
          f"{'' if okflag else (err or (parsed or {}).get('message') or raw)[:110]}")
    return parsed, raw

step("4. MCP 握手")
code, d = mcp("initialize", {"protocolVersion": "2025-06-18",
                             "capabilities": {},
                             "clientInfo": {"name": "run", "version": "1"}})
print("initialize HTTP", code, "->", json.dumps((d.get("result") or {}).get("serverInfo", d), ensure_ascii=False)[:200])

step("5. 八工具链（site_id=%s）" % site_id)
D = {"start_date": "2019-01-01", "end_date": "2019-01-03"}
out = {}

out["get_site"], _ = call("get_site", {"site_id": site_id}, "1 get_site")
out["check_data_quality"], _ = call("check_data_quality", {"site_id": site_id, **D}, "2 check_data_quality")
out["get_weather"], _ = call("get_weather", {"latitude": 30.542, "longitude": 101.948,
                                             "forecast_days": 2}, "3 get_weather")
fc_p, fc_r = call("forecast_power", {"site_id": site_id, **D, "mode": "historical"}, "4 forecast_power")
out["forecast_power"] = fc_p
if isinstance(fc_p, dict):
    d4 = fc_p.get("data") or {}
    print("      has_ml=", d4.get("has_ml"), "| fallback=", d4.get("fallback"),
          "| auto_train=", json.dumps(d4.get("auto_train"), ensure_ascii=False))

out["diagnose_risk"], _ = call("diagnose_risk", {"site_id": site_id, **D}, "5 diagnose_risk")
out["optimize_storage"], _ = call("optimize_storage",
                                  {"site_id": site_id, "battery_capacity": 100,
                                   "battery_power": 50, **D}, "6 optimize_storage")
out["search_knowledge"], _ = call("search_knowledge",
                                  {"query": "分时电价 储能 套利 数据质量", "top": 5}, "7 search_knowledge")
out["generate_report"], rep_raw = call("generate_report",
                                       {"site_id": site_id, **D, "mode": "historical",
                                        "battery_capacity": 100, "battery_power": 50},
                                       "8 generate_report")

step("6. 关键结果")
dq = (out.get("check_data_quality") or {}).get("data") or {}
print("数据质量:", json.dumps({k: dq.get(k) for k in
      ("total_records", "start", "end", "interval_hours", "max_gap_hours",
       "missing_rate_pct", "out_of_range_pct", "quality_level")}, ensure_ascii=False))
rk = (out.get("diagnose_risk") or {}).get("data") or {}
print("风险条数:", len(rk.get("risks") or []))
for x in (rk.get("risks") or []):
    print(f"   [{x.get('level')}] {x.get('type')}: {x.get('desc')}")
op = (out.get("optimize_storage") or {}).get("data") or {}
print("储能:", json.dumps({k: op.get(k) for k in
      ("battery_kwh", "power_kw", "province", "has_price_evidence",
       "period_days", "net_revenue_est_yuan_per_day", "net_revenue_est_yuan")}, ensure_ascii=False))
md = (out.get("generate_report") or {}).get("data", {}).get("markdown") or ""
if md:
    open("run_report.md", "w", encoding="utf-8").write(md)
    print("报告章节:")
    for line in md.split("\n"):
        if line.startswith("## "):
            print("   ", line)

step("完成")
print("报告已存 run_report.md" if md else "未生成报告")
