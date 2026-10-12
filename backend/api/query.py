"""
AI 智能问答接口
- 接入外部 LLM API（兼容 OpenAI 格式），支持自定义 API Key / Base URL / 模型名
- 自动注入光伏数据上下文 + 模型预测结果，对 AI 回答做二次校验
"""
import os
import json
import time
import threading
import httpx
import numpy as np
import pandas as pd
from fastapi import APIRouter, Cookie, Header
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils.data_loader import load_pv_data, get_data_files, get_date_range
from utils.predictor import parse_pv_filename, predict_pv, predict_cnn_lstm_model, get_safe_name
from backend.api.sites import _require_user

router = APIRouter()

# 模型预测结果缓存，避免每次对话都重新推理
_model_ctx_cache: Dict = {}
_model_ctx_lock = threading.Lock()
_CACHE_TTL = 300  # 5分钟过期

# ── 配置持久化 ──────────────────────────────────────────
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ai_config.json')

# 平台提供的预设模型（聊天栏直接选用；api_key 一律走环境变量 DEEPSEEK_API_KEY）
PRESETS: List[Dict[str, str]] = [
    {
        'id': 'deepseek-flash',
        'label': 'DeepSeek Flash',
        'vendor': 'DeepSeek',
        'base_url': 'https://api.deepseek.com',
        'model': 'deepseek-flash',
        'hint': '快速问答',
    },
    {
        'id': 'deepseek-chat',
        'label': 'DeepSeek Chat',
        'vendor': 'DeepSeek',
        'base_url': 'https://api.deepseek.com',
        'model': 'deepseek-chat',
        'hint': '通用对话',
    },
    {
        'id': 'deepseek-reasoner',
        'label': 'DeepSeek Reasoner',
        'vendor': 'DeepSeek',
        'base_url': 'https://api.deepseek.com',
        'model': 'deepseek-reasoner',
        'hint': '深度推理',
    },
    {
        'id': 'gpt-4o-mini',
        'label': 'GPT-4o mini',
        'vendor': 'OpenAI',
        'base_url': 'https://api.openai.com/v1',
        'model': 'gpt-4o-mini',
        'hint': '轻量快速',
    },
    {
        'id': 'gpt-4o',
        'label': 'GPT-4o',
        'vendor': 'OpenAI',
        'base_url': 'https://api.openai.com/v1',
        'model': 'gpt-4o',
        'hint': '通用旗舰',
    },
]

def _find_preset(preset_id: str) -> Optional[Dict[str, str]]:
    for p in PRESETS:
        if p['id'] == preset_id:
            return p
    return None

def _load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            return json.load(open(CONFIG_FILE, 'r', encoding='utf-8'))
        except Exception:
            pass
    return {}

