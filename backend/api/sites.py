"""
用户电站配置 API（/api/sites）
=============================

- 电站 CRUD（按登录用户隔离）
- 历史气象回填后台任务（NASA POWER，默认近 5 年，写入本地缓存）
"""
from __future__ import annotations

import sys
import os
import time
import uuid
import threading
import datetime as dt

from fastapi import APIRouter, HTTPException, Cookie, Header
from pydantic import BaseModel
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import site_store
from backend.api.auth import SECRET_KEY, ALGORITHM
import jwt

router = APIRouter()


def _require_user(access_token: Optional[str],
                  authorization: Optional[str]) -> dict:
    # 优先 Cookie；其次 Authorization: Bearer <token>（前端 axios 实际使用方式）
    token = access_token
    if not token and authorization and authorization.startswith('Bearer '):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail='未登录')
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {'id': int(payload.get('sub')), 'username': payload.get('username')}
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail='登录凭证无效')


# ── 请求模型 ─────────────────────────────────────────────────────────────────

class SiteCreate(BaseModel):
    name: str
    lat: float
    lon: float
    tilt: Optional[float] = None     # 不传则默认 ≈ 纬度
    azimuth: float = 0.0             # 0=正南
    kwp: float = 1.0
    loss_pct: float = 14.0
    visibility: Optional[str] = 'private'  # private | public | custom（legacy: shared→public）
    share_user_ids: Optional[list] = None   # visibility=custom 时的目标用户
    prices: Optional[dict] = None    # {sharp,peak,flat,valley,feed_in}


class SiteUpdate(BaseModel):
    name: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    tilt: Optional[float] = None
    azimuth: Optional[float] = None
    kwp: Optional[float] = None
    loss_pct: Optional[float] = None
    prices: Optional[dict] = None


class VisibilityUpdate(BaseModel):
    visibility: str  # private | public | custom（legacy shared → public）
    share_user_ids: Optional[list] = None  # custom 时的目标用户 id 列表


# ── CRUD ────────────────────────────────────────────────────────────────────

@router.post('')
def create_site(body: SiteCreate, access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)):
    user = _require_user(access_token, authorization)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail='电站名称不能为空')
    if not (-90 <= body.lat <= 90 and -180 <= body.lon <= 180):
        raise HTTPException(status_code=400, detail='经纬度超出范围')
    if body.kwp <= 0:
        raise HTTPException(status_code=400, detail='装机容量必须大于 0')
    site = site_store.create_site(
        user['id'], body.name.strip(), body.lat, body.lon,
        tilt=body.tilt, azimuth=body.azimuth, kwp=body.kwp, loss_pct=body.loss_pct,
        visibility=body.visibility or 'private', prices=body.prices,
        share_user_ids=body.share_user_ids)
    return {'success': True, 'site': site}


@router.get('/shareable-users')
def list_shareable_users(access_token: Optional[str] = Cookie(None),
                         authorization: Optional[str] = Header(None)):
    """可选分享对象：全部活跃用户（仅 id/username，不含邮箱等敏感字段）。"""
    user = _require_user(access_token, authorization)
    from utils.news_database import PVSystemDatabase
    db = PVSystemDatabase()
    df = db.get_all_users()
    users = []
    if df is not None and len(df):
        for _, r in df.iterrows():
            uid = int(r.get('id') or 0)
            if uid == int(user['id']):
                continue
            if int(r.get('is_active') or 1) != 1:
                continue
            users.append({'id': uid, 'username': str(r.get('username') or '')})
    users.sort(key=lambda u: u['username'])
    return {'success': True, 'users': users}


@router.get('/{site_id}/shares')
def get_site_shares(site_id: int, access_token: Optional[str] = Cookie(None),
                    authorization: Optional[str] = Header(None)):
    """仅所有者：查看 custom 分享目标用户。"""
    user = _require_user(access_token, authorization)
    site = site_store.get_site(site_id, user['id'])
    if not site:
        raise HTTPException(status_code=404, detail='电站不存在或无权访问')
    ids = site.get('share_user_ids') or []
    if site.get('visibility') != 'custom':
        ids = []
    names = []
    if ids:
        from utils.news_database import PVSystemDatabase
        db = PVSystemDatabase()
        for uid in ids:
            u = db.get_user(uid) or {}
            names.append({'id': int(uid), 'username': u.get('username') or f'user_{uid}'})
    return {'success': True, 'visibility': site.get('visibility'),
            'share_user_ids': ids, 'users': names}


@router.get('')
def list_sites(include_shared: int = 0,
               access_token: Optional[str] = Cookie(None),
               authorization: Optional[str] = Header(None)):
    user = _require_user(access_token, authorization)
    sites = site_store.list_sites(user['id'], include_shared=bool(include_shared))
    # 附带真实数据覆盖情况
    for s in sites:
        rng = site_store.generation_range(s['id'])
        s['has_data'] = rng is not None
        if rng:
            s['data_range'] = {'start': rng[0], 'end': rng[1], 'rows': rng[2]}
    return {'success': True, 'sites': sites}


