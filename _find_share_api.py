# -*- coding: utf-8 -*-
"""从 dumate_index.js 中解析分享快照加载 API。"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

s = open("dumate_index.js", encoding="utf-8").read()

# 1) 分享快照模块 36697
i = s.find("36697(e,t,i)")
print("module 36697 @", i)
seg = s[i:i + 8000]
print("--- api paths in module 36697 ---")
print(sorted(set(re.findall(r"/api/[A-Za-z0-9_/\-]+", seg))))
print("--- path: contexts ---")
for m in re.finditer(r"path\s*[:=]\s*[`\"']([^`\"']{0,160})", seg):
    print(" ", m.group(1))

# 2) 全局所有 share 相关 api 路径
print("--- all share api paths in bundle ---")
print(sorted(set(re.findall(r"/api/[A-Za-z0-9_/\-]*share[A-Za-z0-9_/\-]*", s))))

# 3) snapshot / contentUrl 加载相关
print("--- Am/h6 function defs hint ---")
for pat in (r"Am\s*[:=]\s*async", r"h6\s*[:=]\s*async", r"sessionSnapshot", r"snapshot/code", r"snapshot\?"):
    for m in list(re.finditer(pat, s))[:3]:
        st = max(0, m.start() - 120)
        print(f"[{pat} @ {m.start()}]", s[st:m.start() + 280].replace("\n", " ")[:400])
