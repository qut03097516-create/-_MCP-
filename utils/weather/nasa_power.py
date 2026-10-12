"""
NASA POWER 逐小时历史气象数据拉取
=================================

数据源：https://power.larc.nasa.gov/api/temporal/hourly/point
卫星观测 + 模型同化数据（区别于 PVGIS 的典型气象年）。

字段：
  ghi  : 地表短波总辐射 ALLSKY_SFC_SW_DWN (W/m²)
  t2m  : 2 米气温 (℃)
  ws2m : 2 米风速 (m/s)，参数 WS2M

时间：API 返回 UTC，本模块统一转换为 Asia/Shanghai 后返回 tz-naive。
缺测：NASA fill_value（-999）转为 NaN 并做短时线性插值。
"""
from __future__ import annotations

import time
import datetime as dt
from typing import Optional, Tuple

import numpy as np
import pandas as pd

# NASA POWER 缺测填充值（API 文档约定 -999；pvlib 通常已替换，此处防御性再处理）
_FILL_VALUE = -999.0
# 单次插值最多跨越的小时数（超过则保留 NaN，不臆造长段数据）
_MAX_INTERP_GAP = 3
# 单年请求，兼顾稳定性与速度
_MONTHS_PER_REQUEST = 12


def _to_date(value) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    s = str(value).strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d', '%Y-%m', '%Y'):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # 兜底：截取前 10 位
    return dt.datetime.strptime(s[:10], '%Y-%m-%d').date()


def _year_segments(start: dt.date, end: dt.date):
    """把 [start, end] 切成按年的 (seg_start, seg_end) 日期段。"""
    segs = []
    cur = start
    while cur <= end:
        seg_end = min(dt.date(cur.year, 12, 31), end)
        segs.append((cur, seg_end))
        cur = seg_end + dt.timedelta(days=1)
    return segs


def fetch_nasa_power(
    latitude: float,
    longitude: float,
    start,
    end,
    *,
    retries: int = 3,
    timeout: int = 90,
) -> pd.DataFrame:
    """
    直接调用 NASA POWER Hourly API（requests，便于暴露 4xx 错误体）。

    返回北京时间 tz-naive DataFrame，列：[ts, ghi, t2m, ws2m]
    请求区间按 UTC 日期；调用方传入的 start/end 按"北京时间日期"理解，
    内部自动向前扩 1 天，保证北京日期边界完整。
    """
    import requests

    start_date = _to_date(start)
    end_date = _to_date(end)
    if end_date < start_date:
        raise ValueError('结束日期不能早于开始日期')

    # 北京时间 00:00 = UTC 前一天 16:00；UTC 请求范围向前扩 1 天
    req_start = start_date - dt.timedelta(days=1)
    req_end = end_date

    frames = []
    last_err: Optional[Exception] = None

    with requests.Session() as session:
        for seg_s, seg_e in _year_segments(req_start, req_end):
            params = {
                'parameters': 'ALLSKY_SFC_SW_DWN,T2M,WS2M',
                'community': 'RE',
                'longitude': round(longitude, 4),
                'latitude': round(latitude, 4),
                'start': seg_s.strftime('%Y%m%d'),
                'end': seg_e.strftime('%Y%m%d'),
                'format': 'JSON',
                # 关键：NASA POWER 默认 LST（地方太阳时），必须显式要求 UTC
                # 否则时间戳无法按固定偏移换算为北京时间
                'time-standard': 'UTC',
            }

            resp = None
            for attempt in range(retries):
                try:
                    resp = session.get(
                        'https://power.larc.nasa.gov/api/temporal/hourly/point',
                        params=params, timeout=timeout,
                    )
                    if resp.status_code == 200:
                        break
                    # 4xx 不重试（参数错误重试无意义），直接带上响应体报错
                    if 400 <= resp.status_code < 500:
                        raise RuntimeError(
                            f'NASA POWER 返回 {resp.status_code}：{resp.text[:500]}'
                        )
                except RuntimeError:
                    raise
                except Exception as e:  # 网络抖动 / 5xx → 退避重试
                    last_err = e
                    resp = None
                time.sleep(2 ** attempt)

            if resp is None or resp.status_code != 200:
                raise RuntimeError(
                    f'NASA POWER 请求失败（{seg_s}~{seg_e}）：'
                    f'{last_err or (resp.text[:300] if resp is not None else "无响应")}'
                )

            payload = resp.json()
            try:
                records = payload['properties']['parameter']
            except (KeyError, TypeError):
                # 详细错误通常在 messages/header
                messages = payload.get('messages') or payload.get('detail') or payload
                raise RuntimeError(f'NASA POWER 响应结构异常：{str(messages)[:500]}')

            ghi_map = records.get('ALLSKY_SFC_SW_DWN', {})
            t2m_map = records.get('T2M', {})
            ws_map = records.get('WS2M', {})

            if not ghi_map:
                raise RuntimeError(f'NASA POWER 未返回辐照数据（{seg_s}~{seg_e}）')

            rows = []
            for key, ghi_v in ghi_map.items():
                # key 格式 YYYYMMDDHH（UTC）
                t_utc = pd.Timestamp(
                    int(key[:4]), int(key[4:6]), int(key[6:8]), int(key[8:10]),
                    tz='UTC',
                )
                rows.append((
                    t_utc,
                    np.nan if ghi_v is None or float(ghi_v) <= _FILL_VALUE else float(ghi_v),
                    np.nan if (v := t2m_map.get(key)) is None or float(v) <= _FILL_VALUE else float(v),
                    np.nan if (w := ws_map.get(key)) is None or float(w) <= _FILL_VALUE else float(w),
                ))

            seg_df = pd.DataFrame(rows, columns=['ts_utc', 'ghi', 't2m', 'ws2m'])
            frames.append(seg_df)

    if not frames:
        raise RuntimeError('NASA POWER 未返回任何数据')

    df = pd.concat(frames, ignore_index=True).sort_values('ts_utc')

    # UTC → 北京时间（tz-naive，项目全链路统一）
    df['ts'] = df['ts_utc'].dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    df = df[['ts', 'ghi', 't2m', 'ws2m']]

    # 裁剪到请求的北京日期边界
    lo = pd.Timestamp(start_date)
    hi = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(hours=1)
    df = df[(df['ts'] >= lo) & (df['ts'] <= hi)].reset_index(drop=True)

    # 去重（按年分段在扩界处可能重复）
    df = df.drop_duplicates(subset='ts', keep='first').reset_index(drop=True)

    # 缺测短时插值
    for col in ('ghi', 't2m', 'ws2m'):
        df[col] = df[col].interpolate(method='linear', limit=_MAX_INTERP_GAP,
                                      limit_direction='both')
    # 辐照与风速物理下界
    df['ghi'] = df['ghi'].clip(lower=0)
    df['ws2m'] = df['ws2m'].clip(lower=0)

    return df


def coverage_report(df: pd.DataFrame) -> dict:
    """数据质量摘要（行数/时间范围/缺测率）。"""
    if df.empty:
        return {'rows': 0, 'start': None, 'end': None, 'missing_rate': 1.0}
    total = len(df)
    missing = int(df[['ghi', 't2m', 'ws2m']].isna().any(axis=1).sum())
    return {
        'rows': total,
        'start': str(df['ts'].iloc[0]),
        'end': str(df['ts'].iloc[-1]),
        'missing_rate': round(missing / total, 4) if total else 1.0,
    }
