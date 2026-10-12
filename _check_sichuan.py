# -*- coding: utf-8 -*-
"""核对内置数据集与附件空值行对应日期的数值。"""
import io
import sys

import duckdb

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

con = duckdb.connect("data/pv_data.duckdb", read_only=True)
key = "Timeseries_30.542_101.948_E5_1kWp_crystSi_14_v47deg_2005_2023.csv"

print("first/last:", con.execute(
    "select min(datatime), max(datatime) from pv_data where filename=?", (key,)
).fetchone())

for d in ("2009-05-06", "2009-05-07", "2009-05-08", "2021-05-06", "2005-06-17"):
    r = con.execute(
        "select count(*), sum(case when power = 0 then 1 else 0 end), "
        "round(avg(power), 2), round(max(power), 2) "
        "from pv_data where filename = ? and datatime like ?",
        (key, d + "%"),
    ).fetchone()
    print(d, "rows / zeroP / avgP / maxP:", r)