def _save_config(cfg: dict):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ── Pydantic 模型 ───────────────────────────────────────
class AIConfig(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 2000
    mode: str = "preset"          # preset | custom
    active_preset: str = ""       # preset id

class ChatMessage(BaseModel):
    role: str  # user / assistant
    content: str

class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []
    pv_file: Optional[str] = None      # 可选：关联站点
    start_date: Optional[str] = None    # 可选：数据范围
    end_date: Optional[str] = None
    use_model: bool = True              # 是否注入模型预测上下文
    ai_mode: Optional[str] = None       # 本条消息使用的模式（preset/custom）
    ai_preset: Optional[str] = None     # 预设模型 id
    # custom 模式下可选的本条覆盖（不写回配置文件）
    ai_base_url: Optional[str] = None
    ai_model: Optional[str] = None

# ── 上下文构建 ──────────────────────────────────────────
def _parse_user_site_key(pv_file: str) -> Optional[int]:
    """`user_site:{id}` / `user:{id}` → site_id；否则 None。"""
    if not pv_file:
        return None
    s = str(pv_file).strip()
    for prefix in ('user_site:', 'user:'):
        if s.startswith(prefix):
            try:
                return int(s.split(':', 1)[1])
            except (ValueError, IndexError):
                return None
    return None


def _build_user_site_data_context(site_id: int, user_id: int,
                                  start_date: str = None, end_date: str = None) -> str:
    """用户电站发电数据摘要（含隐私/电价），作为 AI 上下文。"""
    from utils import site_store
    site = site_store.get_site_readable(int(site_id), int(user_id))
    if not site:
        return "（无权访问该用户电站或电站不存在）"
    lines = [
        f"站点: {site.get('name')}（用户电站 site_id={site['id']}）",
        f"经纬度: {site.get('lat')}, {site.get('lon')}",
        f"装机: {site.get('kwp')} kWp，倾角 {site.get('tilt')}°，方位 {site.get('azimuth')}°",
        f"隐私: {site.get('visibility', 'private')}"
        + ("，您为只读分享访问" if site.get('read_only') else "，您为所有者"),
    ]
    sp = site.get('prices') or {}
    if any(sp.get(k) is not None for k in ('sharp', 'peak', 'flat', 'valley', 'feed_in')):
        lines.append(
            "已存电价(元/kWh): "
            f"尖{sp.get('sharp')} 峰{sp.get('peak')} 平{sp.get('flat')} "
            f"谷{sp.get('valley')} 上网{sp.get('feed_in')}")
    rng = site_store.generation_range(int(site_id))
    if not rng:
        lines.append("发电数据: 尚未导入")
        return '\n'.join(lines)
    df = site_store.get_generation(int(site_id), start_date, end_date)
    if df is None or len(df) == 0:
        lines.append(f"发电数据范围: {rng[0]} ~ {rng[1]}（{rng[2]} 条）；所选时段无数据")
        return '\n'.join(lines)
    lines.append(f"发电数据范围: {rng[0]} ~ {rng[1]}（累计 {rng[2]} 条）")
    if start_date and end_date:
        lines.append(f"查询时段: {start_date} ~ {end_date}（{len(df)} 条记录）")
    p = df['power_kw'].astype(float)
    lines.append(f"功率统计: 均值={p.mean():.3f}kW, 最大={p.max():.3f}kW, "
                 f"最小={p.min():.3f}kW, 标准差={p.std():.3f}")
    df = df.copy()
    df['date'] = pd.to_datetime(df['ts']).dt.date
    daily = df.groupby('date')['power_kw'].mean()
    lines.append(f"日均功率: {daily.mean():.3f}kW（共 {len(daily)} 天）")
    # 轻量异常提示，便于 AI 分析问题
    kwp = float(site.get('kwp') or 0) or 1.0
    over = int((p > kwp * 1.2).sum())
    if over:
        lines.append(f"数据异常提示: {over} 条记录功率 > 1.2×装机（可能单位错误）")
    zero_days = int((daily <= 0.001).sum())
    if zero_days:
        lines.append(f"数据异常提示: {zero_days} 天日均功率≈0（可能停机或漏传）")
    return '\n'.join(lines)


def _build_user_site_model_context(site_id: int, user_id: int) -> str:
    """用户电站 hybrid 残差模型状态（含 config.pkl 指标）。"""
    from utils import hybrid_model as hm
    from utils import site_store
    site = site_store.get_site_readable(int(site_id), int(user_id))
    if not site:
        return "（无权访问该用户电站或电站不存在）"
    trained = hm.has_trained_model(int(user_id), int(site_id))
    rng = site_store.generation_range(int(site_id))
    lines = [f"混合模型: {'已训练 hybrid 残差修正（物理基准 + ML）' if trained else '尚未训练'}"]
    if rng:
        lines.append(f"训练可用数据: {rng[2]} 条，{rng[0]} ~ {rng[1]}")
    else:
        lines.append("训练可用数据: 无（请先导入发电数据）")
    if trained:
        try:
            import pickle
            cfg_path = os.path.join(hm.hybrid_model_dir(user_id, site_id), 'config.pkl')
            if os.path.exists(cfg_path):
                meta = pickle.load(open(cfg_path, 'rb'))
                m = meta.get('metrics') or {}
                if m:
                    lines.append(
                        "验证指标: "
                        f"RMSE物理={m.get('rmse_physical_kw')}kW, "
                        f"RMSE混合={m.get('rmse_hybrid_kw')}kW, "
                        f"MAE={m.get('mae_hybrid_kw')}kW, "
                        f"改善={m.get('improvement_pct')}%")
                if meta.get('trained_at'):
                    lines.append(f"训练时间: {meta['trained_at']}")
        except Exception:
            pass
        lines.append("可用于未来天气预报下的发电预测与收益测算。")
    else:
        lines.append("可在「预测 → 混合预测」页启动训练。")
    return '\n'.join(lines)


def _build_data_context(pv_file: str, start_date: str = None, end_date: str = None,
                        user_id: Optional[int] = None) -> str:
    """从光伏数据中提取统计摘要，作为 AI 上下文"""
    try:
        site_id = _parse_user_site_key(pv_file)
        if site_id is not None:
            if user_id is None:
                return "（未登录，无法读取用户电站）"
            return _build_user_site_data_context(site_id, user_id, start_date, end_date)

        df = load_pv_data(pv_file)
        if df is None or len(df) == 0:
            return "（无法加载数据）"

        info = parse_pv_filename(pv_file)
        lines = [
            f"站点: {pv_file}",
            f"纬度: {info.get('latitude','N/A')}, 经度: {info.get('longitude','N/A')}",
            f"系统规模: {info.get('system_size','N/A')}, 组件: {info.get('module_type','N/A')}",
            f"安装倾角: {info.get('install_angle','N/A')}, 年份范围: {info.get('year_range','N/A')}",
        ]

        # 日期范围
        try:
            min_d, max_d = get_date_range(pv_file)
            lines.append(f"数据范围: {min_d} ~ {max_d}")
        except Exception:
            pass

        # 筛选指定时间段
        if start_date and end_date:
            df['DATATIME'] = pd.to_datetime(df['DATATIME'])
            mask = (df['DATATIME'].dt.date >= pd.to_datetime(start_date).date()) & \
                   (df['DATATIME'].dt.date <= pd.to_datetime(end_date).date())
            df_sub = df[mask]
            lines.append(f"查询时段: {start_date} ~ {end_date} ({len(df_sub)} 条记录)")
        else:
            df_sub = df

        # 功率统计
        power_col = None
        for c in df_sub.columns:
            if 'POWER' in c.upper() or 'power' in c.lower():
                power_col = c
                break

        if power_col:
            p = df_sub[power_col].astype(float)
            lines.append(f"功率统计: 均值={p.mean():.2f}kW, 最大={p.max():.2f}kW, 最小={p.min():.2f}kW, 标准差={p.std():.2f}")
            # 日均发电量
            if 'DATATIME' in df_sub.columns:
                df_tmp = df_sub.copy()
                df_tmp['date'] = pd.to_datetime(df_tmp['DATATIME']).dt.date
                daily = df_tmp.groupby('date')[power_col].mean()
                lines.append(f"日均功率: {daily.mean():.2f}kW (共{len(daily)}天)")

        # 辐照度统计
        irr_col = None
        for c in df_sub.columns:
            cu = c.upper().replace(' ','')
            if 'IRRADIANCE' in cu or 'IRR' in cu:
                irr_col = c
                break
        if irr_col:
            g = df_sub[irr_col].astype(float)
            lines.append(f"辐照度统计: 均值={g.mean():.1f}W/m², 最大={g.max():.1f}W/m²")

        # 温度统计
        temp_col = None
        for c in df_sub.columns:
            cu = c.upper()
            if 'TEMP' in cu and 'TEMPER' in cu:
                temp_col = c
                break
            if 'TEMP' in cu:
                temp_col = c
        if temp_col:
            t = df_sub[temp_col].astype(float)
            lines.append(f"温度统计: 均值={t.mean():.1f}°C, 最高={t.max():.1f}°C, 最低={t.min():.1f}°C")

        return '\n'.join(lines)
    except Exception as e:
        return f"（数据上下文加载失败: {e}）"


def _build_model_context(pv_file: str, start_date: str = None, end_date: str = None,
                         user_id: Optional[int] = None) -> str:
    """遍历站点所有已训练模型，注入预测指标到 AI 上下文（5分钟缓存）"""
    site_id = _parse_user_site_key(pv_file)
    if site_id is not None:
        if user_id is None:
            return "（未登录，无法读取用户电站模型）"
        cache_key = f"user_site:{site_id}|{user_id}|hybrid"
        now = time.time()
        with _model_ctx_lock:
            cached = _model_ctx_cache.get(cache_key)
            if cached and (now - cached['ts'] < _CACHE_TTL):
                return cached['data']
        data = _build_user_site_model_context(site_id, user_id)
        with _model_ctx_lock:
            _model_ctx_cache[cache_key] = {'ts': now, 'data': data}
        return data

    cache_key = f"{pv_file}|{start_date or 'auto'}|{end_date or 'auto'}"
    now = time.time()
    with _model_ctx_lock:
        cached = _model_ctx_cache.get(cache_key)
        if cached and (now - cached['ts'] < _CACHE_TTL):
            return cached['data']

    try:
        base_name = get_safe_name(pv_file)
        site_model_dir = os.path.join('models', base_name)

        if not os.path.isdir(site_model_dir):
            return "（该站点未训练任何模型）"

        # 扫描所有模型目录
        available_models = []
        for model_name in os.listdir(site_model_dir):
            m_dir = os.path.join(site_model_dir, model_name)
            config_path = os.path.join(m_dir, 'config.pkl')
            if os.path.isdir(m_dir) and os.path.exists(config_path):
                available_models.append(model_name)

        if not available_models:
            return "（该站点未训练任何模型）"

        # 使用最近几天的数据做预测
        if not start_date or not end_date:
            try:
                min_d, max_d = get_date_range(pv_file)
                end_date = str(max_d)
                import datetime
                start_dt = max_d - datetime.timedelta(days=7)
                start_date = str(start_dt)
            except Exception:
                return "（无法确定预测日期范围）"

        # 遍历每个模型，收集指标
        all_lines = [f"该站点已训练 {len(available_models)} 个模型: {', '.join(available_models)}",
                     f"预测时段: {start_date} ~ {end_date}"]

        model_labels = {
            'iid_transformer_lstm': 'IID-Transformer-LSTM',
            'cnn_lstm': 'CNN-LSTM',
        }

        for model_name in available_models:
            label = model_labels.get(model_name, model_name)
            try:
                if model_name == 'cnn_lstm':
                    result, error = predict_cnn_lstm_model(
                        pv_file, start_date, end_date, mode='historical')
                else:
                    result, error = predict_pv(
                        pv_file, start_date, end_date,
                        model_key=model_name, mode='historical')

                if error or result is None or len(result) == 0:
                    all_lines.append(f"\n【{label}】预测失败: {error or '结果为空'}")
                    continue

                y_true = result['POWER_true'].dropna() if 'POWER_true' in result.columns else None
                y_pred = result['POWER_pred']

                all_lines.append(f"\n【{label}】")
                all_lines.append(f"  样本数: {len(result)}")

                if y_true is not None and len(y_true) > 0:
                    mae = float(np.mean(np.abs(y_true - y_pred)))
                    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
                    mask = np.abs(y_true) > 0.01
                    mape = float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / (y_true[mask] + 1e-8))) * 100) if mask.sum() > 0 else 0
                    r2 = float(1 - np.sum((y_true - y_pred) ** 2) / (np.sum((y_true - y_true.mean()) ** 2) + 1e-8))

                    all_lines.append(f"  MAE={mae:.3f}, RMSE={rmse:.3f}, MAPE={mape:.1f}%, R²={r2:.4f}")
                    all_lines.append(f"  真实功率: 均值={float(y_true.mean()):.2f}kW, 峰值={float(y_true.max()):.2f}kW")
                    all_lines.append(f"  预测功率: 均值={float(y_pred.mean()):.2f}kW, 峰值={float(y_pred.max()):.2f}kW")

                    # 最近6小时趋势（省 token）
                    recent = result.tail(6)
                    trend_parts = []
                    for _, row in recent.iterrows():
                        t = str(row['DATATIME'])[5:16]
                        yt = f"{row['POWER_true']:.1f}" if 'POWER_true' in row and not pd.isna(row['POWER_true']) else "N/A"
                        yp = f"{row['POWER_pred']:.1f}"
                        trend_parts.append(f"{t}={yt}/{yp}")
                    all_lines.append(f"  近6小时(真实/预测): {' | '.join(trend_parts)}")
            except Exception as e:
                all_lines.append(f"\n【{label}】加载异常: {e}")

        result_str = '\n'.join(all_lines)
        with _model_ctx_lock:
            _model_ctx_cache[cache_key] = {'ts': time.time(), 'data': result_str}
        return result_str
    except Exception as e:
        return f"（模型上下文加载失败: {e}）"


