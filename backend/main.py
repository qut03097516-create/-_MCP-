from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from contextlib import asynccontextmanager
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 控制台/重定向 stdout 默认可能是 GBK，emoji/中文日志会 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .api import auth, data, prediction, news, query, home, application, kb, sites, data_import
from .agent.router import router as agent_router
from starlette.middleware.base import BaseHTTPMiddleware
from utils.news_database import PVSystemDatabase

_activity_db = PVSystemDatabase()

# 高频只刷新在线状态、不写明细日志的路径
_PRESENCE_ONLY_PATHS = {
    '/api/auth/me',
    '/api/health',
}

class ActivityMiddleware(BaseHTTPMiddleware):
    """已登录用户：刷新 last_seen；关键操作写入 user_logs"""

    async def dispatch(self, request: Request, call_next):
        user = None
        try:
            cookie = request.cookies.get('access_token')
            header = request.headers.get('authorization') or ''
            bearer = header[7:].strip() if header.startswith('Bearer ') else None
            token = cookie or bearer
            if token:
                import jwt as pyjwt
                payload = pyjwt.decode(
                    token,
                    auth.SECRET_KEY,
                    algorithms=[auth.ALGORITHM],
                )
                uid = int(payload.get('sub'))
                user = _activity_db.get_user_by_id(uid)
        except Exception:
            user = None

        response = await call_next(request)

        try:
            if user and request.url.path.startswith('/api/'):
                _activity_db.touch_user_presence(user['id'])
                path = request.url.path
                if path not in _PRESENCE_ONLY_PATHS and request.method != 'OPTIONS':
                    _activity_db.log_user_action(
                        user.get('id'),
                        user.get('username'),
                        'api',
                        request.method,
                        path,
                        request.client.host if request.client else '',
                        response.status_code,
                    )
        except Exception:
            pass

        return response

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[startup] PV prediction API started")
    yield
    print("[shutdown] PV prediction API stopped")

app = FastAPI(
    title="光储智联·光伏功率预测与协同优化系统",
    description="光伏功率预测与协同优化系统的 API 接口",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(ActivityMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(home.router, prefix="/api/home", tags=["首页"])
app.include_router(data.router, prefix="/api/data", tags=["数据集"])
app.include_router(prediction.router, prefix="/api/prediction", tags=["功率预测"])
app.include_router(news.router, prefix="/api/news", tags=["新闻动态"])
app.include_router(query.router, prefix="/api/query", tags=["资料查询"])
app.include_router(kb.router, prefix="/api/kb", tags=["知识库"])
app.include_router(application.router, prefix="/api/application", tags=["应用场景"])
app.include_router(sites.router, prefix="/api/sites", tags=["用户电站"])
app.include_router(data_import.router, prefix="/api/data-import", tags=["数据导入"])
app.include_router(agent_router, tags=["智能体"])

# MCP 适配层（DuMate Streamable HTTP MCP 入口）
from backend.agent.mcp_adapter import mcp_router
app.include_router(mcp_router)

# 前端静态文件路径
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")

@app.get("/api/health")
async def health_check():
    # RAG 索引状态（M3.2）：只读 active_manifest，不加载检索器
    rag_state = {"loaded": False}
    try:
        import json as _json
        from pathlib import Path as _Path
        act = _Path(__file__).resolve().parents[1] / "data" / "rag" / "active_manifest.json"
        if act.is_file():
            meta = _json.loads(act.read_text(encoding="utf-8"))
            rag_state = {
                "loaded": True,
                "version": meta.get("version"),
                "chunk_count": meta.get("chunk_count"),
                "embedding": meta.get("embedding"),
                "published_at": meta.get("published_at"),
            }
    except Exception as _e:
        rag_state = {"loaded": False, "error": str(_e)[:120]}
    return {"status": "healthy", "rag": rag_state}

# SPA 路由处理
@app.get("/{path:path}")
async def serve_frontend(path: str):
    """提供前端静态文件，支持 SPA 路由"""
    file_path = os.path.join(frontend_dist, path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        # index.html 禁止缓存，确保每次拿到最新版本
        if path == "index.html" or path == "":
            return FileResponse(file_path, headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            })
        # 带 hash 的静态资源（assets/xxx.[hash].js）长缓存
        return FileResponse(file_path, headers={
            "Cache-Control": "public, max-age=31536000, immutable",
        })
    elif os.path.exists(os.path.join(frontend_dist, "index.html")):
        return FileResponse(os.path.join(frontend_dist, "index.html"), headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        })
    return {"message": "光储智联·光伏功率预测与协同优化系统 API", "version": "1.0.0"}
