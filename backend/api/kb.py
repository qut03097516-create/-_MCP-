"""
知识库接口 /api/kb
- vault 扫描 / 上传导入 / 目录树 / 笔记列表与详情 / 全文检索 / 附件读取
"""
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Cookie, Header
from fastapi.responses import FileResponse

from ..utils import knowledge_base as kbcore
from typing import Optional
from .sites import _require_user

router = APIRouter()

_ALLOWED_UPLOAD_MD = {'.md', '.markdown'}
_ALLOWED_ZIP_MEMBER = {'.md', '.markdown', '.png', '.jpg', '.jpeg', '.gif', '.webp',
                       '.svg', '.pdf', '.bmp', '.mp3', '.mp4', '.wav'}
MAX_UPLOAD = 50 * 1024 * 1024
MAX_ZIP_TOTAL = 200 * 1024 * 1024
MAX_ZIP_ENTRIES = 2000


@router.post('/scan')
async def scan_vault(access_token: Optional[str] = Cookie(None),
                     authorization: Optional[str] = Header(None)):
    """增量扫描 vault 目录（需登录）"""
    _require_user(access_token, authorization)
    return kbcore.rescan()


@router.post('/upload')
async def upload_kb(file: UploadFile = File(...),
                    access_token: Optional[str] = Cookie(None),
                    authorization: Optional[str] = Header(None)):
    """上传 .md 或 Obsidian 导出的 .zip 导入 vault，完成后自动扫描（需登录）"""
    _require_user(access_token, authorization)
    name = Path(file.filename or '').name
    suffix = Path(name).suffix.lower()
    raw = await file.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(400, '文件超过 50MB 限制')
    imported, skipped = [], []

    if suffix in _ALLOWED_UPLOAD_MD:
        target = kbcore.VAULT_DIR / name
        target.write_bytes(raw)
        imported.append(name)
    elif suffix == '.zip':
        kbcore.VAULT_DIR.mkdir(parents=True, exist_ok=True)
        import io
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                members = zf.infolist()
                if len(members) > MAX_ZIP_ENTRIES:
                    raise HTTPException(400, '压缩包条目过多（>2000）')
                total = 0
                for m in members:
                    if m.is_dir():
                        continue
                    total += m.file_size
                    if total > MAX_ZIP_TOTAL:
                        raise HTTPException(400, '压缩包解压体积超限（>200MB）')
                    msuffix = Path(m.filename).suffix.lower()
                    if msuffix not in _ALLOWED_ZIP_MEMBER:
                        skipped.append(m.filename)
                        continue
                    # 防 zip-slip
                    rel = Path(m.filename)
                    if rel.is_absolute() or '..' in rel.parts or ':' in rel.parts[0]:
                        skipped.append(m.filename)
                        continue
                    dest = kbcore.VAULT_DIR / rel
                    if not str(dest.resolve()).startswith(str(kbcore.VAULT_DIR.resolve())):
                        skipped.append(m.filename)
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(m) as src, open(dest, 'wb') as out:
                        shutil.copyfileobj(src, out)
                    imported.append(m.filename)
        except zipfile.BadZipFile:
            raise HTTPException(400, '无效的 zip 文件')
    else:
        raise HTTPException(400, '仅支持 .md 或 .zip 文件')

    scan_result = kbcore.rescan()
    return {'success': True, 'imported': imported, 'skipped': skipped, 'scan': scan_result}


@router.get('/tree')
async def get_tree():
    """目录树 + 标签云 + 统计"""
    return kbcore.build_tree()


@router.get('/notes')
async def get_notes(folder: str = '', tag: str = '', keyword: str = '',
                    limit: int = 50, offset: int = 0):
    """笔记列表（文件夹/标签/关键词过滤）"""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return kbcore.list_notes(folder, tag, keyword, limit, offset)


@router.get('/search')
async def search(q: str, limit: int = 20):
    """混合检索（BM25+向量，M3.3），失败回退 duckdb 关键词检索"""
    if not q.strip():
        return {'results': []}
    top = max(1, min(limit, 50))
    try:
        from ..utils.rag_retriever import Retriever
        hits = Retriever.instance().retrieve(q, top)
        if hits:
            return {'results': hits, 'engine': 'hybrid'}
    except Exception:
        pass
    return {'results': kbcore.search_kb(q, top=top), 'engine': 'keyword'}


@router.get('/note/{key}')
async def get_note_detail(key: str):
    """笔记详情（key 为 id 或 slug）"""
    note = kbcore.get_note(key)
    if not note:
        raise HTTPException(404, '笔记不存在')
    return {'note': note}


@router.get('/attachment')
async def get_attachment(path: str):
    """读取 vault 内附件（防目录穿越）"""
    real = kbcore.safe_attachment_path(path)
    if not real:
        raise HTTPException(400, '非法附件路径')
    return FileResponse(str(real))