def _build_system_prompt(data_ctx: str, model_ctx: str, kb_ctx: str = '',
                         has_evidence: bool = False) -> str:
    """构建系统提示词（M3.4：A/B/C 三类上下文 + 证据约束规则）"""
    from backend.utils.evidence_policy import format_kb_rules
    kb_section = ''
    if has_evidence:
        kb_section = f"""
【知识库资料】
以下是系统知识库检索到的证据片段（可能与问题相关，需先核对地区与时间）：
{kb_ctx or '（无）'}
"""
    return f"""你是一个光伏发电功率预测系统的AI助手，专门解答光伏数据、模型预测和系统使用相关的问题。

你可以参考以下真实数据上下文来回答用户问题：

【A 类：电站数据上下文】
{data_ctx}

【B 类：模型预测上下文】
{model_ctx}
{kb_section}
回答要求：
1. 基于提供的数据上下文回答，如果数据不足以回答，说明需要哪些信息
2. 涉及具体数值时，优先引用上述真实数据和模型预测结果
3. 对光伏功率、辐照度、温度等专业术语做简要解释
4. 如用户询问模型准确性，引用 MAE/RMSE/MAPE/R² 等指标
5. 回答使用中文，简洁专业
6. 如涉及公式或计算，给出简要推导过程{format_kb_rules(has_evidence)}"""


