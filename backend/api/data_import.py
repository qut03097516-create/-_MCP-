"""
用户真实发电数据导入 API（/api/data-import）
===========================================

- POST   /upload             上传 CSV/XLSX（≤20MB、≤20万行），自动字段映射+清洗+入库
- GET    /template           下载 CSV 模板
- GET    /generation/{id}    查看站点数据覆盖与样本
- DELETE /generation/{id}    清空站点已上传数据

只要求两列：时间戳、发电功率（kW，W 可自动识别换算）。
时间统一规范为北京时间整点；非整点按小时聚合（均值）；重复时间戳取均值。
"""
from __future__ import annotations

import sys
import io
import os
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Cookie, Header, UploadFile, File, Form
from fastapi.responses import StreamingResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import site_store
from backend.api.sites import _require_user

router = APIRouter()

MAX_FILE_MB = 20
MAX_ROWS = 200_000

_TIME_KEYS = ['datatime', 'timestamp', '时间', '日期时间', '日期', 'time', 'date', 'datetime']
_POWER_KEYS = ['power', '功率', '有功功率', 'activepower', 'p(kw)', '发电功率', 'pkw',
               'p_ac', 'pac', 'p_dc', 'pdc', 'pm', 'production', 'p']


def _fuzzy_col(columns, keys):
    for c in columns:
        lc = str(c).lower().replace(' ', '').replace('_', '').replace('-', '').replace(':', '')
        if any(k in lc for k in keys):
            return c
    return None


def _find_power_col(columns, time_col):
    """功率列模糊匹配：排除时间列与温度列，先强关键词后弱关键词（p）。"""
    strong = ['power', '功率', '有功', 'activepower', 'p(kw)', '发电', 'pkw',
              'p_ac', 'pac', 'p_dc', 'pdc', 'production']
    weak = ['p', 'pm']
    candidates = [c for c in columns if c != time_col and 'temp' not in str(c).lower()
                  and '温度' not in str(c) and not str(c).lower().startswith('h(')
                  and 'g(i)' not in str(c).lower()]
    hit = _fuzzy_col(candidates, strong)
    if hit:
        return hit
    # 弱匹配仅在归一化后恰好等于 p / kw 结尾时接受，避免误匹配
    for c in candidates:
        lc = str(c).lower().strip().replace(' ', '').replace('_', '')
        if lc in ('p', 'kw', 'p_kw', 'p(kw)', '功率kw', 'pm'):
            return c
    return None


def _decode_text(raw: bytes) -> str:
    for enc in ('utf-8-sig', 'utf-8', 'gb18030', 'gbk'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def _looks_like_header(line: str, next_data_line: str = '') -> bool:
    """
    识别真实表头：跳过 PVGIS 元数据（`Latitude…:` + 数值这类键值对）。
    要求含分隔符、有时间列名；若有下一行，其首列应像时间值。
    """
    s = line.strip()
    if not s or s.startswith('#') or s.startswith('-**-'):
        return False
    if not any(d in s for d in (',', ';', '\t')):
        return False
    fields = _split_fields(s)
    if not fields or len(fields) < 2:
        return False
    # 元数据键值：首字段以冒号结尾
    if fields[0].endswith(':'):
        return False
    if not any(_is_time_header_name(f) for f in fields):
        return False
    # 不能整行都像纯数据值
    if all(_looks_like_time_value(f) or _is_number(f) for f in fields[:2]):
        return False
    if next_data_line.strip():
        nf = _split_fields(next_data_line)
        if nf and not _looks_like_time_value(nf[0]):
            return False
    return True


def _split_fields(line: str) -> list[str]:
    s = line.strip()
    if '\t' in s and s.count('\t') >= max(s.count(','), s.count(';')):
        return [p.strip().strip('"').strip("'") for p in s.split('\t')]
    if ';' in s and s.count(';') >= s.count(','):
        return [p.strip().strip('"').strip("'") for p in s.split(';')]
    return [p.strip().strip('"').strip("'") for p in s.split(',')]


def _is_number(s: str) -> bool:
    try:
        float(str(s).strip())
        return True
    except (TypeError, ValueError):
        return False


def _is_time_header_name(name: str) -> bool:
    raw = str(name).strip()
    lc = raw.lower().replace(' ', '').replace('_', '')
    if lc in (
        'time', 'date', 'datetime', 'timestamp', 'datetimeindex',
        'date/time', 'datatime', '时间', '日期时间', '日期', '时间戳',
    ):
        return True
    if lc.startswith('date') or lc.startswith('time'):
        return True
    if '时间' in raw or '日期时间' in raw:
        return True
    return False


def _looks_like_time_value(sample: str) -> bool:
    import re

    s = str(sample).strip().strip('"').strip("'")
    if not s or s.lower() in ('nan', 'none', 'nat'):
        return False
    # PVGIS: 20050101:0030（YYYYMMDD:HHMM）
    if re.match(r'^\d{8}:\d{4}$', s):
        return True
    # 20050101:00:30 / 20050101T00:30:00 / 200501010030
    if re.match(r'^\d{8}[:\-T]?\d{2}(:\d{2}){0,2}$', s):
        return True
    if re.match(r'^\d{8}\d{2}(:\d{2}){0,2}$', s):
        return True
    if re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}([ T]\d{1,2}:\d{2})?', s):
        return True
    if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', s):
        return True
    try:
        pd.Timestamp(s)
        return True
    except (ValueError, TypeError):
        return False


