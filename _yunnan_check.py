# -*- coding: utf-8 -*-
"""从内置库导出云南干净数据集并运行修正后的污染检测，验证不过度告警。"""
import io
import json
import os
import subprocess
import sys

import duckdb

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

con = duckdb.connect("data/pv_data.duckdb", read_only=True)
name = con.execute(
    "select distinct filename from pv_data where filename like '%25.429%'"
).fetchone()[0]
print("dataset:", name)

out = "yunnan_export.csv"
q = f"""
select substr(datatime,1,4)||substr(datatime,6,2)||substr(datatime,9,2)||':'||
     substr(datatime,12,2)||substr(datatime,15,2) as t,
     power, gb, gd, gr, h_sun, temperature, windspeed, "int"
from pv_data where filename = ?
order by datatime
"""
rows = con.execute(q, (name,)).fetchall()
with open(out, "w", encoding="utf-8", newline="") as f:
    f.write("time,P,Gb(i),Gd(i),Gr(i),H_sun,T2m,WS10m,Int\n")
    for r in rows:
        f.write(",".join(str(x) for x in r) + "\n")
print("exported rows:", len(rows))

r = subprocess.run(
    [sys.executable, "skills/pv-station-analysis/scripts/pollution_detect.py",
     out, "--output", "yunnan_check.json"],
    capture_output=True, text=True, encoding="utf-8")
print(r.stdout)
if r.returncode != 0:
    print("STDERR:", r.stderr)

res = json.load(open("yunnan_check.json", encoding="utf-8"))
s = res["summary"]
print("=== verdict:", s["verdict"], "| hard:", s["hard_detected"],
      "| soft:", s["soft_detected"])
os.remove(out)
print("export csv removed")