# ── AI 结果二次校验 ─────────────────────────────────────
def _post_process(response: str, data_ctx: str, model_ctx: str) -> str:
    """对 AI 回答做二次处理：
    1. 提取回答中提到的数值，与真实数据交叉验证
    2. 在回答末尾附加数据校验注释
    """
    annotations = []

    # 提取真实数据中的关键数值
    import re

    # 检查功率范围
    power_match = re.search(r'功率统计: 均值=([\d.]+)kW.*?最大=([\d.]+)kW', data_ctx)
    if power_match:
        true_mean = float(power_match.group(1))
        true_max = float(power_match.group(2))

        # 在回答中查找 AI 提到的功率数值
        ai_numbers = re.findall(r'(\d+\.?\d*)\s*kW', response)
        suspicious = []
        for num_str in ai_numbers:
            num = float(num_str)
            # 如果 AI 提到的值超出真实范围 2 倍以上，标记可疑
            if num > true_max * 2 and num > 100:
                suspicious.append(f"{num_str}kW（真实峰值仅{true_max:.1f}kW）")
            elif num < 0:
                suspicious.append(f"{num_str}kW（功率不应为负）")

        if suspicious:
            annotations.append(f"⚠️ 数据校验: 回答中的 {', '.join(suspicious)} 可能不准确")

    # 检查模型指标
    metric_match = re.search(r'MAE=([\d.]+).*?RMSE=([\d.]+).*?R²=([\d.]+)', model_ctx)
    if metric_match and ('MAE' in response or 'RMSE' in response or 'R²' in response or 'R2' in response):
        true_mae = float(metric_match.group(1))
        true_rmse = float(metric_match.group(2))
        true_r2 = float(metric_match.group(3))

        # 检查 AI 说的指标是否大致吻合
        ai_mae = re.findall(r'MAE[=: ]+([\d.]+)', response, re.I)
        if ai_mae:
            ai_val = float(ai_mae[0])
            if abs(ai_val - true_mae) / (true_mae + 1e-8) > 0.5:
                annotations.append(f"⚠️ 指标校验: MAE 实际为 {true_mae:.3f}，回答中为 {ai_mae[0]}")

    if annotations:
        response += "\n\n---\n**数据校验注释:**\n" + "\n".join(annotations)

    return response


