"""
backend/agent/contracts.py
==========================
阶段二 · DuMate 智能体闭环：统一工具契约

所有原子工具（get_site / check_data_quality / get_weather / forecast_power /
diagnose_risk / optimize_storage / search_knowledge / generate_report）复用
本模块定义：

- 统一返回结构：success / data / error_code / message / source / elapsed_ms / trace_id
- 错误码表：E_OK / E_AUTH / E_FORBIDDEN / E_BAD_PARAM / E_NOT_FOUND /
            E_EMPTY_DATA / E_TIMEOUT / E_UPSTREAM / E_INTERNAL
- 工具 JSON Schema / 单位 / 参数范围 / 超时声明（供 docs/tool-contracts.md 与调试面板使用）
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# 错误码
# ─────────────────────────────────────────────────────────────────────────────
class EC:
    E_OK           = "E_OK"            # 成功
    E_AUTH         = "E_AUTH"          # 未登录 / 凭证无效
    E_FORBIDDEN    = "E_FORBIDDEN"     # 权限不足（非本人电站等）
    E_BAD_PARAM    = "E_BAD_PARAM"     # 参数缺失 / 非法
    E_NOT_FOUND    = "E_NOT_FOUND"     # 站点 / 文件 / 模型不存在
    E_EMPTY_DATA   = "E_EMPTY_DATA"    # 空数据（无可分析内容，非错误）
    E_TIMEOUT      = "E_TIMEOUT"       # 上游超时
    E_UPSTREAM     = "E_UPSTREAM"      # 上游服务失败（天气 / LLM / 知识库）
    E_INTERNAL     = "E_INTERNAL"      # 内部错误
    E_CONFIRM_REQ  = "E_CONFIRM_REQ"   # 需要人工确认（高风险操作）
    E_UNAVAILABLE  = "E_UNAVAILABLE"   # 能力未配置（如缺 API Key）


_ERROR_TEXT = {
    EC.E_OK: "成功",
    EC.E_AUTH: "未登录或登录凭证无效",
    EC.E_FORBIDDEN: "权限不足",
    EC.E_BAD_PARAM: "参数缺失或非法",
    EC.E_NOT_FOUND: "资源不存在",
    EC.E_EMPTY_DATA: "数据为空，无可分析内容",
    EC.E_TIMEOUT: "上游服务超时",
    EC.E_UPSTREAM: "上游服务暂不可用",
    EC.E_INTERNAL: "内部错误",
    EC.E_CONFIRM_REQ: "该操作需要人工确认",
    EC.E_UNAVAILABLE: "能力未配置或不可用",
}


# ─────────────────────────────────────────────────────────────────────────────
# 统一返回结构
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ToolResult:
    """原子工具的固定返回契约。"""
    success: bool
    data: Any = None
    error_code: str = EC.E_OK
    message: str = ""
    source: List[str] = field(default_factory=list)      # 数据/模型/知识来源
    elapsed_ms: int = 0
    trace_id: str = ""
    warning: Optional[str] = None                        # 降级说明（非错误）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error_code": self.error_code,
            "message": self.message or _ERROR_TEXT.get(self.error_code, ""),
            "source": self.source,
            "elapsed_ms": self.elapsed_ms,
            "trace_id": self.trace_id,
            "warning": self.warning,
        }


def ok(data: Any, *, source: Optional[List[str]] = None,
       trace_id: str = "", warning: Optional[str] = None,
       elapsed_ms: int = 0, message: str = "") -> ToolResult:
    return ToolResult(success=True, data=data, error_code=EC.E_OK,
                      message=message or "成功", source=list(source or []),
                      elapsed_ms=elapsed_ms, trace_id=trace_id,
                      warning=warning)


def fail(error_code: str, message: str = "", *,
         trace_id: str = "", source: Optional[List[str]] = None,
         elapsed_ms: int = 0) -> ToolResult:
    return ToolResult(success=False, data=None, error_code=error_code,
                      message=message or _ERROR_TEXT.get(error_code, ""),
                      source=list(source or []),
                      elapsed_ms=elapsed_ms, trace_id=trace_id)


def _now_ms() -> int:
    return int(time.time() * 1000)


def new_trace_id() -> str:
    """生成 trace_id：全链路唯一的 32 位十六进制。"""
    return uuid.uuid4().hex


# ─────────────────────────────────────────────────────────────────────────────
# 工具注册表与 Schema（JSON Schema 摘要，供文档/调试面板/前端渲染）
# ─────────────────────────────────────────────────────────────────────────────
TOOL_TIMEOUTS = {
    "get_site": 10,
    "check_data_quality": 60,
    "get_weather": 90,
    "forecast_power": 120,
    "diagnose_risk": 60,
    "optimize_storage": 60,
    "search_knowledge": 20,
    "generate_report": 60,
    "confirm_action": 10,
}

TOOL_SCHEMAS: Dict[str, dict] = {
    "get_site": {
        "summary": "识别电站并返回站址、装机、朝向等基础信息",
        "params": {
            "type": "object",
            "properties": {
                "site_id": {"type": "integer", "description": "用户电站 id（dataimport/工作台创建）"},
                "pv_file": {"type": "string", "description": "内置数据集文件名（如 云南_-_Timeseries_...csv）"},
                "name": {"type": "string", "description": "用户电站名称（模糊匹配）"},
            },
            "oneOf": [{"required": ["site_id"]}, {"required": ["pv_file"]}, {"required": ["name"]}],
        },
        "units": "kWp / 度°",
    },
    "check_data_quality": {
        "summary": "检查光伏时序数据质量：缺失率、越界数、时间间隔",
        "params": {
            "type": "object",
            "properties": {
                "pv_file": {"type": "string", "description": "内置数据集文件名或已上传文件名"},
                "start_date": {"type": "string", "description": "YYYY-MM-DD，默认文件最早日期"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD，默认文件最晚日期"},
                "capacity_kwp": {"type": "number", "description": "装机容量 kWp，用于功率越界判定"},
            },
            "required": [],
        },
        "units": "kW / kWp",
    },
    "get_weather": {
        "summary": "获取逐小时天气（GHI/气温/风速）。未来用 Open-Meteo，历史用 NASA POWER 缓存",
        "params": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                "longitude": {"type": "number", "minimum": -180, "maximum": 180},
                "start_date": {"type": "string", "description": "YYYY-MM-DD（历史回算）"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                "forecast_days": {"type": "integer", "minimum": 1, "maximum": 16, "description": "未来天数（不给日期时使用）"},
                "source": {"type": "string", "enum": ["auto", "nasa_power", "open_meteo"], "default": "auto"},
            },
            "required": [],
        },
        "units": "W/m²(ghi) / °C(t2m) / m/s(ws2m)",
    },
    "forecast_power": {
        "summary": "功率预测：混合预测（物理+ML残差）优先；无站点则用内置数据集 iid 模型",
        "params": {
            "type": "object",
            "properties": {
                "site_id": {"type": "integer", "description": "用户电站 id（优先走混合预测）"},
                "pv_file": {"type": "string", "description": "内置数据集文件名（走 iid_transformer_lstm）"},
                "start_date": {"type": "string", "description": "YYYY-MM-DD（历史回算）"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
                "forecast_days": {"type": "integer", "minimum": 1, "maximum": 16, "default": 7},
                "mode": {"type": "string", "enum": ["historical", "future"], "default": "future"},
            },
            "required": [],
        },
        "units": "kW（瞬时）/ kWh（能量）",
    },
    "diagnose_risk": {
        "summary": "围绕预测与数据给出风险条目：低辐照、高温、数据缺失、越界等",
        "params": {
            "type": "object",
            "properties": {
                "pv_file": {"type": "string"},
                "site_id": {"type": "integer"},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "forecast_days": {"type": "integer", "minimum": 1, "maximum": 16, "default": 7},
            },
            "required": [],
        },
        "units": "无",
    },
    "optimize_storage": {
        "summary": "储能配置与充放电策略优化，估算套利收益（分时电价）",
        "params": {
            "type": "object",
            "properties": {
                "pv_file": {"type": "string"},
                "site_id": {"type": "integer"},
                "battery_capacity": {"type": "integer", "minimum": 0, "default": 1000, "units": "kWh"},
                "battery_power": {"type": "integer", "minimum": 0, "default": 500, "units": "kW"},
                "efficiency": {"type": "number", "minimum": 50, "maximum": 100, "default": 90, "units": "%"},
                "initial_soc": {"type": "number", "minimum": 0, "maximum": 100, "default": 50, "units": "%"},
                "load_ratio": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.3},
                "load_type": {"type": "string", "enum": ["fixed", "industrial", "commercial"], "default": "industrial"},
                "province": {"type": "string", "description": "电价省份，默认按坐标反查"},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
            },
            "required": [],
        },
        "units": "kWh / kW / 元",
    },
    "search_knowledge": {
        "summary": "知识库 RAG 检索：政策、电价、故障诊断、储能等主题",
        "params": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索主题"},
                "top": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["query"],
        },
        "units": "无",
    },
    "generate_report": {
        "summary": "汇总各工具结果生成结构化 Markdown 报告（执行摘要/关键数据/风险/收益/引用）",
        "params": {
            "type": "object",
            "properties": {
                "site_id": {"type": "integer"},
                "pv_file": {"type": "string"},
                "forecast_days": {"type": "integer", "default": 7},
                "task_id": {"type": "string", "description": "任务幂等 id（重复提交同 id 返回同报告）"},
                "mode": {"type": "string", "enum": ["future", "historical"], "default": "future"},
                "start_date": {"type": "string", "description": "YYYY-MM-DD，透传给预测/质检/风险/储能"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD，透传给预测/质检/风险/储能"},
                "battery_capacity": {"type": "integer", "minimum": 0, "default": 1000, "units": "kWh",
                                     "description": "透传给储能优化，避免回落到默认 1000"},
                "battery_power": {"type": "integer", "minimum": 0, "default": 500, "units": "kW",
                                  "description": "透传给储能优化，避免回落到默认 500"},
                "efficiency": {"type": "number", "minimum": 50, "maximum": 100, "default": 90, "units": "%"},
                "initial_soc": {"type": "number", "minimum": 0, "maximum": 100, "default": 50, "units": "%"},
                "load_ratio": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.3},
                "load_type": {"type": "string", "enum": ["fixed", "industrial", "commercial"], "default": "industrial"},
                "province": {"type": "string", "description": "电价省份，默认按坐标反查"},
            },
            "required": [],
        },
        "units": "无",
    },
    "confirm_action": {
        "summary": "人工确认高风险动作（设备控制/高压/远程关停等）——本项目仅提示，不执行真实控制",
        "params": {
            "type": "object",
            "properties": {
                "action_type": {"type": "string", "description": "derated_op / remote_shutdown / device_control 等"},
                "reason": {"type": "string"},
            },
            "required": ["action_type"],
        },
        "units": "无",
    },
}


def list_tool_schemas() -> Dict[str, dict]:
    """供 /api/agent/tools 注册表拉取（调试面板用）。"""
    return {
        name: {
            **schema,
            "timeout_s": TOOL_TIMEOUTS.get(name, 60),
        }
        for name, schema in TOOL_SCHEMAS.items()
    }