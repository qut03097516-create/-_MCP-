from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional, List, Any
import sys
import os
import math
import json
import hashlib
import datetime as _dt

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils.data_loader import get_data_files, get_date_range, load_pv_data, preprocess_data
from utils.predictor import parse_pv_filename

router = APIRouter()

class SiteInfo(BaseModel):
    filename: str
    display_name: str
    latitude: str
    longitude: str
    system_size: str
    module_type: str
    install_angle: str
    year_range: str

@router.get("/sites")
async def get_sites():
    """获取所有光伏站点列表"""
    pv_files = get_data_files()
    sites = []
    for pf in pv_files:
        site_info = parse_pv_filename(pf)
        sites.append(SiteInfo(
            filename=pf,
            display_name=pf,
            latitude=site_info.get('latitude', 'N/A'),
            longitude=site_info.get('longitude', 'N/A'),
            system_size=site_info.get('system_size', 'N/A'),
            module_type=site_info.get('module_type', 'N/A'),
            install_angle=site_info.get('install_angle', 'N/A'),
            year_range=site_info.get('year_range', 'N/A')
        ))
    return sites

@router.get("/site/{pv_file}/info")
async def get_site_info(pv_file: str):
    """获取站点详细信息"""
    site_info = parse_pv_filename(pv_file)
    try:
        min_date, max_date = get_date_range(pv_file)
        date_range = {
            'min_date': str(min_date),
            'max_date': str(max_date)
        }
    except:
        date_range = {'min_date': '', 'max_date': ''}

    return {
        **site_info,
        **date_range
    }

