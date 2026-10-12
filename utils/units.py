"""
utils/units.py - 全系统唯一单位口径层（T4 单位统一与发电量积分）

统一口径（对外展示 / API 输出）：
    capacity_kwp : float  光伏装机容量（kWp，1 kWp 站点 = 1.0）
    power_kw     : float  某时刻平均功率（kW）
    energy_kwh   : float  某时间段发电量（kWh）
    ghi / poa_global : W/m²

内部约定（数据存储 / 模型资产）：
    数据库 pv_data.power 与已训练模型 scaler.bins.stats 均为 W 量级；
    物理模型 p_phys_kw / 混合模型 p_final_kw 为 kW 量级。
    一切对外输出（REST API / 前端 / AI 上下文）统一在本模块转换为 kW，
    训练与推理内部保持 W 口径不变，避免重训既有模型资产。

警告：禁止在多个文件里各自 /1000 猜测单位，转换只允许发生在本模块定义的函数中。
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

import numpy as np
import pandas as pd

WATTS_PER_KILOWATT = 1000.0

KWP_PATTERN = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*kWp", re.IGNORECASE)


def parse_capacity_kwp(pv_file: str, default: float = 1.0) -> float:
    """从文件名解析装机容量 kWp，例如 'Timeseries_..._1kWp_....csv' -> 1.0。

    解析失败返回 default（批量仿真站点默认均为 1 kWp）。
    """
    try:
        base = pv_file.replace("\\", "/").split("/")[-1]
        m = KWP_PATTERN.search(base)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return default


def w_to_kw(values, decimals: int = 4):
    """瓦 -> 千瓦（输入可为标量 / numpy 数组 / pandas Series）。"""
    return (np.asarray(values, dtype=float) / WATTS_PER_KILOWATT).round(decimals)


def power_range_check(power_kw, capacity_kwp: float, factor: float = 1.2) -> Tuple[bool, Optional[float]]:
    """物理范围校验：power_kw 应处于 [0, capacity_kwp * factor]。

    返回 (是否越界, 越界时的功率峰值 kW)；合法返回 (False, None)。
    """
    arr = np.asarray(power_kw, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return False, None
    upper = float(capacity_kwp) * factor
    invalid = (arr < 0) | (arr > upper)
    if invalid.any():
        return True, float(np.nanmax(arr[invalid]))
    return False, None


def median_interval_hours(timestamps) -> float:
    """按相邻时间戳的中位间隔（小时）计算采样间隔，用于发电量积分。

    输入：可转为 pandas 时间序列的数组/Series；至少需要 2 个时间点。
    """
    ts = pd.to_datetime(pd.Series(timestamps))
    if ts.nunique() < 2:
        return 1.0
    diffs = ts.sort_values().diff().dt.total_seconds().dropna()
    diffs = diffs[diffs > 0]
    if diffs.empty:
        return 1.0
    return float(np.median(diffs.values) / 3600.0)


def energy_kwh_from_power_kw(power_kw, timestamps) -> float:
    """由功率序列（kW）与时间戳序列积分得到发电量（kWh）。

    energy_kwh = Σ power_kw_i * h_i，h_i 取全序列中位时间间隔（小时）。
    """
    p = np.asarray(power_kw, dtype=float)
    p = p[~np.isnan(p)]
    if p.size == 0:
        return 0.0
    interval_h = median_interval_hours(timestamps)
    return float(p.sum() * interval_h)