# ── API 接口 ────────────────────────────────────────────
@router.get("/config")
async def get_ai_config():
    """获取当前AI配置 + 平台预设模型（隐藏完整key）"""
    cfg = _load_config()
    # 安全（PHASE1 清单 T2）：API Key 只从环境变量读取，绝不回读本地明文
    key = (os.environ.get('DEEPSEEK_API_KEY') or '').strip()
    masked = '****' + key[-4:] if len(key) > 12 else ('****' if key else '')
    mode = cfg.get('mode', 'preset')
    active_preset = cfg.get('active_preset', '') or (PRESETS[0]['id'] if mode == 'preset' else '')
    if mode == 'preset' and not _find_preset(active_preset):
        active_preset = PRESETS[0]['id']
    return {
        'success': True,
        'data': {
            'api_key': masked,
            'has_key': bool(key),
            'base_url': cfg.get('base_url', 'https://api.openai.com/v1'),
            'model': cfg.get('model', 'gpt-4o-mini'),
            'temperature': cfg.get('temperature', 0.3),
            'max_tokens': cfg.get('max_tokens', 2000),
            'mode': mode if mode in ('preset', 'custom') else 'preset',
            'active_preset': active_preset,
            'presets': PRESETS,
        }
    }


@router.post("/config")
async def save_ai_config(config: AIConfig):
    """保存AI配置（预设选择或自定义 API）"""
    mode = config.mode if config.mode in ('preset', 'custom') else 'preset'
    active_preset = config.active_preset or ''
    if mode == 'preset':
        if not _find_preset(active_preset):
            active_preset = PRESETS[0]['id']
    # 安全（PHASE1 清单 T2）：API Key 不写入本地文件；提交时仅注入当前进程环境变量
    if config.api_key:
        os.environ['DEEPSEEK_API_KEY'] = config.api_key
    cfg = {
        'base_url': config.base_url,
        'model': config.model,
        'temperature': config.temperature,
        'max_tokens': config.max_tokens,
        'mode': mode,
        'active_preset': active_preset if mode == 'preset' else '',
    }
    _save_config(cfg)
    return {'success': True, 'message': '配置已保存（API Key 仅注入服务端环境变量，不写入本地文件）'}


def _resolve_ai_settings(cfg: dict, request: 'ChatRequest') -> dict:
    """根据配置 + 本次请求，解析实际使用的 API 参数"""
    mode = request.ai_mode or cfg.get('mode', 'preset')
    if mode not in ('preset', 'custom'):
        mode = cfg.get('mode', 'preset') or 'preset'

    temperature = float(cfg.get('temperature', 0.3))
    max_tokens = int(cfg.get('max_tokens', 2000))
    # 安全（PHASE1 清单 T2）：Key 只走环境变量，本地文件即使遗留明文也不使用
    api_key = (os.environ.get('DEEPSEEK_API_KEY') or '').strip()

    if mode == 'preset':
        preset_id = request.ai_preset or cfg.get('active_preset') or PRESETS[0]['id']
        preset = _find_preset(preset_id) or PRESETS[0]
        return {
            'mode': 'preset',
            'api_key': api_key,
            'base_url': preset['base_url'],
            'model': preset['model'],
            'temperature': temperature,
            'max_tokens': max_tokens,
            'preset_id': preset['id'],
            'label': preset['label'],
        }

    return {
        'mode': 'custom',
        'api_key': api_key,
        'base_url': request.ai_base_url or cfg.get('base_url', 'https://api.openai.com/v1'),
        'model': request.ai_model or cfg.get('model', 'gpt-4o-mini'),
        'temperature': temperature,
        'max_tokens': max_tokens,
        'preset_id': '',
        'label': request.ai_model or cfg.get('model', 'gpt-4o-mini'),
    }


