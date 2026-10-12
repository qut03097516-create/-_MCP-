"""
Open-Meteo 未来天气预报（逐小时）
================================

免费、无需 API key。输出结构与 NASA POWER 模块一致：
  [ts(北京时间 tz-naive), ghi, t2m, ws2m]

字段映射：
  shortwave_radiation (W/m², 小时均值) → GHI
  temperature_2m                         → T2M
  wind_speed_10m                         → 经对数律换算为 2m 风速 WS2M

风速换算（对数风廓线，地表粗糙度长度 z0=0.15m，平坦草地典型值）：
  WS2 = WS10 * ln(2/z0) / ln(10/z0)
"""
from __future__ import annotations

import io
import json
import time

import requests
import pandas as pd

OPEN_METEO_URL = 'https://api.open-meteo.com/v1/forecast'
# ln(2/0.15)/ln(10/0.15)
_WIND_10_TO_2 = 0.617
TIMEOUT = 30


def fetch_open_meteo_forecast(latitude: float, longitude: float,
                              forecast_days: int = 7,
                              past_days: int = 0) -> pd.DataFrame:
    """
    拉取未来逐小时预报（可选附带 past_days 天历史预报，用于与当前时刻衔接）。

    返回
    ----
    DataFrame: [ts, ghi, t2m, ws2m]，ts 为北京时间 tz-naive，按小时排序
    """
    params = {
        'latitude': latitude,
        'longitude': longitude,
        'hourly': 'shortwave_radiation,temperature_2m,wind_speed_10m',
        'forecast_days': int(forecast_days),
        'timezone': 'Asia/Shanghai',
    }
    if past_days:
        params['past_days'] = int(past_days)

    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(OPEN_METEO_URL, params=params, timeout=TIMEOUT)
            if resp.status_code != 200:
                body = resp.text[:300]
                last_err = RuntimeError(
                    f'Open-Meteo 返回 HTTP {resp.status_code}: {body}')
                # 4xx 不重试（参数错误重试无意义），仅 5xx/网络错误重试
                if 400 <= resp.status_code < 500:
                    raise last_err
            else:
                payload = resp.json()
                break
        except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
            last_err = e
        if attempt < 2:
            time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f'Open-Meteo 请求失败（已重试3次）: {last_err}')

    hourly = payload.get('hourly')
    if not hourly or 'time' not in hourly:
        raise RuntimeError('Open-Meteo 响应缺少 hourly 数据，请检查坐标参数')

    df = pd.DataFrame({
        'ts': pd.to_datetime(hourly['time']),
        'ghi': pd.to_numeric(hourly.get('shortwave_radiation', []), errors='coerce'),
        't2m': pd.to_numeric(hourly.get('temperature_2m', []), errors='coerce'),
        'ws10': pd.to_numeric(hourly.get('wind_speed_10m', []), errors='coerce'),
    })
    if df.empty:
        raise RuntimeError('Open-Meteo 返回空预报数据')

    df['ws2m'] = (df['ws10'] * _WIND_10_TO_2).clip(lower=0)
    df['ghi'] = df['ghi'].fillna(0.0).clip(lower=0)
    # 极少量缺测线性插值
    df['t2m'] = df['t2m'].interpolate(limit=3)
    df['ws2m'] = df['ws2m'].fillna(0.0)

    # API 已按 Asia/Shanghai 返回本地时间字符串，去掉 tz 信息统一为 tz-naive
    if df['ts'].dt.tz is not None:
        df['ts'] = df['ts'].dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    df = df[['ts', 'ghi', 't2m', 'ws2m']].sort_values('ts').reset_index(drop=True)
    return df
