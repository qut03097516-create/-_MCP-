"""
backend/agent/router.py
=======================
阶段二 · DuMate 智能体闭环：HTTP 路由层

/api/agent/run           提交主任务（异步执行，返回 task_id）
/api/agent/tasks/{id}    轮询任务状态与步骤明细
/api/agent/confirm       人工确认点（高风险任务需用户拍板）
/api/agent/contracts     工具契约（供前端渲染工具面板 / 验收审计）
/api/agent/report/{id}   取最终报告 Markdown

鉴权：全部要求登录（依赖现有 get_current_user 依赖注入）；
      工具端再从 JWT 解析 user，不信任智能体传入的 user_id（双保险）。
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import state_machine as sm
from backend.api.sites import _require_user
from .tools import resolve_user, run_tool, new_trace_id
from .contracts import TOOL_SCHEMAS

router = APIRouter(prefix='/api/agent', tags=['agent'])


# MCP 原子工具集合（排除状态机内部节点 confirm_action）
ATOM_TOOLS = {name: schema for name, schema in TOOL_SCHEMAS.items()
              if name != 'confirm_action'}


# ── 请求/响应模型 ───────────────────────────────────────────────────────────
class AgentRunRequest(BaseModel):
    # MCP 工具直调契约（DuMate 平台注册入口）：tool 指定工具，params 传参数
    tool: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    pv_file: Optional[str] = None
    site_id: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    forecast_days: int = Field(default=7, ge=1, le=30)
    mode: str = Field(default='future', pattern='^(future|historical)$')
    province: Optional[str] = None
    battery_capacity: int = Field(default=1000, ge=50, le=100000)
    battery_power: int = Field(default=500, ge=25, le=50000)
    efficiency: int = Field(default=90, ge=60, le=99)
    initial_soc: float = Field(default=50, ge=0, le=100)
    load_ratio: float = Field(default=0.3, ge=0.0, le=1.0)
    task_id: Optional[str] = None


class AgentConfirmRequest(BaseModel):
    task_id: str
    approved: bool


# ── 依赖：登录用户（复用项目现有范式：Cookie 优先，其次 Bearer） ─────────
def _current_user_http(request: Request) -> Dict[str, Any]:
    user = _require_user(
        request.cookies.get('access_token'),
        request.headers.get('Authorization'))
    if user is None:
        raise HTTPException(status_code=401, detail='未登录或凭证无效')
    return user


# ── 路由 ────────────────────────────────────────────────────────────────────
@router.post('/run', summary='提交主任务 / MCP 工具直调')
def agent_run(body: AgentRunRequest, request: Request):
    user = _current_user_http(request)
    # MCP 工具直调契约：{"tool": "get_site", "params": {...}}
    if body.tool:
        trace_id = body.task_id or new_trace_id()
        result = run_tool(body.tool, body.params or {}, user,
                          trace_id=trace_id)
        payload = result.to_dict()
        payload['tool'] = body.tool
        return payload
    params = body.model_dump()
    # 校验：站点与数据文件至少其一
    if not params.get('pv_file') and not params.get('site_id'):
        raise HTTPException(status_code=422, detail='pv_file 与 site_id 至少提供一个')
    try:
        task = sm.create_task(user, params)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {'task_id': task.task_id, 'trace_id': task.trace_id,
            'state': task.state, 'status': task.status}


@router.get('/contracts', summary='MCP 原子工具契约查询')
def agent_contracts(request: Request):
    user = _current_user_http(request)
    return {'tools': ATOM_TOOLS}


class ToolCallRequest(BaseModel):
    params: Optional[Dict[str, Any]] = None
    trace_id: Optional[str] = None


@router.post('/tools/{tool}', summary='MCP 单工具直调')
def agent_tool_call(tool: str, body: ToolCallRequest, request: Request):
    user = _current_user_http(request)
    trace_id = body.trace_id or new_trace_id()
    result = run_tool(tool, body.params or {}, user, trace_id=trace_id)
    payload = result.to_dict()
    payload['tool'] = tool
    return payload


def _owned_task(task_id: str, request: Request):
    user = _current_user_http(request)
    task = sm.get_runner().get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='任务不存在')
    if str(task.user['id']) != str(user['id']):
        raise HTTPException(status_code=403, detail='无权访问其他用户的任务')
    return task


@router.get('/tasks/{task_id}', summary='查询任务状态与步骤明细')
def agent_task_status(task_id: str, request: Request):
    task = _owned_task(task_id, request)
    return task.to_dict()


@router.post('/confirm', summary='人工确认高风险任务继续/中止')
def agent_confirm(body: AgentConfirmRequest, request: Request):
    user = _current_user_http(request)
    _owned_task(body.task_id, request)
    try:
        task = sm.get_runner().confirm(body.task_id, body.approved, int(user['id']))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {'task_id': task.task_id, 'state': task.state, 'status': task.status}


@router.get('/report/{task_id}', summary='取最终报告')
def agent_report(task_id: str, request: Request):
    task = _owned_task(task_id, request)
    if task.final_report is None:
        raise HTTPException(status_code=409, detail='报告未生成（任务可能未完成或失败）')
    md = task.final_report.data.get('markdown') if task.final_report.data else None
    if not md:
        raise HTTPException(status_code=409, detail='报告内容为空')
    return PlainTextResponse(md, media_type='text/markdown')


# 供 main.py 注册
def include_agent_routes(app):
    app.include_router(router)