@router.put('/{site_id}/visibility')
def update_visibility(site_id: int, body: VisibilityUpdate,
                      access_token: Optional[str] = Cookie(None),
                      authorization: Optional[str] = Header(None)):
    """仅所有者：private / public（公共网络）/ custom（指定用户）。"""
    user = _require_user(access_token, authorization)
    raw = str(body.visibility or 'private').lower()
    if raw in ('private',):
        vis = 'private'
    elif raw in ('public', 'shared', 'network'):
        vis = 'public'
    elif raw in ('custom', 'users', 'specific'):
        vis = 'custom'
    else:
        raise HTTPException(status_code=400, detail='visibility 须为 private | public | custom')
    share_ids = body.share_user_ids or []
    if vis == 'custom' and not share_ids:
        raise HTTPException(status_code=400, detail='指定用户分享至少需要 1 个目标用户')
    site = site_store.set_visibility(site_id, user['id'], vis, share_user_ids=share_ids)
    if not site:
        raise HTTPException(status_code=404, detail='电站不存在或无权访问')
    if vis == 'custom':
        site = site_store.get_site(site_id, user['id'])
        site['share_user_ids'] = share_ids
    return {'success': True, 'site': site}


@router.put('/{site_id}')
def update_site(site_id: int, body: SiteUpdate, access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)):
    user = _require_user(access_token, authorization)
    fields = body.model_dump(exclude_none=True)
    site = site_store.update_site(site_id, user['id'], **fields)
    if not site:
        raise HTTPException(status_code=404, detail='电站不存在或无权访问')
    return {'success': True, 'site': site}


# ── 历史气象回填（后台任务）──────────────────────────────────────────────────

_backfill_jobs: dict = {}
_backfill_lock = threading.Lock()


def _run_backfill(job_id: str, site_id: int, years: int):
    from utils.weather.nasa_power import fetch_nasa_power
    from utils.weather import store as wstore

    with _backfill_lock:
        _backfill_jobs[job_id]['status'] = 'running'
        _backfill_jobs[job_id]['message'] = f'准备回填近 {years} 年气象...'

    try:
        site = site_store.get_site(site_id)
        if not site:
            raise RuntimeError('电站不存在')

        # NASA POWER hourly 历史约滞后数日，结束到昨天
        end_date = dt.date.today() - dt.timedelta(days=2)
        start_date = dt.date(end_date.year - years, 1, 1)
        segments = []
        cur = start_date
        while cur <= end_date:
            seg_end = min(dt.date(cur.year, 12, 31), end_date)
            segments.append((cur, seg_end))
            cur = seg_end + dt.timedelta(days=1)

        total_rows = 0
        for i, (s, e) in enumerate(segments):
            with _backfill_lock:
                _backfill_jobs[job_id].update({
                    'progress': round((i / len(segments)) * 100, 1),
                    'message': f'正在拉取 {s.year} 年（{i+1}/{len(segments)}）',
                })
            df = fetch_nasa_power(site['lat'], site['lon'], s, e)
            total_rows += wstore.upsert(df, site['lat'], site['lon'])

        rng = wstore.covered_range(site['lat'], site['lon'])
        with _backfill_lock:
            _backfill_jobs[job_id].update({
                'status': 'done', 'progress': 100,
                'message': f'回填完成，缓存共 {rng[2] if rng else 0} 行',
                'result': {'rows': rng[2] if rng else 0,
                           'start': str(rng[0]) if rng else None,
                           'end': str(rng[1]) if rng else None},
            })
    except Exception as e:
        with _backfill_lock:
            _backfill_jobs[job_id].update({'status': 'failed', 'error': str(e)})


@router.post('/{site_id}/backfill')
def start_backfill(site_id: int, years: int = 5, access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)):
    user = _require_user(access_token, authorization)
    site = site_store.get_site(site_id, user['id'])
    if not site:
        raise HTTPException(status_code=404, detail='电站不存在或无权访问')
    years = max(1, min(int(years), 10))

    with _backfill_lock:
        for j in _backfill_jobs.values():
            if j.get('site_id') == site_id and j.get('status') == 'running':
                return {'success': False, 'error': '该电站气象正在回填中'}
        job_id = str(uuid.uuid4())
        _backfill_jobs[job_id] = {
            'job_id': job_id, 'site_id': site_id, 'status': 'pending',
            'progress': 0.0, 'message': '任务已创建', 'error': None,
        }
    threading.Thread(target=_run_backfill, args=(job_id, site_id, years),
                     daemon=True).start()
    return {'success': True, 'job_id': job_id}


@router.get('/backfill/progress/{job_id}')
def backfill_progress(job_id: str, access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)):
    _require_user(access_token, authorization)
    with _backfill_lock:
        job = _backfill_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail='任务不存在')
        return {'success': True, **job}
