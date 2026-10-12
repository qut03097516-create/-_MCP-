"""
backend/agent/state_machine.py
===============================
阶段二 · DuMate 智能体闭环：主任务状态机

把「站点识别→数据质量→天气→预测→风险→储能收益→RAG→报告」编码为显式状态机，
具备：
- 状态流转与非法迁移防护（set_state 校验迁移边）
- 幂等任务 ID（同 trace_id 重复提交直接返回缓存结果）
- 失败降级记账（每步实际 source / fallback / warning 可回溯）
- 人工确认点（E_CONFIRM_REQ：高风险任务先暂停，等用户确认后继续）
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from .contracts import EC, ToolResult, ok, fail, new_trace_id
from . import tools as agent_tools


# ─────────────────────────────────────────────────────────────────────────────
# 状态机定义
# ─────────────────────────────────────────────────────────────────────────────
class St:
    CREATED = 'CREATED'            # 已入队
    VALIDATING = 'VALIDATING'      # 站点识别/输入校验
    FETCHING = 'FETCHING'          # 数据质量 + 天气
    FORECASTING = 'FORECASTING'    # 功率预测
    DIAGNOSING = 'DIAGNOSING'      # 风险诊断
    OPTIMIZING = 'OPTIMIZING'      # 储能收益
    REPORTING = 'REPORTING'        # RAG + 报告
    DONE = 'DONE'
    FAILED = 'FAILED'
    AWAIT_CONFIRM = 'AWAIT_CONFIRM'  # 人工确认点


# 合法迁移边
_EDGES = {
    St.CREATED: {St.VALIDATING, St.FAILED},
    St.VALIDATING: {St.FETCHING, St.AWAIT_CONFIRM, St.FAILED},
    St.FETCHING: {St.FORECASTING, St.AWAIT_CONFIRM, St.FAILED},
    St.FORECASTING: {St.DIAGNOSING, St.AWAIT_CONFIRM, St.FAILED},
    St.DIAGNOSING: {St.OPTIMIZING, St.AWAIT_CONFIRM, St.FAILED},
    St.OPTIMIZING: {St.REPORTING, St.AWAIT_CONFIRM, St.FAILED},
    St.REPORTING: {St.DONE, St.FAILED},
    St.AWAIT_CONFIRM: {St.FETCHING, St.FORECASTING, St.DIAGNOSING,
                       St.OPTIMIZING, St.REPORTING, St.DONE, St.FAILED},
    St.DONE: set(),
    St.FAILED: set(),
}

# 报告模板：与 tools.generate_report 对齐，前端工作台按此呈现
REPORT_TEMPLATE = {
    'sections': [
        {'key': 'summary', 'title': '一、执行摘要'},
        {'key': 'data', 'title': '二、关键数据'},
        {'key': 'risk', 'title': '三、风险与建议'},
        {'key': 'storage', 'title': '四、储能与收益'},
        {'key': 'knowledge', 'title': '五、知识库引用（RAG）'},
        {'key': 'uncertainty', 'title': '六、不确定性说明'},
        {'key': 'next', 'title': '七、下一步'},
    ],
}


class TaskError(Exception):
    pass


class AgentTask:
    """单个主任务的执行上下文（幂等、可追踪、可恢复）。"""

    def __init__(self, task_id: str, user: Dict[str, Any],
                 params: Dict[str, Any], trace_id: str = ''):
        self.task_id = task_id
        self.user = user
        self.params = params
        self.trace_id = trace_id or new_trace_id()
        self.state = St.CREATED
        self.steps: Dict[str, ToolResult] = {}
        self.step_order: List[str] = []
        self.errors: List[Dict[str, Any]] = []
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.resume_after: Optional[str] = None   # 确认后从哪一步续跑
        self.next_step_index = 0
        self.final_report: Optional[ToolResult] = None
        self.status = 'queued'  # queued/running/await_confirm/done/failed

    # ── 状态机核心 ─────────────────────────────────────────────────────────
    def set_state(self, next_st: str) -> bool:
        # 同一状态内的多步骤（如 FETCHING 内 check_data_quality→get_weather）
        # 视为保持，不做迁移校验
        if next_st == self.state:
            return True
        if next_st not in _EDGES.get(self.state, set()):
            self.record_error(f'非法状态迁移: {self.state} -> {next_st}',
                              ec=EC.E_INTERNAL)
            return False
        self.state = next_st
        self.updated_at = time.time()
        return True

    def record_error(self, msg: str, ec: str = EC.E_INTERNAL,
                     step: str = '', exception: Optional[Exception] = None):
        self.errors.append({
            'time': time.time(), 'ec': ec, 'step': step or self.state,
            'message': msg,
            'detail': str(exception)[:300] if exception else None,
        })

    def add_step(self, name: str, result: ToolResult):
        self.steps[name] = result
        if name not in self.step_order:
            self.step_order.append(name)
        self.updated_at = time.time()

    # ── 序列化（前端轮询 / 审计） ──────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        return {
            'task_id': self.task_id,
            'trace_id': self.trace_id,
            'state': self.state,
            'status': self.status,
            'progress': f'{len(self.step_order)}/{len(AGENT_FLOW)} 步',
            'current_step': self.step_order[-1] if self.step_order else None,
            'steps': [
                {
                    'name': s,
                    'source': self.steps[s].source,
                    'ok': self.steps[s].success,
                    'error_code': self.steps[s].error_code,
                    'warning': self.steps[s].warning,
                    'elapsed_ms': self.steps[s].elapsed_ms,
                }
                for s in self.step_order
            ],
            'errors': self.errors[-5:],
            'awaiting_confirm': self.state == St.AWAIT_CONFIRM,
            'resume_after': self.resume_after,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'params': {k: v for k, v in self.params.items()
                       if k not in ('access_token', 'token')},
        }


# ─────────────────────────────────────────────────────────────────────────────
# 主业务流程（Mirror tools.generate_report 的聚合顺序，但按状态机逐步走）
# ─────────────────────────────────────────────────────────────────────────────
AGENT_FLOW = [
    ('get_site', St.VALIDATING, '站点识别'),
    ('check_data_quality', St.FETCHING, '数据质量'),
    ('get_weather', St.FETCHING, '天气获取'),
    ('forecast_power', St.FORECASTING, '功率预测'),
    ('diagnose_risk', St.DIAGNOSING, '风险诊断'),
    ('optimize_storage', St.OPTIMIZING, '储能收益'),
    ('search_knowledge', St.REPORTING, '知识检索'),
    ('generate_report', St.REPORTING, '报告生成'),
]


def _params_for(task: AgentTask, step_name: str) -> Dict[str, Any]:
    p = dict(task.params)
    # get_weather：经纬度由 get_site 结果注入（用户站点 / 数据集文件名解析）
    if step_name == 'get_weather' and not p.get('latitude'):
        site = task.steps.get('get_site')
        if site and site.success and site.data:
            s = site.data
            provider = s.get('provider') or s
            lat_s = provider.get('latitude') or s.get('lat')
            lon_s = provider.get('longitude') or s.get('lon')
            if lat_s is not None and not str(lat_s).startswith('N/'):
                try:
                    p['latitude'] = _to_float(lat_s)
                    p['longitude'] = _to_float(lon_s)
                except (TypeError, ValueError):
                    pass
            elif s.get('lat') is not None:
                p['latitude'] = float(s['lat'])
                p['longitude'] = float(s['lon'])
    # search_knowledge：RAG 查询词不在用户参数里，用上下文相关默认主题
    if step_name == 'search_knowledge' and not p.get('query'):
        head = p.get('pv_file', '').split(' - ')[0] if p.get('pv_file') else None
        if not head:
            # 用户电站：取站点识别步骤返回的站名
            site = task.steps.get('get_site')
            if site and site.success and site.data:
                head = (site.data.get('name') or site.data.get('display_name') or '')[:20] or None
        p['query'] = ' '.join(filter(None, [
            head,
            '光伏', '储能', '分时电价', '收益', '政策建议',
        ]))[:200]
    return p


def _to_float(v) -> float:
    s = str(v).replace('°N', '').replace('°S', '').replace('°E', '').replace('°W', '').strip()
    return float(s)


class AgentRunner:
    """内存任务仓 + 串行执行器（单线程，避免并发写共享 DB；任务量小，满足演示与审计）。"""

    def __init__(self):
        self._tasks: Dict[str, AgentTask] = {}
        self._lock = threading.Lock()
        self._history: List[str] = []

    # ── 任务仓接口 ─────────────────────────────────────────────────────────
    def submit(self, user: Dict[str, Any], params: Dict[str, Any]) -> AgentTask:
        task_id = params.get('task_id') or new_trace_id()
        with self._lock:
            existing = self._tasks.get(task_id)
            if existing:
                if str(existing.user['id']) != str(user['id']):
                    raise PermissionError('任务 ID 已由其他用户使用')
                return existing
            task = AgentTask(task_id, user, params)
            self._tasks[task_id] = task
            self._history.append(task_id)
        self.run(task_id)
        return self.get(task_id)

    def get(self, task_id: str) -> Optional[AgentTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def confirm(self, task_id: str, approved: bool, user_id: int) -> Optional[AgentTask]:
        """人工确认：高风险预警任务由用户拍板继续/中止。"""
        task = self.get(task_id)
        if not task:
            return None
        if str(task.user['id']) != str(user_id):
            raise PermissionError('无权确认其他用户的任务')
        if task.state != St.AWAIT_CONFIRM:
            return task
        if not approved:
            task.set_state(St.FAILED)
            task.status = 'failed'
            task.record_error('用户拒绝继续执行', ec=EC.E_CONFIRM_REQ, step='confirm')
            return task
        task.set_state(task.resume_after or St.FETCHING)
        task.status = 'running'
        return self.resume(task_id)

    # ── 执行器 ─────────────────────────────────────────────────────────────
    def run(self, task_id: str) -> Optional[AgentTask]:
        task = self.get(task_id)
        if not task:
            return None
        task.status = 'running'
        self._execute(task)
        return task

    def resume(self, task_id: str) -> Optional[AgentTask]:
        return self.run(task_id)

    def _execute(self, task: AgentTask):
        """逐步骤执行主流程；任何一步失败 → 降级继续或 FAILED。"""
        try:
            if task.state == St.CREATED and not task.set_state(St.VALIDATING):
                return self._fail(task, '初始化失败')

            for index in range(task.next_step_index, len(AGENT_FLOW)):
                name, state, label = AGENT_FLOW[index]
                if not task.set_state(state):
                    continue
                if name == 'generate_report':
                    # 复用已执行步骤结果，避免重复重算（预测/诊断耗时步骤只跑一次）
                    from .tools import generate_report as _gr
                    result = _gr(_params_for(task, name), task.user,
                                 trace_id=task.trace_id, cached=task.steps)
                    task.add_step(name, result)
                else:
                    result = agent_tools.run_tool(name, _params_for(task, name),
                                                  task.user, task.trace_id)
                    task.add_step(name, result)

                # 高风险诊断只暂停后续建议与报告，不重复执行已完成的预测。
                risks = (result.data or {}).get('risks', []) if name == 'diagnose_risk' and result.success else []
                needs_confirm = result.error_code == EC.E_CONFIRM_REQ or any(
                    risk.get('level') == 'high' for risk in risks)
                if needs_confirm:
                    task.set_state(St.AWAIT_CONFIRM)
                    task.next_step_index = index + 1
                    task.resume_after = AGENT_FLOW[index + 1][1] if index + 1 < len(AGENT_FLOW) else St.DONE
                    task.status = 'await_confirm'
                    return

                # 失败降级：核心步骤失败才整体 FAILED；非核心（知识检索等）允许带降级继续
                if not result.success:
                    task.record_error(result.message or '步骤失败',
                                      ec=result.error_code, step=name)
                    if name in ('get_site', 'forecast_power'):
                        return self._fail(task, result.message or f'{label}失败')
                    # 非阻断步骤：跳过并继续，报告里会标注
                task.next_step_index = index + 1

            # 收尾：生成报告（若之前未成功，此处强制聚合一次）
            report = task.steps.get('generate_report')
            if report and report.success:
                task.final_report = report
            task.set_state(St.DONE)
            task.status = 'done'
            task.updated_at = time.time()
        except Exception as e:  # 兜底：状态机自身异常
            task.record_error(f'状态机异常: {str(e)}', step=task.state)
            return self._fail(task, f'状态机异常: {str(e)}')

    def _fail(self, task: AgentTask, msg: str):
        task.set_state(St.FAILED)
        task.status = 'failed'
        task.record_error(msg, step=task.state)


def _after(state: str) -> str:
    """确认后续跑的下一步状态。"""
    for i, (_, st, _) in enumerate(AGENT_FLOW):
        if st == state:
            return AGENT_FLOW[i + 1][1] if i + 1 < len(AGENT_FLOW) else St.DONE
    return St.FETCHING


# 单例
_runner = AgentRunner()


def get_runner() -> AgentRunner:
    return _runner


def create_task(user: Dict[str, Any], params: Dict[str, Any]) -> AgentTask:
    return get_runner().submit(user, params)