def _find_header_idx(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        nxt = ''
        for j in range(i + 1, min(i + 6, len(lines))):
            if lines[j].strip():
                nxt = lines[j]
                break
        if _looks_like_header(line, nxt):
            return i
    # 兜底：跳过元数据后，第一行含分隔符且字段数 ≥ 2 的
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith('#') or s.startswith('-**-'):
            continue
        fields = _split_fields(s)
        if fields and fields[0].endswith(':'):
            continue
        if len(fields) >= 2 and any(d in s for d in (',', ';', '\t')):
            return i
    return 0


def _detect_sep(header_line: str) -> str:
    counts = {
        '\t': header_line.count('\t'),
        ';': header_line.count(';'),
        ',': header_line.count(','),
    }
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] > 0 else ','


def _read_csv_bytes(raw: bytes) -> pd.DataFrame:
    """
    容错读 CSV：
    - 跳过文件头元数据（如 PVGIS 的 -**- 文档注释），避免 C 引擎
      “Expected 1 fields in line N, saw M”
    - 按表头行嗅探分隔符（逗号/分号/制表符）
    """
    text = _decode_text(raw)
    lines = text.splitlines()
    if not any(ln.strip() for ln in lines):
        raise ValueError('CSV 内容为空')

    header_idx = _find_header_idx(lines)
    body = '\n'.join(lines[header_idx:])
    header_line = lines[header_idx]
    # 表头行内出现的分隔符按优先级尝试
    candidates: list[str] = []
    for sep in (_detect_sep(header_line), ',', '\t', ';'):
        if sep not in candidates:
            candidates.append(sep)

    last_err: Exception | None = None
    for sep in candidates:
        try:
            df = pd.read_csv(io.StringIO(body), sep=sep, engine='python')
        except Exception as e:  # noqa: BLE001 — 逐个分隔符回退
            last_err = e
            continue
        if df.shape[1] >= 2:
            df.columns = [str(c).strip().strip('"').strip("'") for c in df.columns]
            # 丢掉仍混入的元数据残留（首列键名以冒号结尾）
            first = df.iloc[:, 0].astype(str).str.strip()
            df = df[~first.str.endswith(':')]
            if len(df):
                return df
            last_err = ValueError('表头后无有效数据行')
            continue
        # 单列可能是分隔符猜错，继续试
        last_err = ValueError(f'按 sep={sep!r} 只解析出 1 列')

    # 最后交给 pandas 空 sep 嗅探
    try:
        df = pd.read_csv(io.StringIO(body), sep=None, engine='python', on_bad_lines='skip')
        if df.shape[1] >= 1:
            df.columns = [str(c).strip().strip('"').strip("'") for c in df.columns]
            return df
    except Exception as e:  # noqa: BLE001
        last_err = e

    raise RuntimeError(str(last_err) if last_err else '无法识别 CSV 结构')