async def _do_chat(request: ChatRequest, user_id: Optional[int] = None) -> dict:
    """核心对话逻辑（供 /chat 和 /sessions/{id}/message 复用）"""
    cfg = _load_config()
    ai = _resolve_ai_settings(cfg, request)
    api_key = ai['api_key']

    if not api_key:
        hint = '请在聊天栏「模型」→「自定义 API」中填写 API Key' if ai['mode'] == 'custom' else \
               '未配置 API Key，请先在聊天栏模型菜单中配置'
        return {
            'success': False,
            'error': hint,
        }

    base_url = ai['base_url']
    model = ai['model']
    temperature = ai['temperature']
    max_tokens = ai['max_tokens']

    # 构建上下文（同步阻塞函数放到线程池，避免阻塞 asyncio）
    data_ctx = "（未关联站点数据）"
    model_ctx = "（未使用模型预测）"

    if request.pv_file:
        import asyncio
        loop = asyncio.get_event_loop()
        uid_for_ctx = user_id
        data_ctx = await loop.run_in_executor(
            None, lambda: _build_data_context(
                request.pv_file, request.start_date, request.end_date, uid_for_ctx)
        )
        if request.use_model:
            model_ctx = await loop.run_in_executor(
                None, lambda: _build_model_context(
                    request.pv_file, request.start_date, request.end_date, uid_for_ctx)
            )

    # 检索知识库（RAG）：混合检索（M3.3）→ 证据过滤与拒答（M3.4）→ 回退旧关键词检索
    import asyncio
    kb_hits = []
    kb_ctx = ''
    refusal = None
    try:
        loop = asyncio.get_event_loop()
        raw_hits = []
        try:
            from backend.utils.rag_retriever import Retriever
            raw_hits = await loop.run_in_executor(
                None, lambda: Retriever.instance().retrieve(request.message, 8))
        except Exception:
            raw_hits = []
        if raw_hits:
            from backend.utils.evidence_policy import (
                filter_policy_evidence, format_kb_context, refusal_message)
            kept, reason = await loop.run_in_executor(
                None, lambda: filter_policy_evidence(raw_hits, request.message))
            if reason and not kept:
                refusal = refusal_message(reason, request.message)
            else:
                kb_hits = kept
                kb_ctx = format_kb_context(kept)
        else:
            from backend.utils.knowledge_base import search_kb
            kb_hits = await loop.run_in_executor(None, search_kb, request.message)
            if kb_hits:
                kb_ctx = '\n'.join(
                    f"[{i}] 《{h['title']}》: {h['snippet']}"
                    for i, h in enumerate(kb_hits, 1))
    except Exception:
        kb_hits = kb_hits or []

    # M3.4 拒答：证据不满足条件时直接返回标准语，不调用 LLM（省 Token、防编造）
    if refusal:
        return {
            'success': True,
            'response': refusal,
            'elapsed': 0,
            'model': model,
            'refused': True,
            'context_summary': {
                'data': data_ctx[:200] + '...' if len(data_ctx) > 200 else data_ctx,
                'model': model_ctx[:200] + '...' if len(model_ctx) > 200 else model_ctx,
            },
        }

    system_prompt = _build_system_prompt(data_ctx, model_ctx, kb_ctx,
                                         has_evidence=bool(kb_ctx))

    # 构建消息列表
    messages = [{"role": "system", "content": system_prompt}]
    for msg in request.history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": request.message})

    # 调用 LLM API
    try:
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'model': model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }

        # 兼容 OpenAI / Azure / 国产 API
        chat_url = base_url.rstrip('/')
        if not chat_url.endswith('/chat/completions'):
            if chat_url.endswith('/v1'):
                chat_url += '/chat/completions'
            elif '/v1' not in chat_url:
                chat_url += '/v1/chat/completions'
            else:
                chat_url += '/chat/completions'

        start_ts = time.time()
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(chat_url, headers=headers, json=payload)

        elapsed = round(time.time() - start_ts, 2)

        if resp.status_code != 200:
            err_body = resp.text[:500]
            return {
                'success': False,
                'error': f'API调用失败({resp.status_code}): {err_body}',
            }

        data = resp.json()
        msg = data['choices'][0]['message']
        ai_response = msg.get('content', '')

        # 提取思考过程
        thinking = ''
        if msg.get('reasoning_content'):
            thinking = msg['reasoning_content']
        import re as _re
        for tag in ('think', 'thinking'):
            m = _re.search(rf'<{tag}[^>]*>(.*?)</{tag}>', ai_response, _re.DOTALL | _re.IGNORECASE)
            if m:
                thinking = (thinking + '\n\n' + m.group(1).strip()).strip() if thinking else m.group(1).strip()
                ai_response = _re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', ai_response, flags=_re.DOTALL | _re.IGNORECASE).strip()

        ai_response = _post_process(ai_response, data_ctx, model_ctx)

        result = {
            'success': True,
            'response': ai_response,
            'elapsed': elapsed,
            'model': model,
            'context_summary': {
                'data': data_ctx[:200] + '...' if len(data_ctx) > 200 else data_ctx,
                'model': model_ctx[:200] + '...' if len(model_ctx) > 200 else model_ctx,
            }
        }
        if thinking:
            result['thinking'] = thinking
        if kb_hits:
            result['kb_sources'] = [
                {'id': h['id'], 'title': h['title'], 'path': h['path'],
                 'snippet': h['snippet']} for h in kb_hits]
        return result

    except httpx.TimeoutException:
        return {'success': False, 'error': 'API调用超时，请检查网络或减少 max_tokens'}
    except httpx.ConnectError:
        return {'success': False, 'error': f'无法连接到 {base_url}，请检查 Base URL 或网络'}
    except KeyError:
        return {'success': False, 'error': 'API返回格式异常'}
    except Exception as e:
        return {'success': False, 'error': f'调用失败: {str(e)}'}


