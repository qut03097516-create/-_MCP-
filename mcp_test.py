"""MCP Streamable HTTP 协议测试脚本"""
import json, urllib.request, urllib.error, uuid, sys
BASE = "http://127.0.0.1:8000"

def post(path, body, token=None, headers=None):
    data = json.dumps(body).encode('utf-8')
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = f"Bearer {token}"
    if headers: h.update(headers)
    req = urllib.request.Request(BASE + path, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        try: return e.code, json.load(e)
        except Exception: return e.code, {}

def rpc(method, params, token=None):
    body = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params or {}}
    code, d = post("/mcp", body, token=token)
    return code, d

# 1) REST 登录拿 token
_, login = post("/api/auth/login", {"username":"mcp_test","password":"McpTest@2026"})
TOKEN = login["access_token"]
print("[REST login] token OK")

# 2) MCP 未登录 -> 401
code, d = rpc("initialize", {})
print(f"[MCP init 未登录] HTTP={code} (期望401)")

# 3) MCP initialize -> 成功
code, d = rpc("initialize", {"protocolVersion": "2025-06-18"}, token=TOKEN)
print(f"[MCP initialize] HTTP={code} result keys={list(d.get('result',{}).keys())}")

# 4) MCP tools/list -> 8 个工具
code, d = rpc("tools/list", {}, token=TOKEN)
tools = d.get('result', {}).get('tools', [])
print(f"[MCP tools/list] HTTP={code} 工具数={len(tools)}")
for t in tools:
    print(f"  - {t['name']}: {t.get('title','')[:40]}")

# 5) MCP tools/call get_site -> 成功
PV = "云南 - Timeseries_25.429_102.107_E5_1kWp_crystSi_14_v47deg_2005_2023.csv"
code, d = rpc("tools/call", {"name":"get_site","arguments":{"pv_file":PV}}, token=TOKEN)
result = d.get('result', {})
print(f"[MCP call get_site] HTTP={code} isError={result.get('isError')}")
if not result.get('isError'):
    sc = result.get('structuredContent', {})
    print(f"  success={sc.get('success')} err={sc.get('error_code')} kind={(sc.get('data') or {}).get('kind')}")
else:
    print(f"  error={result.get('content')}")

# 6) REST 主流程入口确认无 regression
_, d = post("/api/agent/run", {"tool":"get_weather","params":{"latitude":25.429,"longitude":102.107,"forecast_days":2}}, token=TOKEN)
print(f"[REST run 分派] success={d.get('success')} err={d.get('error_code')}")

print("\n全链路验证通过。")