def _parse_times(s: pd.Series) -> pd.Series:
    """尽量宽松地解析时间；支持 PVGIS `YYYYMMDD:HHMM`；无时区按北京时间。"""
    idx = pd.Series(s).index
    raw = (
        pd.Series(s)
        .astype(str)
        .str.strip()
        .str.strip('"')
        .str.strip("'")
        .replace({'': pd.NA, 'nan': pd.NA, 'None': pd.NA, 'NaT': pd.NA})
    )
    non_empty = raw.dropna()
    if len(non_empty) and non_empty.str.match(r'^\d{8}:\d{4}$').mean() > 0.5:
        ts = pd.to_datetime(raw, format='%Y%m%d:%H%M', errors='coerce')
    else:
        ts = pd.to_datetime(raw, errors='coerce', format='mixed')
        need = ts.isna() & raw.notna()
        if bool(need.any()):
            for fmt in (
                '%Y%m%d:%H%M',
                '%Y%m%d%H%M',
                '%Y-%m-%d %H:%M:%S',
                '%Y/%m/%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%d %H:%M',
                '%Y/%m/%d %H:%M',
            ):
                alt = pd.to_datetime(raw[need], format=fmt, errors='coerce')
                ts = ts.copy()
                ts.loc[need] = alt
                need = ts.isna() & raw.notna()
                if not bool(need.any()):
                    break

    ts = pd.Series(ts, index=idx)
    if getattr(ts.dt, 'tz', None) is not None:
        ts = ts.dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    return ts


