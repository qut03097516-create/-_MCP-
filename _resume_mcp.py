# -*- coding: utf-8 -*-
"""补齐上次失败的四项 MCP 工具：diagnose_risk / optimize_storage / search_knowledge / generate_report。"""
import io
import json
import sys
import time
import uuid

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "http://127.0.0.1:8000"
PV = "四川 - Timeseries_30.542_101.948_E5_1kWp_crystSi_14_v47deg_2005_2023.csv"

s = requests.Session()
r = s.post(f"{BASE}/api/auth/login", json={"username": "mcp_test", "password": "McpTest@2026"}, timeout=60)
r.raise_for_status()
tok = r.json()["access_token"]
MH = {"Content-Type": "application/json",
      "Accept": "application/json, text/event-stream",
      "Authorization": f"Bearer {tok}"}
print(f"[OK] login, token len={len(tok)}")


def mcp(method, params=None):
    payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()),
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
          f"{'' if okflag else (err or (parsed or {}).get('message') or raw)[:160]}")
    return parsed


code, d = mcp("initialize", {"protocolVersion": "2025-06-18",
                             "capabilities": {},
                             "clientInfo": {"name": "resume", "version": "1"}})
print("initialize HTTP", code)

out = {}
out["diagnose_risk"] = call("diagnose_risk",
                            {"pv_file": PV, "forecast_days": 2}, "5 diagnose_risk")
out["optimize_storage"] = call("optimize_storage",
                               {"pv_file": PV, "battery_capacity": 1000,
                                "battery_power": 500}, "6 optimize_storage")
out["search_knowledge"] = call("search_knowledge",
                               {"query": "光伏电站 风险诊断 低温 数据异常 储能 分时电价",
                                "top": 5}, "7 search_knowledge")
out["generate_report"] = call("generate_report",
                              {"pv_file": PV, "forecast_days": 2,
                               "battery_capacity": 1000, "battery_power": 500},
                              "8 generate_report")

rk = (out.get("diagnose_risk") or {}).get("data") or {}
print("\n风险条数:", len(rk.get("risks") or []))
for x in (rk.get("risks") or []):
    print(f"   [{x.get('level')}] {x.get('type')}: {x.get('desc')}")

op = (out.get("optimize_storage") or {}).get("data") or {}
print("储能:", json.dumps({k: op.get(k) for k in
      ("battery_kwh", "power_kw", "province", "has_price_evidence",
       "period_days", "net_revenue_est_yuan_per_day", "net_revenue_est_yuan")},
      ensure_ascii=False))

sk = (out.get("search_knowledge") or {}).get("data") or {}
hits = sk.get("hits") or sk.get("results") or []
print("知识命中:", len(hits))
for h in hits[:5]:
    print("   -", (h.get("title") or h.get("name") or str(h))[:80])

md = (out.get("generate_report") or {}).get("data", {}).get("markdown") or ""
if md:
    open("resume_report.md", "w", encoding="utf-8").write(md)
    print("\n报告章节:")
    for line in md.split("\n"):
        if line.startswith("## "):
            print("   ", line)
else:
    print("\n未拿到 markdown；原始:", json.dumps(
        {k: list((v or {}).keys()) if isinstance(v, dict) else type(v).__name__
         for k, v in out.items()}, ensure_ascii=False)[:500])

json.dump({k: v for k, v in out.items()}, open("resume_results.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("\n完成，详见 resume_report.md / resume_results.json")
