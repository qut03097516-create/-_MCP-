# -*- coding: utf-8 -*-
"""批量预训缺模型的内置数据集（串行，避免抢核）。"""
import io
import json
import sys
import time

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

BASE = "http://127.0.0.1:8000"
EPOCHS = 5        # 实测 16.6 万行 5 轮约 531 秒
PATIENCE = 3

s = requests.Session()
r = s.post(f"{BASE}/api/auth/login",
           json={"username": "mcp_test", "password": "McpTest@2026"}, timeout=60)
tok = r.json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}

r = s.get(f"{BASE}/api/data/sites", headers=H, timeout=60)
names = [x["filename"] for x in r.json()]

print(f"内置数据集 {len(names)} 个，开始逐个检查/训练...", flush=True)

todo = []
for f in names:
    # get_site 的 model_ready 通过 MCP 拿；这里直接查模型目录更省事
    from utils.predictor import get_safe_name
    import os
    d = os.path.join("models", get_safe_name(f), "iid_transformer_lstm")
    has = os.path.isdir(d) and any(
        x.startswith("interval_") and x.endswith(".pt") for x in os.listdir(d))
    print(f"  {'[有]' if has else '[缺]'} {f}", flush=True)
    if not has:
        todo.append(f)

print(f"\n待训练 {len(todo)} 个，预计每个约 {EPOCHS * 106 // 5} 秒", flush=True)

for i, f in enumerate(todo, 1):
    print(f"\n[{i}/{len(todo)}] {f}", flush=True)
    try:
        resp = s.post(f"{BASE}/api/prediction/train", headers=H, json={
            "pv_file": f, "model_type": "iid_transformer_lstm",
            "epochs": EPOCHS, "batch_size": 32, "seq_len": 24,
            "learning_rate": 0.001, "patience": PATIENCE,
        }, timeout=120)
        body = resp.json()
    except Exception as e:
        print(f"  提交失败: {e}", flush=True)
        continue
    if not body.get("success"):
        print(f"  提交被拒: {body.get('error')}", flush=True)
        continue
    job = body["job_id"]
    print(f"  job={job} 等待完成...", flush=True)
    t0 = time.time()
    while True:
        time.sleep(15)
        try:
            p = s.get(f"{BASE}/api/prediction/train/progress/{job}",
                      headers=H, timeout=60).json()
        except Exception as e:
            print(f"  轮询异常: {e}", flush=True)
            continue
        st = p.get("status")
        if st in ("done", "failed"):
            el = int(time.time() - t0)
            print(f"  {st} 耗时 {el}s {p.get('message') or p.get('error') or ''}",
                  flush=True)
            break
        print(f"    {int(time.time() - t0)}s progress={p.get('progress')} "
              f"{p.get('message', '')}", flush=True)

print("\n===== 批量预训结束 =====", flush=True)
