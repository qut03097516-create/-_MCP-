"""
光伏直流功率物理模型
====================

计算链路（pvlib）：
  GHI ──erbs 分解──→ DNI / DHI
  太阳位置(SPA) + 倾角/方位角 ──perez──→ 倾斜面总辐照度 POA
  POA + 环境温度 + 风速 ──faiman──→ 组件温度 T_cell
  POA + T_cell ──Huld(cSi, PVGIS5 系数)──→ 逐小时直流功率 P_dc

时间约定：输入 ts 为北京时间 tz-naive，内部转 Asia/Shanghai。
硬约束：夜间功率为 0、非负、不超过装机容量。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pvlib import solarposition, irradiance, atmosphere, temperature, pvarray

# Faiman 组件热模型经验系数（典型 cSi 开放式支架）
_FAIMAN_U0 = 25.0
_FAIMAN_U1 = 6.84
# Huld 电池类型与 PVGIS 系数版本
_CELL_TYPE = 'cSi'
_K_VERSION = 'pvgis5'

REQUIRED_COLS = ['ts', 'ghi', 't2m', 'ws2m']


def compute_physics_power(
    df: pd.DataFrame,
    latitude: float,
    longitude: float,
    tilt: float,
    azimuth: float = 0.0,
    kwp: float = 1.0,
    loss_pct: float = 14.0,
    altitude: float = 0.0,
) -> pd.DataFrame:
    """
    由逐小时气象计算物理基准直流功率。

    参数
    ----
    df : 含 [ts, ghi, t2m, ws2m]，ts 为北京时间 tz-naive
    latitude/longitude : 经纬度
    tilt : 组件安装倾角(度)
    azimuth : 组件方位角(度)，0=正南（pvlib 约定正南=180，内部转换）
    kwp : 装机容量 kWp
    loss_pct : 系统综合损耗 %（线损/失配/灰尘/逆变器等）

    返回
    ----
    DataFrame：原列 + solar_zenith, dni, dhi, poa_global, t_cell, p_phys_kw
    """
    out = df.copy()
    missing = [c for c in REQUIRED_COLS if c not in out.columns]
    if missing:
        raise ValueError(f'物理模型缺少必要列: {missing}')

    out['ts'] = pd.to_datetime(out['ts'])
    # 北京时间 tz-aware（pvlib 需要时区计算太阳位置）
    # 统一用 DatetimeIndex：pvlib 部分函数（erbs/get_extra_radiance）对 Series 入参兼容差，
    # 且其返回结果以时间为索引，因此工作变量全部对齐到时间索引，最后再写回 out
    ts_idx = pd.DatetimeIndex(out['ts']).tz_localize('Asia/Shanghai')

    ghi = pd.to_numeric(out['ghi'], errors='coerce').fillna(0.0).clip(lower=0)
    ghi.index = ts_idx
    t_air = pd.to_numeric(out['t2m'], errors='coerce')
    t_air.index = ts_idx
    wind = pd.to_numeric(out['ws2m'], errors='coerce').fillna(0.0).clip(lower=0)
    wind.index = ts_idx

    # 1. 太阳位置（SPA）
    solpos = solarposition.get_solarposition(
        time=ts_idx, latitude=latitude, longitude=longitude,
        altitude=altitude, temperature=t_air.fillna(10.0),
    )
    zenith = solpos['apparent_zenith'].clip(lower=0, upper=180)
    solar_az = solpos['azimuth']

    # 2. GHI → DNI / DHI（erbs）。夜间天顶角≥90° 直接置 0，避免分解出负值
    day_mask = (zenith < 90) & (ghi > 0)
    erbs = irradiance.erbs(ghi.where(day_mask, 0.0), zenith, ts_idx)
    dni = erbs['dni'].fillna(0.0).clip(lower=0).where(day_mask, 0.0)
    dhi = erbs['dhi'].fillna(0.0).clip(lower=0).where(day_mask, 0.0)

    # 3. 倾斜面总辐照度（perez）
    # pvlib 方位角约定：正北=0、正东=90、正南=180；用户输入 0=正南
    surface_azimuth_pvlib = (float(azimuth) + 180.0) % 360.0
    dni_extra = irradiance.get_extra_radiation(ts_idx)
    airmass = atmosphere.get_relative_airmass(zenith)
    poa = irradiance.get_total_irradiance(
        surface_tilt=float(tilt),
        surface_azimuth=surface_azimuth_pvlib,
        solar_zenith=zenith,
        solar_azimuth=solar_az,
        dni=dni,
        ghi=ghi,
        dhi=dhi,
        dni_extra=dni_extra,
        airmass=airmass,
        model='perez',
    )
    poa_global = poa['poa_global'].fillna(0.0).clip(lower=0)

    # 4. 组件温度（Faiman 热模型）
    t_cell = temperature.faiman(
        poa_global, t_air.fillna(t_air.median() if t_air.notna().any() else 10.0),
        wind, u0=_FAIMAN_U0, u1=_FAIMAN_U1,
    )

    # 5. Huld 直流功率（W → kW），应用系统综合损耗
    p_dc_w = pvarray.huld(
        effective_irradiance=poa_global,
        temp_mod=t_cell,
        pdc0=float(kwp) * 1000.0,
        cell_type=_CELL_TYPE,
        k_version=_K_VERSION,
    )
    p_kw = pd.Series(np.asarray(p_dc_w, dtype=float) / 1000.0).clip(lower=0.0)
    p_kw = p_kw * (1.0 - float(loss_pct) / 100.0)

    # 6. 硬物理约束：夜间为 0、非负、上限装机容量
    night = (~day_mask).to_numpy()
    p_kw_np = np.array(p_kw.to_numpy(), dtype=float, copy=True)
    p_kw_np[night] = 0.0
    p_kw_np = np.clip(p_kw_np, 0.0, float(kwp))

    out['solar_zenith'] = np.round(zenith.to_numpy(), 2)
    out['dni'] = np.round(dni.to_numpy(), 2)
    out['dhi'] = np.round(dhi.to_numpy(), 2)
    out['poa_global'] = np.round(poa_global.to_numpy(), 2)
    out['t_cell'] = np.round(np.asarray(t_cell, dtype=float), 2)
    out['p_phys_kw'] = np.round(p_kw_np, 4)
    return out


def daily_energy(df: pd.DataFrame, power_col: str = 'p_phys_kw') -> pd.Series:
    """逐小时功率(kW) → 逐日发电量(kWh)。"""
    s = df[[ 'ts', power_col]].copy()
    s['ts'] = pd.to_datetime(s['ts'])
    return s.set_index('ts')[power_col].resample('D').sum()