@router.get("/site/{pv_file}/data")
async def get_site_data(
    pv_file: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_rows: int = Query(default=2000, le=50000)
):
    """获取站点数据"""
    try:
        df = load_pv_data(pv_file)
        
        # 如果没有数据，返回空结果
        if df is None or len(df) == 0:
            return {
                'success': True,
                'data': [],
                'columns': []
            }
        
        # 日期筛选
        if start_date and end_date:
            df['DATATIME'] = pd.to_datetime(df['DATATIME'])
            start = pd.to_datetime(start_date).date()
            end = pd.to_datetime(end_date).date()
            df = df[(df['DATATIME'].dt.date >= start) & (df['DATATIME'].dt.date <= end)]
        
        # 降采样
        if len(df) > max_rows:
            df = df.iloc[::max(1, len(df) // max_rows)]
        
        # 转换为字典列表
        df['DATATIME'] = df['DATATIME'].astype(str)
        data = df.to_dict(orient='records')
        
        return {
            'success': True,
            'data': data,
            'columns': list(df.columns)
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

@router.get("/site/{pv_file}/date-range")
async def get_site_date_range(pv_file: str):
    """获取站点日期范围"""
    try:
        min_date, max_date = get_date_range(pv_file)
        return {
            'min_date': str(min_date),
            'max_date': str(max_date)
        }
    except Exception as e:
        return {'min_date': None, 'max_date': None, 'error': str(e)}


# =============================================================================
# PVGIS 在线数据接口（pvlib → 欧盟 PVGIS，无需本地文件）
# =============================================================================

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PVGIS_CACHE_DIR = os.path.join(_PROJECT_ROOT, 'data', 'pvgis_cache')
PVGIS_MAX_ROWS = 20000  # 单次最多返回行数（多年查询自动降采样）


def _parse_pvgis_date(value: str):
    """'2019' -> int(2019); '2019-06-01' -> datetime.date"""
    value = (value or '').strip()
    if len(value) == 4 and value.isdigit():
        return int(value)
    return _dt.datetime.strptime(value[:10], '%Y-%m-%d').date()


def _pvgis_cache_key(parts: dict) -> str:
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode('utf-8')).hexdigest()[:16]


@router.get("/pvgis")
def get_pvgis(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    start: str = Query(..., description="开始：2019 或 2019-06-01"),
    end: str = Query(..., description="结束：2020 或 2020-08-31"),
    surface_tilt: float = Query(35, ge=0, le=90, description="组件倾角(度)"),
    surface_azimuth: float = Query(0, ge=-180, le=180, description="方位角，0=正南"),
    peakpower: float = Query(1.0, gt=0, le=1000, description="装机容量 kWp"),
    loss: float = Query(14.0, ge=0, le=100, description="系统损耗 %"),
):
    """从 PVGIS 获取小时级辐照/温度/模拟功率，字段与本地数据集对齐"""
    import time as _time
    import pvlib

    try:
        start_parsed = _parse_pvgis_date(start)
        end_parsed = _parse_pvgis_date(end)
    except Exception:
        return {'success': False, 'error': '日期格式错误，请使用 2019 或 2019-06-01 格式'}

    # 年份跨度保护（PVGIS 单次请求数据量上限）
    sy = start_parsed if isinstance(start_parsed, int) else start_parsed.year
    ey = end_parsed if isinstance(end_parsed, int) else end_parsed.year
    if ey < sy:
        return {'success': False, 'error': '结束年份不能早于开始年份'}
    if ey - sy > 4:
        return {'success': False, 'error': '单次最多查询 5 年数据，请缩小年份范围'}
    if sy < 2005 or ey > 2030:
        return {'success': False, 'error': 'PVGIS 历史数据范围约为 2005-2020（部分地区更新），请调整年份'}

    cache_parts = {
        'lat': round(latitude, 4), 'lon': round(longitude, 4),
        # PVGIS seriescalc 仅支持年份粒度，缓存按年份区间，同年不同日期裁剪可复用
        'year_start': sy, 'year_end': ey,
        'tilt': surface_tilt, 'az': surface_azimuth,
        'kwp': peakpower, 'loss': loss,
    }
    key = _pvgis_cache_key(cache_parts)
    os.makedirs(PVGIS_CACHE_DIR, exist_ok=True)
    csv_path = os.path.join(PVGIS_CACHE_DIR, f'{key}.csv')
    meta_path = os.path.join(PVGIS_CACHE_DIR, f'{key}.json')

    t0 = _time.time()
    cached = False

    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        cached = True
    else:
        try:
            # PVGIS seriescalc 仅支持年份粒度，按年请求
            raw, raw_meta = pvlib.iotools.get_pvgis_hourly(
                latitude=latitude,
                longitude=longitude,
                start=sy,
                end=ey,
                surface_tilt=surface_tilt,
                surface_azimuth=surface_azimuth,
                pvcalculation=True,
                peakpower=peakpower,
                loss=loss,
                usehorizon=True,
                timeout=90,
            )
        except Exception as e:
            return {'success': False, 'error': f'PVGIS 请求失败：{str(e)}（欧洲服务器，可稍后重试）'}

        if raw is None or len(raw) == 0:
            return {'success': False, 'error': 'PVGIS 未返回数据，请检查坐标或年份范围'}

        # UTC → 北京时间（项目统一使用 Asia/Shanghai）
        raw.index = raw.index.tz_convert('Asia/Shanghai')
        raw = raw.reset_index().rename(columns={'time': 'DATATIME'})

        # 字段对齐本地数据集：DATATIME / POWER / GLOBAL_HORIZONTAL_IRRADIANCE / TEMPERATURE / WINDSPEED
        poa_total = (raw['poa_direct'].fillna(0)
                     + raw['poa_sky_diffuse'].fillna(0)
                     + raw['poa_ground_diffuse'].fillna(0))
        df = pd.DataFrame({
            'DATATIME': raw['DATATIME'].dt.strftime('%Y-%m-%d %H:%M:%S'),
            'POWER': raw['P'].round(2),                    # W（peakpower kWp 对应）
            'GLOBAL_HORIZONTAL_IRRADIANCE': poa_total.round(2),  # 斜面总辐照 W/m²
            'TEMPERATURE': raw['temp_air'].round(2),
            'WINDSPEED': raw['wind_speed'].round(2),
        })

        meta = {
            'source': 'PVGIS (pvlib)',
            'latitude': latitude,
            'longitude': longitude,
            'year_start': sy,
            'year_end': ey,
            'surface_tilt': surface_tilt,
            'surface_azimuth': surface_azimuth,
            'peakpower_kwp': peakpower,
            'loss_percent': loss,
            'timezone': 'Asia/Shanghai',
            'note': 'GLOBAL_HORIZONTAL_IRRADIANCE 字段为组件斜面总辐照度(直射+天空散射+地面反射)',
            'min_date': df['DATATIME'].iloc[0],
            'max_date': df['DATATIME'].iloc[-1],
            'rows_total': len(df),
        }

        # 写文件缓存（按年份区间的完整数据）
        try:
            df.to_csv(csv_path, index=False)
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # 精确日期裁剪（PVGIS 按年返回，用户选择具体日期时在年内过滤；end 含当天）
    if isinstance(start_parsed, _dt.date) and not isinstance(start_parsed, int):
        dt_series = pd.to_datetime(df['DATATIME'])
        start_ts = pd.Timestamp(start_parsed)
        end_exclusive = pd.Timestamp(end_parsed) + pd.Timedelta(days=1)
        df = df[(dt_series >= start_ts) & (dt_series < end_exclusive)].reset_index(drop=True)

    if len(df) == 0:
        return {'success': False, 'error': '所选日期范围内无数据（PVGIS 历史数据约覆盖 2005-2020 年）'}

    # 行数保护：超过上限等间隔降采样
    total_rows = len(df)
    if total_rows > PVGIS_MAX_ROWS:
        step = math.ceil(total_rows / PVGIS_MAX_ROWS)
        df = df.iloc[::step].reset_index(drop=True)

    records = df.where(pd.notna(df), None).to_dict(orient='records')
    elapsed = round(_time.time() - t0, 2)

    # 返回裁剪后的实际范围（meta 保留年份缓存信息）
    result_meta = dict(meta)
    result_meta['min_date'] = df['DATATIME'].iloc[0]
    result_meta['max_date'] = df['DATATIME'].iloc[-1]
    result_meta['rows_total'] = len(df)

    return {
        'success': True,
        'source': 'pvgis',
        'cached': cached,
        'data': records,
        'columns': list(df.columns),
        'count': len(records),
        'meta': result_meta,
        'elapsed': elapsed,
    }


# =============================================================================
# NASA POWER 真实气象数据接口（卫星同化，DuckDB 本地缓存 + 增量更新）
# =============================================================================

NASA_MAX_SPAN_DAYS = 370  # 即时查询最大跨度（约 1 年）；多年回填走站点后台任务


@router.get("/nasa-power")
def get_nasa_power_route(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    start: str = Query(..., description="开始日期 YYYY-MM-DD（北京时间）"),
    end: str = Query(..., description="结束日期 YYYY-MM-DD（北京时间）"),
    force_refresh: bool = Query(False, description="忽略缓存整段重拉"),
):
    """获取 NASA POWER 逐小时 GHI/气温/风速，缺啥拉啥并写入本地缓存"""
    import time as _time
    from utils.weather.store import get_weather

    try:
        sd = _dt.datetime.strptime(start[:10], '%Y-%m-%d').date()
        ed = _dt.datetime.strptime(end[:10], '%Y-%m-%d').date()
    except Exception:
        return {'success': False, 'error': '日期格式错误，请使用 YYYY-MM-DD'}

    if ed < sd:
        return {'success': False, 'error': '结束日期不能早于开始日期'}
    if (ed - sd).days > NASA_MAX_SPAN_DAYS:
        return {'success': False,
                'error': f'即时查询最多 {NASA_MAX_SPAN_DAYS} 天，多年数据请先在站点中回填'}

    t0 = _time.time()
    try:
        df, meta = get_weather(latitude, longitude, sd, ed, force_refresh=force_refresh)
    except Exception as e:
        return {'success': False, 'error': f'NASA POWER 获取失败：{str(e)}'}

    if df.empty:
        return {'success': False, 'error': '所选日期范围内无气象数据'}

    records = df.where(pd.notna(df), None).to_dict(orient='records')
    for r in records:
        r['ts'] = str(pd.Timestamp(r['ts']))
        for k in ('ghi', 't2m', 'ws2m'):
            if r[k] is not None:
                r[k] = round(float(r[k]), 2)

    return {
        'success': True,
        'source': 'nasa_power',
        'data': records,
        'columns': ['ts', 'ghi', 't2m', 'ws2m'],
        'count': len(records),
        'meta': {
            'latitude': latitude,
            'longitude': longitude,
            'start': start[:10],
            'end': end[:10],
            'timezone': 'Asia/Shanghai',
            **meta,
            'min_date': str(df['ts'].iloc[0]),
            'max_date': str(df['ts'].iloc[-1]),
        },
        'elapsed': round(_time.time() - t0, 2),
    }


# =============================================================================
# 逆地理编码（经纬度 → 真实行政区划），替代旧的"本地数据集站点最近邻"
# BigDataCloud 免费客户端端点：无需 API Key，中文返回，按 0.01° 网格持久缓存
# =============================================================================

GEOCODE_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'data', 'geocode_cache.json')
_geocode_lock = __import__('threading').Lock()
GEOCODE_GRID = 2  # 与气象缓存一致：0.01° 网格


def _load_geocode_cache() -> dict:
    if os.path.exists(GEOCODE_CACHE_FILE):
        try:
            with open(GEOCODE_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_geocode_cache(cache: dict):
    os.makedirs(os.path.dirname(GEOCODE_CACHE_FILE), exist_ok=True)
    tmp = GEOCODE_CACHE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    os.replace(tmp, GEOCODE_CACHE_FILE)


@router.get("/reverse-geocode")
async def reverse_geocode(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
):
    """经纬度 → 国家/省/市/区县（BigDataCloud，免 key，0.01° 网格缓存）"""
    import httpx

    key = f"{round(float(latitude), GEOCODE_GRID)},{round(float(longitude), GEOCODE_GRID)}"
    with _geocode_lock:
        cache = _load_geocode_cache()
        if key in cache:
            hit = dict(cache[key])
            hit['success'] = True
            hit['cached'] = True
            return hit

    url = 'https://api.bigdatacloud.net/data/reverse-geocode-client'
    params = {
        'latitude': round(float(latitude), 6),
        'longitude': round(float(longitude), 6),
        'localityLanguage': 'zh',
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
    except Exception as e:
        return {'success': False, 'error': f'逆地理编码服务连接失败：{str(e)}（可稍后重试）'}

    if resp.status_code != 200:
        return {'success': False,
                'error': f'逆地理编码服务返回 {resp.status_code}：{resp.text[:200]}'}

    d = resp.json() or {}
    country = (d.get('countryName') or '').strip()
    province = (d.get('principalSubdivision') or '').strip()
    city = (d.get('city') or '').strip()
    district = (d.get('locality') or '').strip()

    # 直辖市等场景 city 常为空，回退到省级
    if not city:
        city = province
    # 组装可读名称（国 → 省 → 市 → 区，去重去空）
    parts, seen = [], set()
    for p in (country, province, city, district):
        if p and p not in seen and not (seen and parts and p in parts[-1]):
            parts.append(p)
            seen.add(p)
    display = ' · '.join(parts)

    if not province:
        # 海洋/荒漠/境外无人区等无行政区划
        result = {
            'success': True,
            'country': country,
            'province': '',
            'city': '',
            'district': '',
            'display': country or '该位置无行政区划信息（可能位于海洋或无人区）',
            'latitude': latitude,
            'longitude': longitude,
        }
    else:
        result = {
            'success': True,
            'country': country,
            'province': province,
            'city': city,
            'district': district,
            'display': display,
            'latitude': latitude,
            'longitude': longitude,
        }

    with _geocode_lock:
        cache = _load_geocode_cache()
        cache.setdefault(key, {k: v for k, v in result.items() if k not in ('success', 'cached')})
        try:
            _save_geocode_cache(cache)
        except Exception:
            pass

    result['cached'] = False
    return result