@router.get("/sites")
async def get_sites_for_chat(
    access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """站点列表（全局演示库 + 本人/已分享用户电站）。"""
    try:
        user = _require_user(access_token, authorization)
        files = get_data_files()
        sites = []
        for f in files:
            info = parse_pv_filename(f)
            sites.append({
                'filename': f,
                'display_name': f.replace('.csv', ''),
                'latitude': info.get('latitude', ''),
                'longitude': info.get('longitude', ''),
                'source': 'demo',
            })
        from utils import site_store
        for s in site_store.list_sites(user['id'], include_shared=True):
            sites.append({
                'filename': f"user_site:{s['id']}",
                'display_name': s['name'] + ('（分享）' if s.get('read_only') else ''),
                'latitude': str(s['lat']),
                'longitude': str(s['lon']),
                'source': 'user_site',
                'site_id': s['id'],
                'visibility': s.get('visibility', 'private'),
                'read_only': s.get('read_only', False),
            })
        return {'success': True, 'data': sites}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# ── 会话管理 ──────────────────────────────────────────
SESSIONS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ai_sessions.json')
_sessions_lock = threading.Lock()

def _load_sessions() -> list:
    if os.path.exists(SESSIONS_FILE):
        try:
            return json.load(open(SESSIONS_FILE, 'r', encoding='utf-8'))
        except Exception:
            pass
    return []

def _save_sessions(sessions: list):
    with open(SESSIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)

def _find_owned_session(sessions: list, session_id: str, user_id: int):
    """按 id + 归属用户查找会话；user_id 不匹配视同不存在，防止越权枚举"""
    for s in sessions:
        if s.get('id') == session_id and s.get('user_id') == user_id:
            return s
    return None

def _migrate_ownerless_sessions() -> bool:
    """弱迁移（幂等）：隔离功能上线前的存量会话没有 user_id 字段，
    统一标记为 None（不属于任何登录用户，任何人列表中不可见，数据不删除）。"""
    sessions = _load_sessions()
    changed = False
    for s in sessions:
        if 'user_id' not in s:
            s['user_id'] = None
            changed = True
    if changed:
        _save_sessions(sessions)
    return changed

@router.get("/sessions")
async def list_sessions(access_token: Optional[str] = Cookie(None),
                        authorization: Optional[str] = Header(None)):
    """列出当前登录用户的会话（按用户隔离）"""
    user = _require_user(access_token, authorization)
    with _sessions_lock:
        _migrate_ownerless_sessions()
        sessions = _load_sessions()
    # 仅返回属于当前用户的会话，按 updated_at 倒序
    mine = [s for s in sessions if s.get('user_id') == user['id']]
    mine.sort(key=lambda s: s.get('updated_at', ''), reverse=True)
    # 返回精简版（不含完整消息）
    slim = [{
        'id': s['id'],
        'title': s.get('title', '新对话'),
        'updated_at': s.get('updated_at', s.get('created_at', '')),
        'message_count': len(s.get('messages', [])),
        'pv_file': s.get('pv_file', ''),
    } for s in mine]
    return {'success': True, 'data': slim}

@router.post("/sessions")
async def create_session(access_token: Optional[str] = Cookie(None),
                         authorization: Optional[str] = Header(None)):
    """创建新会话（归属当前登录用户）"""
    user = _require_user(access_token, authorization)
    import uuid
    import datetime
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    session = {
        'id': str(uuid.uuid4()),
        'user_id': user['id'],
        'title': '新对话',
        'created_at': now,
        'updated_at': now,
        'messages': [],
        'pv_file': '',
        'start_date': '',
        'end_date': '',
        'use_model': True,
    }
    with _sessions_lock:
        sessions = _load_sessions()
        sessions.append(session)
        _save_sessions(sessions)
    return {'success': True, 'data': session}

@router.get("/sessions/{session_id}")
async def get_session(session_id: str,
                      access_token: Optional[str] = Cookie(None),
                      authorization: Optional[str] = Header(None)):
    """获取会话详情（含完整消息），仅属主可访问"""
    user = _require_user(access_token, authorization)
    with _sessions_lock:
        sessions = _load_sessions()
        session = _find_owned_session(sessions, session_id, user['id'])
    if not session:
        return {'success': False, 'error': '会话不存在'}
    return {'success': True, 'data': session}

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str,
                         access_token: Optional[str] = Cookie(None),
                         authorization: Optional[str] = Header(None)):
    """删除会话，仅属主可操作"""
    user = _require_user(access_token, authorization)
    with _sessions_lock:
        sessions = _load_sessions()
        before = len(sessions)
        sessions = [s for s in sessions
                    if not (s.get('id') == session_id and s.get('user_id') == user['id'])]
        if len(sessions) == before:
            return {'success': False, 'error': '会话不存在'}
        _save_sessions(sessions)
    return {'success': True}

