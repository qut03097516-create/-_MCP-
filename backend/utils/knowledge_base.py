"""
Obsidian 知识库核心模块
- vault 目录扫描（增量，基于内容 hash）
- Obsidian 方言解析：YAML frontmatter / [[wikilink]] / ![[embed]] / #tag / ==高亮==
- duckdb 存储（data/kb.duckdb）
- 全文关键词检索打分（中文滑窗短语，供 AI RAG 注入）
"""
import os
import re
import time
import hashlib
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
from typing import Dict, List, Optional, Tuple

import duckdb

_BASE = Path(__file__).resolve().parents[2]  # 项目根
VAULT_DIR = Path(os.environ.get('KB_VAULT_DIR', str(_BASE / 'data' / 'vault')))
KB_DB = _BASE / 'data' / 'kb.duckdb'

_MD_SUFFIX = '.md'

# ── 表结构 ──────────────────────────────────────────────
_DDL = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    path VARCHAR UNIQUE NOT NULL,
    title VARCHAR NOT NULL,
    folder VARCHAR,
    body_md TEXT,
    raw_frontmatter TEXT,
    tags VARCHAR[],
    out_links VARCHAR[],
    hash VARCHAR,
    mtime TIMESTAMP,
    size INTEGER,
    created_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title);
CREATE INDEX IF NOT EXISTS idx_notes_folder ON notes(folder);
"""


def _conn(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if read_only and not KB_DB.exists():
        KB_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(KB_DB), read_only=read_only)
    if not read_only:
        conn.execute(_DDL)
    return conn


# ── frontmatter 解析（无 pyyaml，覆盖 key: value / [a,b] / 块列表）──
_FM_RE = re.compile(r'\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?', re.DOTALL)
_KEY_RE = re.compile(r'^([A-Za-z_][\w\-]*)\s*:\s*(.*)$')


def parse_frontmatter(text: str) -> Tuple[dict, str, str]:
    """返回 (fm字典, 原始frontmatter文本, 正文)"""
    m = _FM_RE.match(text)
    if not m:
        return {}, '', text
    raw = m.group(1)
    body = text[m.end():]
    fm: dict = {}
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith('#'):
            i += 1
            continue
        km = _KEY_RE.match(line)
        if not km:
            i += 1
            continue
        key = km.group(1).lower()
        val = km.group(2).strip()
        if val == '':
            items = []
            j = i + 1
            while j < len(lines) and re.match(r'^\s+-\s+\S', lines[j]):
                items.append(lines[j].split('-', 1)[1].strip().strip('"\''))
                j += 1
            fm[key] = items if items else ''
            i = j if items else i + 1
            continue
        if val.startswith('[') and val.endswith(']'):
            inner = val[1:-1].strip()
            fm[key] = [x.strip().strip('"\'') for x in inner.split(',')] if inner else []
        else:
            fm[key] = val.strip('"\'')
        i += 1
    return fm, raw, body


# ── Obsidian 方言预处理 ──────────────────────────────────
_EMBED_RE = re.compile(r'!\[\[([^\]]+)\]\]')
_WIKI_RE = re.compile(r'(?<!!)\[\[([^\]]+)\]\]')
_TAG_RE = re.compile(r'(?<![\w#&/])#([\w\u4e00-\u9fff][\w\u4e00-\u9fff/\-]*)')
_HL_RE = re.compile(r'==([^=\n]{1,120})==')


def _norm_link_target(target: str) -> str:
    """[[目标]] → 规范化 slug（lower、去 .md、去 ./ 前缀）"""
    t = target.strip().replace('\\', '/').split('#')[0]
    if t.lower().endswith(_MD_SUFFIX):
        t = t[:-3]
    return t.strip('/').lower()


def parse_note(text: str, rel_path: str, file_index: Optional[Dict[str, str]] = None) -> dict:
    """解析单篇 .md → 结构化字段"""
    fm, raw_fm, body = parse_frontmatter(text)
    folder = str(Path(rel_path).parent.as_posix()) if str(Path(rel_path).parent) != '.' else ''

    def resolve_embed(name: str) -> str:
        name = name.split('|')[0].split('#')[0].strip()
        if not name:
            return ''
        # 同目录优先，其次全库索引
        if folder:
            cand = f'{folder}/{name}'
            if (VAULT_DIR / cand).exists():
                return cand
        if file_index:
            hit = file_index.get(name.lower())
            if hit:
                return hit
        if (VAULT_DIR / name).exists():
            return name
        return ''

    def embed_sub(m: re.Match) -> str:
        rel = resolve_embed(m.group(1))
        if rel:
            return f'![](/api/kb/attachment?path={quote(rel)})'
        label = m.group(1).split('|')[0].strip()
        return f'*[缺失附件: {label}]*'

    def wiki_sub(m: re.Match) -> str:
        inner = m.group(1)
        target, _, alias = inner.partition('|')
        anchor = ''
        if '#' in target:
            target, _, anchor = target.partition('#')
        slug = _norm_link_target(target)
        if not slug:
            label = alias.strip() or anchor.strip() or inner.strip()
            return label
        label = alias.strip()
        if not label:
            label = Path(target.strip()).stem or target.strip()
        if anchor.strip():
            label = f'{label} › {anchor.strip()}' if label and alias.strip() else (anchor.strip() or label)
        return f'[{label}](/kb/note/{quote(slug)})'

    body_md = _EMBED_RE.sub(embed_sub, body)
    body_md = _WIKI_RE.sub(wiki_sub, body_md)
    body_md = _HL_RE.sub(r'<mark>\1</mark>', body_md)

    # 标签：frontmatter 优先，正文 #tag 补充
    tags: List[str] = []
    ftags = fm.get('tags', [])
    if isinstance(ftags, list):
        tags.extend(str(t) for t in ftags)
    elif isinstance(ftags, str):
        tags.extend([t for t in re.split(r'[,，\s]+', ftags) if t])
    tags.extend(m.group(1) for m in _TAG_RE.finditer(body))
    tags = list(dict.fromkeys(t.lower().lstrip('#') for t in tags if t.strip()))

    # 出链
    links: List[str] = []
    for m in _WIKI_RE.finditer(body):
        t = m.group(1).partition('|')[0].split('#')[0].strip()
        if t:
            links.append(_norm_link_target(t))
    links = list(dict.fromkeys(links))

    title = str(fm.get('title', '')).strip() or Path(rel_path).stem
    return {
        'title': title,
        'folder': folder,
        'body_md': body_md,
        'raw_frontmatter': raw_fm,
        'tags': tags,
        'out_links': links,
    }


# ── 增量扫描 ────────────────────────────────────────────
def rescan() -> dict:
    """扫描 vault，增量更新索引。返回统计。"""
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    md_files: Dict[str, Path] = {}
    file_index: Dict[str, str] = {}
    attachments = 0
    for p in VAULT_DIR.rglob('*'):
        if not p.is_file():
            continue
        rel = p.relative_to(VAULT_DIR).as_posix()
        file_index.setdefault(p.name.lower(), rel)
        if p.suffix.lower() == _MD_SUFFIX:
            md_files[rel] = p
        else:
            attachments += 1

    conn = _conn()
    try:
        existing = {r[0]: (r[1], r[2]) for r in
                    conn.execute('SELECT path, id, hash FROM notes').fetchall()}
        added = updated = deleted = 0
        now = datetime.now()
        for rel, p in md_files.items():
            raw = p.read_bytes()
            h = hashlib.sha1(raw).hexdigest()
            if rel in existing and existing[rel][1] == h:
                continue
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                text = raw.decode('utf-8', 'ignore')
            note = parse_note(text, rel, file_index)
            st = p.stat()
            mtime = datetime.fromtimestamp(st.st_mtime)
            if rel in existing:
                conn.execute(
                    'UPDATE notes SET title=?, folder=?, body_md=?, raw_frontmatter=?, '
                    'tags=?, out_links=?, hash=?, mtime=?, size=? WHERE path=?',
                    [note['title'], note['folder'], note['body_md'], note['raw_frontmatter'],
                     note['tags'], note['out_links'], h, mtime, st.st_size, rel])
                updated += 1
            else:
                nid = conn.execute('SELECT COALESCE(MAX(id), 0) + 1 FROM notes').fetchone()[0]
                conn.execute(
                    'INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    [nid, rel, note['title'], note['folder'], note['body_md'],
                     note['raw_frontmatter'], note['tags'], note['out_links'],
                     h, mtime, st.st_size, now])
                added += 1
        gone = set(existing) - set(md_files)
        for g in gone:
            conn.execute('DELETE FROM notes WHERE path=?', [g])
            deleted += 1
        total = conn.execute('SELECT COUNT(*) FROM notes').fetchone()[0]
    finally:
        conn.close()
    return {'success': True, 'added': added, 'updated': updated, 'deleted': deleted,
            'total': total, 'attachments': attachments,
            'elapsed': round(time.time() - t0, 2)}


# ── 检索（中文滑窗短语 + 字段加权打分）───────────────────
def _make_terms(q: str) -> List[str]:
    terms = [t for t in re.split(r'\s+', q.strip()) if t][:8]
    phrases = set()
    for t in terms:
        tl = t.lower()
        phrases.add(tl)
        if re.search(r'[\u4e00-\u9fff]', tl) and len(tl) >= 2:
            cnt = 0
            for n in (4, 3, 2):
                for i in range(len(tl) - n + 1):
                    phrases.add(tl[i:i + n])
                    cnt += 1
                    if cnt >= 20:
                        break
                if cnt >= 20:
                    break
    out = [p for p in phrases if p and p not in ('', ' ')]
    return out[:36]


def _plain_text(body: str) -> str:
    """剥离 markdown/Obsidian 语法，返回用于摘要展示的纯文本。"""
    import re as _re
    text = body or ''
    rules = [
        (r'```.*?```', ' '),                    # 代码块
        (r'<!--.*?-->', ' '),                   # HTML 注释
        (r'!\[\[[^\]]*\]\]', ' '),              # 嵌入图片 wikilink
        (r'!\[[^\]]*\]\([^)]*\)', ' '),         # 嵌入图片 md
        (r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]', r'\1'),  # wikilink 保留别名文本
        (r'\[!\w+\]\s*', ''),                   # callout 标记（保留标题文本）
        (r'\[([^\]]*)\]\([^)]*\)', r'\1'),      # md 链接保留文本
        (r'`([^`]*)`', r'\1'),                  # 行内代码保留内容
        (r'^#{1,6}\s+', ''),                    # 标题
        (r'^>\s?', ''),                         # 引用
        (r'^\s*[-*+]\s+', ''),                  # 列表
        (r'^\s*\d+\.\s+', ''),                  # 有序列表
        (r'(\*\*|__)(.*?)\1', r'\2'),           # 加粗
        (r'(\*|_)([^*_]*?)\1', r'\2'),          # 斜体
        (r'~~(.*?)~~', r'\1'),                  # 删除线
        (r'==(.+?)==', r'\1'),                  # 高亮
        (r'^---+\s*$', ''),                     # 分割线
        (r'\|', ' '),                           # 表格分隔
        (r'<[^>]+>', ' '),                      # HTML 标签
    ]
    for pat, rep in rules:
        flags = _re.S if pat.startswith('```') or pat.startswith('<!--') else _re.M
        text = _re.sub(pat, rep, text, flags=flags)
    text = _re.sub(r'\s+', ' ', text).strip()
    return text


def _make_snippet(body: str, phrases: List[str], width: int = 300) -> str:
    body = _plain_text((body or '').replace('\r\n', '\n').replace('\r', '\n'))
    low = body.lower()
    pos = -1
    for ph in sorted(phrases, key=len, reverse=True):
        i = low.find(ph)
        if i >= 0:
            pos = i
            break
    if pos < 0:
        s = body[:width]
        return s + ('…' if len(body) > width else '')
    start = max(0, pos - 100)
    end = min(len(body), pos + width - 100)
    nl = body.rfind('\n', 0, pos)
    if nl > start:
        start = nl + 1
    seg = body[start:end].strip()
    return ('…' if start > 0 else '') + seg + ('…' if end < len(body) else '')


def search_kb(q: str, top: int = 5) -> List[dict]:
    """全文关键词检索，返回 [{id,title,path,score,snippet,tags}]"""
    phrases = _make_terms(q)
    if not phrases:
        return []
    where = ' OR '.join(
        ['(lower(title) LIKE ? OR lower(body_md) LIKE ? OR list_contains(tags, ?))'] * min(len(phrases), 10))
    use = phrases[:10]
    params: List = []
    for p in use:
        params += [f'%{p}%', f'%{p}%', p]
    try:
        conn = _conn(read_only=True)
    except Exception:
        return []
    try:
        rows = conn.execute(
            f'SELECT id, title, path, tags, body_md FROM notes WHERE {where} LIMIT 500',
            params).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    scored = []
    for nid, title, path, tags, body in rows:
        tl = (title or '').lower()
        bl = (body or '').lower()
        tag_list = [str(t).lower() for t in (tags or [])]
        score = 0.0
        for p in phrases:
            n_title = tl.count(p)
            n_body = bl.count(p)
            n_tag = sum(1 for tg in tag_list if p in tg)
            if n_title:
                score += 8 * n_title * min(len(p), 4) / 2
            if n_tag:
                score += 6 * n_tag
            if n_body:
                score += n_body * min(len(p), 4) / 2
        if score > 0:
            scored.append({'id': nid, 'title': title, 'path': path,
                           'score': round(score, 2),
                           'snippet': _make_snippet(body or '', phrases),
                           'tags': tag_list})
    scored.sort(key=lambda x: -x['score'])
    return scored[:top]


# ── 查询辅助 ────────────────────────────────────────────
def get_note(key: str) -> Optional[dict]:
    """按 id（数字）或 slug（lower 标题/路径名）取笔记详情 + 出链/反链"""
    conn = _conn(read_only=True)
    try:
        if key.isdigit():
            row = conn.execute(
                'SELECT id, path, title, folder, body_md, raw_frontmatter, tags, created_at '
                'FROM notes WHERE id=?', [int(key)]).fetchone()
        else:
            slug = key.strip().strip('/').lower()
            row = conn.execute(
                "SELECT id, path, title, folder, body_md, raw_frontmatter, tags, created_at "
                "FROM notes WHERE lower(title)=? OR lower(path)=? "
                "OR lower(path)=? || '.md' OR lower(path) LIKE ? LIMIT 1",
                [slug, slug, slug, '%/' + slug + '.md']).fetchone()
        if not row:
            return None
        nid, path, title, folder, body, raw_fm, tags, created = row
        tag_list = [str(t) for t in (tags or [])]
        # 出链解析
        outgoing = []
        for link in conn.execute('SELECT unnest(out_links) FROM notes WHERE id=?', [nid]).fetchall():
            lt = link[0]
            m = conn.execute(
                "SELECT id, title FROM notes WHERE lower(title)=? "
                "OR lower(path)=? || '.md' OR lower(path) LIKE ? LIMIT 1",
                [lt, lt, '%/' + lt + '.md']).fetchone()
            if m and m[0] != nid:
                outgoing.append({'id': m[0], 'title': m[1]})
        # 反链：其他笔记的 out_links 含本笔记 title 或文件名
        fname = Path(path).stem.lower()
        back = conn.execute(
            "SELECT id, title, path FROM notes WHERE id<>? AND "
            "(list_contains(out_links, ?) OR list_contains(out_links, ?))",
            [nid, title.lower(), fname]).fetchall()
        fm = {}
        if raw_fm:
            fm, _, _ = parse_frontmatter('---\n' + raw_fm + '\n---\n')
        return {'id': nid, 'path': path, 'title': title, 'folder': folder,
                'body_md': body, 'tags': tag_list, 'frontmatter': fm,
                'created_at': str(created)[:10] if created else '',
                'outgoing': outgoing,
                'backlinks': [{'id': b[0], 'title': b[1], 'path': b[2]} for b in back]}
    finally:
        conn.close()


def list_notes(folder: str = '', tag: str = '', keyword: str = '',
               limit: int = 50, offset: int = 0) -> dict:
    conn = _conn(read_only=True)
    try:
        where, params = [], []
        if folder:
            where.append('(folder = ? OR folder LIKE ?)')
            params += [folder, folder.rstrip('/') + '/%']
        if tag:
            where.append('list_contains(tags, ?)')
            params.append(tag.lower())
        if keyword:
            where.append('(lower(title) LIKE ? OR lower(body_md) LIKE ?)')
            params += [f'%{keyword.lower()}%'] * 2
        wsql = ('WHERE ' + ' AND '.join(where)) if where else ''
        total = conn.execute(f'SELECT COUNT(*) FROM notes {wsql}', params).fetchone()[0]
        rows = conn.execute(
            f'SELECT id, path, title, folder, tags, body_md, mtime FROM notes {wsql} '
            'ORDER BY mtime DESC LIMIT ? OFFSET ?',
            params + [int(limit), int(offset)]).fetchall()
        items = []
        for nid, path, title, fld, tags, body, mtime in rows:
            items.append({
                'id': nid, 'path': path, 'title': title, 'folder': fld,
                'tags': [str(t) for t in (tags or [])],
                'snippet': _plain_text(body)[:120],
                'mtime': str(mtime)[:10] if mtime else '',
            })
        return {'total': total, 'items': items}
    finally:
        conn.close()


def build_tree() -> dict:
    """目录树 + 标签云 + 统计"""
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    conn = _conn(read_only=True)
    try:
        id_by_path = {r[0]: r[1] for r in conn.execute('SELECT path, id FROM notes').fetchall()}
        tag_rows = conn.execute(
            'SELECT tag, COUNT(*) AS n FROM (SELECT UNNEST(tags) AS tag FROM notes) t '
            'WHERE tag IS NOT NULL AND tag <> \'\' '
            'GROUP BY tag ORDER BY n DESC, tag LIMIT 40').fetchall()
        stats = conn.execute(
            'SELECT COUNT(*), COALESCE(SUM(size),0) FROM notes').fetchone()
    except Exception:
        id_by_path, tag_rows, stats = {}, [], (0, 0)
    finally:
        conn.close()

    def node_for(rel: str, is_dir: bool) -> dict:
        name = rel.split('/')[-1]
        if is_dir:
            return {'type': 'folder', 'name': name, 'path': rel, 'children': []}
        if rel in id_by_path:
            return {'type': 'note', 'name': name[:-3], 'path': rel, 'id': id_by_path[rel]}
        return {'type': 'file', 'name': name, 'path': rel}

    root: dict = {'type': 'folder', 'name': '', 'path': '', 'children': []}
    dirs: Dict[str, dict] = {'': root}
    entries = []
    for p in VAULT_DIR.rglob('*'):
        rel = p.relative_to(VAULT_DIR).as_posix()
        entries.append((rel, p.is_dir(), p.name.lower()))
    entries.sort(key=lambda e: (not e[1], e[2]))
    for rel, is_dir, _ in entries:
        parent_key = rel.rsplit('/', 1)[0] if '/' in rel else ''
        # 确保父目录链存在
        if parent_key and parent_key not in dirs:
            parts = parent_key.split('/')
            acc = ''
            for part in parts:
                acc = f'{acc}/{part}' if acc else part
                if acc not in dirs:
                    dn = node_for(acc, True)
                    dirs[acc] = dn
                    parent_of_acc = acc.rsplit('/', 1)[0] if '/' in acc else ''
                    dirs[parent_of_acc]['children'].append(dn)
        if is_dir:
            if rel not in dirs:
                dn = node_for(rel, True)
                dirs[rel] = dn
                dirs[parent_key]['children'].append(dn)
        else:
            dirs[parent_key]['children'].append(node_for(rel, False))

    tags = [{'tag': t, 'count': n} for t, n in tag_rows]
    att_count = sum(1 for _ in VAULT_DIR.rglob('*')
                    if _.is_file() and _.suffix.lower() != _MD_SUFFIX)
    return {'tree': root['children'], 'tags': tags,
            'stats': {'notes': stats[0], 'attachments': att_count, 'tags': len(tags)}}


def safe_attachment_path(rel: str) -> Optional[Path]:
    """防目录穿越：realpath 必须位于 vault 内"""
    rel = (rel or '').strip().replace('\\', '/').lstrip('/')
    if not rel or '..' in rel.split('/') or ':' in rel:
        return None
    p = (VAULT_DIR / rel)
    try:
        real = p.resolve()
        vault_real = VAULT_DIR.resolve()
        if not str(real).startswith(str(vault_real) + os.sep):
            return None
        return real if real.is_file() else None
    except Exception:
        return None
