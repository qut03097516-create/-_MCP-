# -*- coding: utf-8 -*-
"""导出分享会话的关键消息全文。"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

j = json.load(open("share_snapshot.json", encoding="utf-8"))
msgs = j.get("messages") or []

WANT = [24, 35, 54, 83, 115, 130, 142, 189]
for i in WANT:
    m = msgs[i]
    texts = [p.get("text", "") for p in (m.get("parts") or [])
             if isinstance(p, dict) and p.get("type") == "text"]
    t = "\n".join(texts)
    print("=" * 30, f"msg[{i}] ({len(t)} chars)", "=" * 30)
    print(t[:3500])
    if len(t) > 3500:
        print(f"...[截断，共 {len(t)} 字符]")
    print()