@router.post('/upload')
async def upload_generation(
    site_id: int = Form(...),
    power_unit: str = Form('auto'),          # auto / kw / w
    file: UploadFile = File(...),
    access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    user = _require_user(access_token, authorization)
    site = site_store.get_site(site_id, user['id'])
    if not site:
        raise HTTPException(status_code=404, detail='电站不存在或无权访问')

    fname = file.filename or ''
    ext = os.path.splitext(fname)[1].lower()
    if ext not in ('.csv', '.xlsx', '.xls'):
        return {'success': False, 'error': '仅支持 CSV / XLSX / XLSX 文件'}

    raw = await file.read()
    if len(raw) > MAX_FILE_MB * 1024 * 1024:
        return {'success': False, 'error': f'文件超过 {MAX_FILE_MB}MB 限制'}

    # 1. 读取（跳过 PVGIS 等文件头元数据，自动嗅探分隔符）
    try:
        if ext == '.csv':
            df = _read_csv_bytes(raw)
        else:
            df = pd.read_excel(io.BytesIO(raw))
    except Exception as e:
        return {'success': False, 'error': f'文件解析失败：{str(e)}'}

    if len(df) > MAX_ROWS:
        return {'success': False, 'error': f'数据超过 {MAX_ROWS:,} 行上限，请拆分后上传'}
    total_raw = len(df)
    if total_raw == 0:
        return {'success': False, 'error': '文件中没有数据行'}

    # 2. 字段映射
    time_col = _fuzzy_col(df.columns, _TIME_KEYS)
    power_col = _find_power_col(df.columns, time_col)
    if not time_col or not power_col:
        return {'success': False,
                'error': f'未能识别必要列（时间、功率）。实际列名：{list(df.columns)}，'
                         f'请确认包含时间戳列和发电功率列'}

    work = pd.DataFrame({'ts': df[time_col], 'power_kw': df[power_col]})
    work['ts'] = _parse_times(work['ts'])
    work['power_kw'] = pd.to_numeric(work['power_kw'], errors='coerce')

    bad_time = int(work['ts'].isna().sum())
    bad_power = int(work['power_kw'].isna().sum())
    work = work.dropna(subset=['ts']).copy()

    # 3. 单位识别（W → kW）
    unit_used = power_unit
    converted = False
    if power_unit == 'w':
        work['power_kw'] = work['power_kw'] / 1000.0
        converted = True
        unit_used = 'w→kw'
    elif power_unit == 'auto':
        # 用正值中位数/峰值判断 W：小装机（1kWp）W 数据中位数常在数百，
        # 旧阈值 max(kwp*100, 500) 会漏判，导致超容行全被丢掉。
        daytime = work['power_kw'][work['power_kw'] > 0]
        kwp = float(site['kwp']) or 1.0
        if len(daytime):
            med = float(daytime.median())
            peak = float(daytime.max())
            looks_like_w = (med > max(kwp * 10, 20)) or (peak > max(kwp * 100, 500))
            if looks_like_w:
                work['power_kw'] = work['power_kw'] / 1000.0
                converted = True
                unit_used = 'auto:w→kw'
            else:
                unit_used = 'auto:kw'
        else:
            unit_used = 'auto:kw'

    # 物理合理性：负值丢弃（发电功率不应为负），超装机 1.5 倍记为异常丢弃
    neg_count = int((work['power_kw'] < 0).sum())
    over_cap = int((work['power_kw'] > float(site['kwp']) * 1.5).sum())
    work.loc[work['power_kw'] < 0, 'power_kw'] = np.nan
    work.loc[work['power_kw'] > float(site['kwp']) * 1.5, 'power_kw'] = np.nan
    work = work.dropna(subset=['power_kw'])

    # 4. 规范到北京时间整点：非整点 floor 到小时后取均值
    work['hour_ts'] = work['ts'].dt.floor('h')
    grouped = work.groupby('hour_ts', as_index=False)['power_kw'].mean()
    grouped.columns = ['ts', 'power_kw']
    duplicate_merged = int(len(work) - len(grouped))

    # 时间合理性：不允许未来时间
    now = pd.Timestamp.now()
    future_count = int((grouped['ts'] > now).sum())
    grouped = grouped[grouped['ts'] <= now]

    if grouped.empty:
        return {'success': False, 'error': '清洗后无有效数据，请检查时间与功率列内容'}

    # 5. 入库（INSERT OR REPLACE）
    n_upserted = site_store.upsert_generation(site_id, grouped)
    rng = site_store.generation_range(site_id)

    # 6. 覆盖率报告（按应有整小时数）
    full_hours = int((grouped['ts'].max() - grouped['ts'].min()).total_seconds() // 3600) + 1
    coverage = round(len(grouped) / max(full_hours, 1) * 100, 1)
    sample = grouped.tail(5).assign(
        ts=lambda d: d['ts'].dt.strftime('%Y-%m-%d %H:%M:%S')).to_dict('records')

    return {
        'success': True,
        'file': fname,
        'mapped_columns': {'time': str(time_col), 'power': str(power_col)},
        'unit': unit_used,
        'report': {
            'raw_rows': total_raw,
            'invalid_time_rows': bad_time,
            'invalid_power_rows': bad_power,
            'negative_power_rows': neg_count,
            'over_capacity_rows': over_cap,
            'future_rows': future_count,
            'duplicate_or_subhourly_merged': duplicate_merged,
            'valid_hourly_rows': int(len(grouped)),
            'upserted_rows': n_upserted,
            'time_start': grouped['ts'].min().strftime('%Y-%m-%d %H:%M:%S'),
            'time_end': grouped['ts'].max().strftime('%Y-%m-%d %H:%M:%S'),
            'hourly_coverage_pct': coverage,
            'power_kw': {
                'min': round(float(grouped['power_kw'].min()), 3),
                'mean': round(float(grouped['power_kw'].mean()), 3),
                'max': round(float(grouped['power_kw'].max()), 3),
            },
        },
        'site_total': {'rows': rng[2], 'start': rng[0], 'end': rng[1]} if rng else None,
        'sample_tail': sample,
    }


@router.get('/template')
def download_template(access_token: Optional[str] = Cookie(None),
                      authorization: Optional[str] = Header(None)):
    _require_user(access_token, authorization)
    csv = ('时间,发电功率(kW)\n'
           '2024-06-01 06:00:00,0.02\n'
           '2024-06-01 07:00:00,0.35\n'
           '2024-06-01 08:00:00,1.21\n'
           '2024-06-01 12:00:00,4.52\n')
    return StreamingResponse(
        io.BytesIO('\ufeff'.encode('utf-8') + csv.encode('utf-8')),
        media_type='text/csv',
        headers={'Content-Disposition': 'attachment; filename=generation_template.csv'})


@router.get('/generation/{site_id}')
def generation_summary(site_id: int, access_token: Optional[str] = Cookie(None),
                       authorization: Optional[str] = Header(None)):
    user = _require_user(access_token, authorization)
    # 只读：本人或已分享站点
    site = site_store.get_site_readable(site_id, user['id'])
    if not site:
        raise HTTPException(status_code=404, detail='电站不存在或无权访问')
    rng = site_store.generation_range(site_id)
    if not rng:
        return {'success': True, 'has_data': False, 'rows': 0}
    df = site_store.get_generation(site_id)
    full_hours = int((df['ts'].max() - df['ts'].min()).total_seconds() // 3600) + 1
    monthly = (df.set_index('ts')['power_kw'].resample('ME').agg(['size', 'sum', 'max'])
               .reset_index())
    monthly_list = [
        {'month': r['ts'].strftime('%Y-%m'), 'hours': int(r['size']),
         'energy_kwh': round(float(r['sum']), 1), 'peak_kw': round(float(r['max']), 3)}
        for _, r in monthly.iterrows()]

    # 轻量数据诊断：零出力日、覆盖缺口、超容、骤降
    diagnosis: list = []
    try:
        cov = round(rng[2] / max(full_hours, 1) * 100, 1)
        if cov < 80:
            diagnosis.append({
                'level': 'warning',
                'code': 'coverage_gap',
                'title': '数据覆盖不足',
                'detail': f'小时覆盖率仅 {cov}%（{rng[2]}/{full_hours}），建议补传缺失时段',
            })
        kwp = float(site.get('kwp') or 0) or 1.0
        p = df['power_kw'].astype(float)
        over_n = int((p > kwp * 1.2).sum())
        if over_n:
            diagnosis.append({
                'level': 'error',
                'code': 'over_capacity',
                'title': '功率疑似超装机',
                'detail': f'{over_n} 条记录 > 1.2×{kwp}kWp，请检查单位（W/kW）',
            })
        df2 = df.copy()
        df2['date'] = pd.to_datetime(df2['ts']).dt.date
        daily = df2.groupby('date')['power_kw'].mean()
        zero_days = int((daily <= 0.001).sum())
        if zero_days:
            diagnosis.append({
                'level': 'warning',
                'code': 'zero_output',
                'title': '存在零出力日',
                'detail': f'{zero_days} 天日均功率≈0，可能停机、遮挡或漏传',
            })
        # 相邻日均骤降 > 70% 且前一日正常
        if len(daily) >= 3:
            drops = 0
            vals = list(daily.values)
            for i in range(1, len(vals)):
                prev, cur = float(vals[i - 1]), float(vals[i])
                if prev > 0.05 * kwp and cur < prev * 0.3:
                    drops += 1
            if drops:
                diagnosis.append({
                    'level': 'info',
                    'code': 'daily_drop',
                    'title': '日发电量骤降',
                    'detail': f'检测到 {drops} 次相邻日均功率下降超 70%，可结合天气/检修排查',
                })
    except Exception:
        pass

    return {
        'success': True, 'has_data': True,
        'rows': rng[2], 'start': rng[0], 'end': rng[1],
        'hourly_coverage_pct': round(rng[2] / max(full_hours, 1) * 100, 1),
        'monthly': monthly_list,
        'diagnosis': diagnosis,
        'sample_head': [{'ts': t.strftime('%Y-%m-%d %H:%M:%S'), 'power_kw': round(float(p), 3)}
                        for t, p in df.head(5)[['ts', 'power_kw']].itertuples(index=False)],
    }


@router.get('/generation/{site_id}/rows')
def generation_rows(site_id: int,
                    start_date: Optional[str] = None,
                    end_date: Optional[str] = None,
                    max_rows: int = 2000,
                    access_token: Optional[str] = Cookie(None),
                    authorization: Optional[str] = Header(None)):
    """站点发电时序行数据（数据集显示页用），列名对齐演示集：DATATIME / POWER。"""
    user = _require_user(access_token, authorization)
    site = site_store.get_site_readable(site_id, user['id'])
    if not site:
        raise HTTPException(status_code=404, detail='电站不存在或无权访问')
    df = site_store.get_generation(site_id, start_date, end_date)
    if df.empty:
        return {'success': True, 'data': [], 'columns': ['DATATIME', 'POWER']}
    # 超限降采样（等间隔抽行，保持时序形态）
    if len(df) > max_rows:
        df = df.iloc[::max(1, len(df) // max_rows)]
    data = [
        {'DATATIME': ts.strftime('%Y-%m-%d %H:%M:%S'), 'POWER': round(float(p), 4)}
        for ts, p in df[['ts', 'power_kw']].itertuples(index=False)
    ]
    return {'success': True, 'data': data, 'columns': ['DATATIME', 'POWER']}


@router.delete('/generation/{site_id}')
def clear_generation(site_id: int, access_token: Optional[str] = Cookie(None),
                     authorization: Optional[str] = Header(None)):
    user = _require_user(access_token, authorization)
    # 写操作：仅所有者
    site = site_store.get_site(site_id, user['id'])
    if not site:
        raise HTTPException(status_code=404, detail='电站不存在或无权访问')
    import sqlite3
    with site_store._conn() as c:
        cur = c.execute('DELETE FROM user_generation WHERE site_id=?', (int(site_id),))
        deleted = cur.rowcount
    return {'success': True, 'deleted_rows': int(deleted)}
