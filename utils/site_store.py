"""
用户电站配置 + 真实发电数据存储（SQLite: data/pv_system.db）
==========================================================

site_config       用户自定义电站（经纬度/倾角/方位角/装机容量/损耗/隐私/电价）
user_generation   用户上传的真实逐小时发电功率（kW）

权限约定：
- 写操作仅所有者（user_id 匹配）
- visibility=private（默认）：他人不可见
- visibility=public（旧值 shared 等价）：登录用户可只读
- visibility=custom：仅 site_shares 中指定用户可只读
"""
from __future__ import annotations

import os
import sqlite3
import datetime as dt
from typing import List, Optional

import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_DB = os.path.join(_PROJECT_ROOT, 'data', 'pv_system.db')


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(SITE_DB), exist_ok=True)
    c = sqlite3.connect(SITE_DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_site_db():
    """幂等建表 + 存量列迁移。"""
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS site_config (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL,
                name      TEXT NOT NULL,
                lat       REAL NOT NULL,
                lon       REAL NOT NULL,
                tilt      REAL NOT NULL,
                azimuth   REAL NOT NULL DEFAULT 0,
                kwp       REAL NOT NULL DEFAULT 1,
                loss_pct  REAL NOT NULL DEFAULT 14,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_generation (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL,
                ts          TEXT NOT NULL,
                power_kw    REAL NOT NULL,
                uploaded_at TEXT NOT NULL,
                UNIQUE(site_id, ts),
                FOREIGN KEY(site_id) REFERENCES site_config(id) ON DELETE CASCADE
            )
        """)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_gen_site_ts ON user_generation(site_id, ts)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS site_shares (
                site_id          INTEGER NOT NULL,
                shared_with_user INTEGER NOT NULL,
                created_at       TEXT NOT NULL,
                PRIMARY KEY (site_id, shared_with_user),
                FOREIGN KEY(site_id) REFERENCES site_config(id) ON DELETE CASCADE
            )
        """)
        _migrate_site_config(c)


def _migrate_site_config(c: sqlite3.Connection):
    cols = {r[1] for r in c.execute("PRAGMA table_info(site_config)")}
    migrations = [
        ("visibility", "TEXT NOT NULL DEFAULT 'private'"),
        ("price_sharp", "REAL"),
        ("price_peak", "REAL"),
        ("price_flat", "REAL"),
        ("price_valley", "REAL"),
        ("price_feed_in", "REAL"),
    ]
    for name, ddl in migrations:
        if name not in cols:
            c.execute(f"ALTER TABLE site_config ADD COLUMN {name} {ddl}")
    # 旧版 shared = 公共网络分享 → 统一为 public
    c.execute(
        "UPDATE site_config SET visibility='public' WHERE visibility='shared'")


def _normalize_visibility(v: str) -> str:
    s = str(v or 'private').lower()
    if s in ('shared', 'public', 'network'):
        return 'public'
    if s in ('custom', 'users', 'specific'):
        return 'custom'
    return 'private'


def _share_user_ids(c: sqlite3.Connection, site_id: int) -> List[int]:
    rows = c.execute(
        "SELECT shared_with_user FROM site_shares WHERE site_id=?",
        (int(site_id),)).fetchall()
    return [int(r[0]) for r in rows]


def set_share_targets(site_id: int, user_id: int,
                      share_user_ids: Optional[List[int]] = None) -> Optional[dict]:
    """仅所有者：设置 custom 分享目标用户 id 列表（空列表等价取消指定分享）。"""
    init_site_db()
    with _conn() as c:
        owner = c.execute(
            "SELECT id FROM site_config WHERE id=? AND user_id=?",
            (int(site_id), int(user_id))).fetchone()
        if not owner:
            return None
        c.execute("DELETE FROM site_shares WHERE site_id=?", (int(site_id),))
        now = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        seen = set()
        for uid in (share_user_ids or []):
            try:
                uid = int(uid)
            except (TypeError, ValueError):
                continue
            if uid == int(user_id) or uid in seen:
                continue
            seen.add(uid)
            c.execute(
                "INSERT OR IGNORE INTO site_shares(site_id, shared_with_user, created_at) VALUES (?,?,?)",
                (int(site_id), uid, now))
    return get_site(site_id, user_id)


# ── site_config CRUD ────────────────────────────────────────────────────────

def _row_to_dict(r: sqlite3.Row) -> dict:
    keys = set(r.keys())
    return {
        'id': r['id'],
        'user_id': r['user_id'],
        'name': r['name'],
        'lat': r['lat'],
        'lon': r['lon'],
        'tilt': r['tilt'],
        'azimuth': r['azimuth'],
        'kwp': r['kwp'],
        'loss_pct': r['loss_pct'],
        'created_at': r['created_at'],
        'visibility': _normalize_visibility(
            r['visibility'] if 'visibility' in keys else 'private'),
        'prices': {
            'sharp': r['price_sharp'] if 'price_sharp' in keys else None,
            'peak': r['price_peak'] if 'price_peak' in keys else None,
            'flat': r['price_flat'] if 'price_flat' in keys else None,
            'valley': r['price_valley'] if 'price_valley' in keys else None,
            'feed_in': r['price_feed_in'] if 'price_feed_in' in keys else None,
        },
    }


def create_site(user_id: int, name: str, lat: float, lon: float,
                tilt: Optional[float] = None, azimuth: float = 0.0,
                kwp: float = 1.0, loss_pct: float = 14.0,
                visibility: str = 'private',
                prices: Optional[dict] = None,
                share_user_ids: Optional[List[int]] = None) -> dict:
    init_site_db()
    if tilt is None:
        tilt = round(abs(float(lat)), 1)
    vis = _normalize_visibility(visibility)
    now = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    p = prices or {}

    def _pk(key):
        v = p.get(key)
        return float(v) if v is not None else None

    with _conn() as c:
        cur = c.execute("""
            INSERT INTO site_config(
                user_id, name, lat, lon, tilt, azimuth, kwp, loss_pct, created_at,
                visibility, price_sharp, price_peak, price_flat, price_valley, price_feed_in
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (int(user_id), name, float(lat), float(lon), float(tilt),
              float(azimuth), float(kwp), float(loss_pct), now, vis,
              _pk('sharp'), _pk('peak'), _pk('flat'), _pk('valley'), _pk('feed_in')))
        site_id = cur.lastrowid
    if vis == 'custom':
        set_share_targets(site_id, user_id, share_user_ids or [])
    return get_site(site_id, user_id)


def list_sites(user_id: int, include_shared: bool = False) -> List[dict]:
    """本人电站；include_shared=True 时附带他人 public / 指定给我的 custom 站点（只读）。"""
    init_site_db()
    uid = int(user_id)
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM site_config WHERE user_id=? ORDER BY id DESC",
            (uid,)).fetchall()
        shared: List[sqlite3.Row] = []
        if include_shared:
            shared = c.execute("""
                SELECT * FROM site_config
                WHERE user_id != ?
                  AND (
                    visibility IN ('public', 'shared')
                    OR (
                      visibility = 'custom'
                      AND EXISTS (
                        SELECT 1 FROM site_shares ss
                        WHERE ss.site_id = site_config.id
                          AND ss.shared_with_user = ?
                      )
                    )
                  )
                ORDER BY id DESC
            """, (uid, uid)).fetchall()
        result = []
        for r in list(rows) + list(shared):
            d = _row_to_dict(r)
            d['is_owner'] = d['user_id'] == uid
            d['read_only'] = not d['is_owner']
            if d['is_owner'] and d['visibility'] == 'custom':
                d['share_user_ids'] = _share_user_ids(c, d['id'])
            result.append(d)
    return result


def get_site(site_id: int, user_id: Optional[int] = None) -> Optional[dict]:
    """按归属读；user_id=None 时不限制（内部任务用）。写操作请用本函数。"""
    init_site_db()
    with _conn() as c:
        if user_id is None:
            r = c.execute("SELECT * FROM site_config WHERE id=?",
                          (int(site_id),)).fetchone()
        else:
            r = c.execute("SELECT * FROM site_config WHERE id=? AND user_id=?",
                          (int(site_id), int(user_id))).fetchone()
    return _row_to_dict(r) if r else None


def get_site_readable(site_id: int, user_id: int) -> Optional[dict]:
    """本人站点，或 public / 指定分享给我的 custom 站点（只读分析用）。"""
    site = get_site(site_id, user_id)
    if site:
        site['is_owner'] = True
        site['read_only'] = False
        if site.get('visibility') == 'custom':
            with _conn() as c:
                site['share_user_ids'] = _share_user_ids(c, site_id)
        return site
    init_site_db()
    with _conn() as c:
        r = c.execute(
            """
            SELECT * FROM site_config
            WHERE id = ?
              AND (
                visibility IN ('public', 'shared')
                OR (
                  visibility = 'custom'
                  AND EXISTS (
                    SELECT 1 FROM site_shares ss
                    WHERE ss.site_id = site_config.id
                      AND ss.shared_with_user = ?
                  )
                )
              )
            """,
            (int(site_id), int(user_id))).fetchone()
    if not r:
        return None
    d = _row_to_dict(r)
    d['is_owner'] = False
    d['read_only'] = True
    return d


def set_visibility(site_id: int, user_id: int, visibility: str,
                   share_user_ids: Optional[List[int]] = None) -> Optional[dict]:
    """仅所有者可切换 private / public / custom（custom 时同步 share_user_ids）。"""
    vis = _normalize_visibility(visibility)
    init_site_db()
    with _conn() as c:
        cur = c.execute(
            "UPDATE site_config SET visibility=? WHERE id=? AND user_id=?",
            (vis, int(site_id), int(user_id)))
        if cur.rowcount == 0:
            return None
        if vis != 'custom':
            c.execute("DELETE FROM site_shares WHERE site_id=?", (int(site_id),))
    if vis == 'custom':
        set_share_targets(site_id, user_id, share_user_ids or [])
    return get_site(site_id, user_id)


def update_site(site_id: int, user_id: int, **fields) -> Optional[dict]:
    """仅所有者可改；允许基础字段 + 自定义电价（prices dict 或 price_*）。"""
    allowed = {'name', 'lat', 'lon', 'tilt', 'azimuth', 'kwp', 'loss_pct',
               'price_sharp', 'price_peak', 'price_flat', 'price_valley', 'price_feed_in'}
    sets, vals = [], []
    prices = fields.pop('prices', None)
    if isinstance(prices, dict):
        for src, col in (('sharp', 'price_sharp'), ('peak', 'price_peak'),
                         ('flat', 'price_flat'), ('valley', 'price_valley'),
                         ('feed_in', 'price_feed_in')):
            if src in prices and prices[src] is not None:
                fields[col] = float(prices[src])
    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        if k == 'name':
            sets.append("name=?")
            vals.append(str(v))
        else:
            sets.append(f"{k}=?")
            vals.append(float(v))
    if not sets:
        return get_site(site_id, user_id)
    vals += [int(site_id), int(user_id)]
    with _conn() as c:
        cur = c.execute(
            f"UPDATE site_config SET {', '.join(sets)} WHERE id=? AND user_id=?", vals)
        if cur.rowcount == 0:
            return None
    return get_site(site_id, user_id)


def delete_site(site_id: int, user_id: int) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM site_config WHERE id=? AND user_id=?",
                        (int(site_id), int(user_id)))
        return cur.rowcount > 0


# ── user_generation ─────────────────────────────────────────────────────────

def upsert_generation(site_id: int, df: pd.DataFrame) -> int:
    """
    写入真实发电记录（INSERT OR REPLACE）。
    df 需含列 [ts(可转 Timestamp), power_kw]。
    """
    if df is None or df.empty:
        return 0
    init_site_db()
    now = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    rows = [
        (int(site_id), pd.Timestamp(r['ts']).strftime('%Y-%m-%d %H:%M:%S'),
         float(r['power_kw']), now)
        for _, r in df.iterrows()
        if pd.notna(r['power_kw'])
    ]
    if not rows:
        return 0
    with _conn() as c:
        c.executemany("""
            INSERT OR REPLACE INTO user_generation(site_id, ts, power_kw, uploaded_at)
            VALUES (?,?,?,?)
        """, rows)
    return len(rows)


def get_generation(site_id: int, start: Optional[str] = None,
                   end: Optional[str] = None) -> pd.DataFrame:
    """读取站点真实发电，返回 [ts(Timestamp), power_kw]。"""
    init_site_db()
    sql = "SELECT ts, power_kw FROM user_generation WHERE site_id=?"
    vals: list = [int(site_id)]
    if start:
        sql += " AND ts >= ?"
        vals.append(str(start)[:10])
    if end:
        sql += " AND ts < ?"  # end 按日期排他
        vals.append(
            (pd.Timestamp(str(end)[:10]) + pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
    sql += " ORDER BY ts"
    with _conn() as c:
        rows = c.execute(sql, vals).fetchall()
    if not rows:
        return pd.DataFrame(columns=['ts', 'power_kw'])
    df = pd.DataFrame([dict(r) for r in rows])
    df['ts'] = pd.to_datetime(df['ts'])
    return df


def generation_range(site_id: int) -> Optional[tuple]:
    """(最早时间, 最晚时间, 行数)。"""
    init_site_db()
    with _conn() as c:
        r = c.execute(
            "SELECT MIN(ts), MAX(ts), COUNT(*) FROM user_generation WHERE site_id=?",
            (int(site_id),)).fetchone()
    if not r or r[0] is None:
        return None
    return r[0], r[1], int(r[2])