@router.post("/sessions/{session_id}/message")
async def send_session_message(session_id: str, request: ChatRequest,
                               access_token: Optional[str] = Cookie(None),
                               authorization: Optional[str] = Header(None)):
    """在指定会话中发送消息（自动管理 history），仅属主可操作"""
    user = _require_user(access_token, authorization)
    import datetime
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 读取当前会话（用于构造 history）
    with _sessions_lock:
        sessions = _load_sessions()
        session = _find_owned_session(sessions, session_id, user['id'])
        if not session:
            return {'success': False, 'error': '会话不存在'}

        # 合并上下文
        pv_file = request.pv_file or session.get('pv_file', '')
        start_date = request.start_date or session.get('start_date', '')
        end_date = request.end_date or session.get('end_date', '')
        use_model = request.use_model if request.use_model is not None else session.get('use_model', True)

        # 先保存用户消息（重要！必须在跑 AI 之前持久化）
        user_msg = {'role': 'user', 'content': request.message, 'time': now}
        session['messages'].append(user_msg)
        session['pv_file'] = pv_file
        session['start_date'] = start_date
        session['end_date'] = end_date
        session['use_model'] = use_model
        session['updated_at'] = now
        # 自动生成标题（如果还是默认名）
        if session.get('title') in ('新对话', None, ''):
            session['title'] = request.message[:25] + ('...' if len(request.message) > 25 else '')
        _save_sessions(sessions)

        # 构造 history（不含刚加的 user 消息，因为 chat 内部会再加一次）
        history_for_chat = [{'role': m['role'], 'content': m['content']} for m in session['messages'][:-1]]

    # 调用 AI（不在锁内，避免阻塞）
    chat_request = ChatRequest(
        message=request.message,
        history=history_for_chat,
        pv_file=pv_file or None,
        start_date=start_date or None,
        end_date=end_date or None,
        use_model=use_model,
        ai_mode=request.ai_mode,
        ai_preset=request.ai_preset,
        ai_base_url=request.ai_base_url,
        ai_model=request.ai_model,
    )
    result = await _do_chat(chat_request, user_id=user['id'])

    # 保存 AI 回复（再次校验归属，防止竞态下会话被删/转移）
    with _sessions_lock:
        sessions = _load_sessions()
        session = _find_owned_session(sessions, session_id, user['id'])
        if session:
            if result.get('success'):
                ai_msg = {
                    'role': 'assistant',
                    'content': result['response'],
                    'time': now,
                }
                if result.get('thinking'):
                    ai_msg['thinking'] = result['thinking']
                if result.get('kb_sources'):
                    ai_msg['kb_sources'] = result['kb_sources']
                session['messages'].append(ai_msg)
            session['updated_at'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            _save_sessions(sessions)

    return result
