import time
import sys
import os
import uuid
import threading

import numpy as np
import pandas as pd
import math
from fastapi import APIRouter, HTTPException, Cookie, Header
from pydantic import BaseModel
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils.data_loader import load_pv_data
from utils.predictor import (
    predict_pv,
    train_pv_models,
    predict_cnn_lstm_model,
    train_cnn_lstm_model,
    evaluate_model,
    parse_pv_filename,
)
from utils import site_store
from utils import hybrid_model as hm
from utils.weather.forecast import fetch_open_meteo_forecast
from utils.weather import store as wstore
from backend.api.sites import _require_user

router = APIRouter()


def compute_metrics_like_benchmark(y_true_kw, y_pred_kw, ghi, cap_kwp):
    """与 evaluation/benchmark.py 的 compute_day_metrics 完全同口径的指标计算。

    - 白天样本：day_mask = (ghi > 50) & (power_true > capacity_kwp * 0.01)
    - R² = 1 - SS_res / SS_tot（SS_tot = Σ(yt - mean(yt))²）
    - nRMSE = RMSE / capacity_kwp
    返回 dict 或 None（无有效样本时）。
    """
    yt = np.asarray(y_true_kw, dtype=float)
    yp = np.asarray(y_pred_kw, dtype=float)
    g = np.asarray(ghi, dtype=float)
    mask = ~(np.isnan(yt) | np.isnan(yp))
    yt, yp, g = yt[mask], yp[mask], g[mask]
    if len(yt) == 0:
        return None
    mae = float(np.mean(np.abs(yt - yp)))
    rmse = float(np.sqrt(np.mean((yt - yp) ** 2)))
    nrmse = rmse / max(float(cap_kwp), 1e-9)
    mbe = float(np.mean(yp - yt))
    ss_tot = float(np.sum((yt - np.mean(yt)) ** 2))
    if ss_tot > 1e-12:
        r2 = 1.0 - float(np.sum((yt - yp) ** 2)) / ss_tot
    else:
        r2 = None
    day_mask = (g > 50) & (yt > float(cap_kwp) * 0.01)
    if day_mask.sum() > 0:
        day_mape = float(np.mean(np.abs((yt[day_mask] - yp[day_mask]) / yt[day_mask]) * 100))
    else:
        day_mape = None
    return {
        'MAE_kW': round(mae, 4),
        'RMSE_kW': round(rmse, 4),
        'nRMSE': round(nrmse, 4),
        '白天MAPE_pct': round(day_mape, 2) if day_mape is not None else None,
        'R2': round(r2, 4) if r2 is not None else None,
        'MBE_kW': round(mbe, 4),
        '样本数': int(len(yt)),
        '白天样本数': int(day_mask.sum()),
    }


class PredictRequest(BaseModel):
    pv_file: str
    start_date: str
    end_date: str
    model_type: str = "iid_transformer_lstm"
    mode: str = "historical"

class TrainRequest(BaseModel):
    pv_file: str
    model_type: str = "iid_transformer_lstm"
    d_model: int = 64
    transformer_layers: int = 2
    lstm_layers: int = 2
    attention_heads: int = 8
    lstm_units: int = 64
    seq_len: int = 24
    epochs: int = 50
    batch_size: int = 32
    learning_rate: float = 0.001


def _result_to_predictions(result: pd.DataFrame, pv_file: str,
                           model_key: str = 'iid_transformer_lstm'):
    """将 predict 返回的 DataFrame 转为 JSON 安全的 list[dict]，NaN -> None；
    同时计算汇总统计与 90% 置信区间。所有功率字段均为 kW（真实/预测），发电量为 kWh。

    返回 (preds, summary)：
      preds   - {DATATIME, POWER_true, POWER_pred, POWER_lower, POWER_upper} 列表
      summary - 含 capacity_kwp / energy_kwh / confidence / uncertainty / warning 等
    """
    from utils.units import (parse_capacity_kwp, power_range_check,
                             energy_kwh_from_power_kw)

    t_kw = pd.to_numeric(result['POWER_true'], errors='coerce')
    p_kw = pd.to_numeric(result['POWER_pred'], errors='coerce')
    tstamps = pd.to_datetime(result['DATATIME'])
    capacity_kwp = parse_capacity_kwp(pv_file)

    # ── 90% 置信区间：白天/夜间分档，用本段历史残差的标准差估计 ──────
    # 白天＝6~18 时（统一口径，避免夜间零值拉低带宽）；历史模式残差可算，
    # 未来模式无真实值 → 用启发式相对带宽（并写入 uncertainty 说明）。
    hour = tstamps.dt.hour.to_numpy(dtype=int)
    day_mask = (hour >= 6) & (hour <= 18)
    resid = t_kw - p_kw
    valid = resid.notna()
    std_day = float(resid[valid & day_mask].std()) if (valid & day_mask).sum() > 5 else None
    std_night = float(resid[valid & ~day_mask].std()) if (valid & ~day_mask).sum() > 5 else None
    if std_day is None and std_night is None:
        # 未来模式/无真实值：启发式带宽（预测功率的 15% + 0.02 kW 底座）
        has_true = bool(valid.any())
        conf_method = '启发式' if not has_true else '历史残差'
        day_band = [np.nan] * len(result)
        night_band = [np.nan] * len(result)
        for i, pv in enumerate(p_kw.to_numpy(dtype=float)):
            base = 0.02 + 0.15 * max(0.0, float(pv)) if not np.isnan(pv) else 0.02
            day_band[i] = night_band[i] = base
    else:
        conf_method = '历史残差(白天/夜间分档)'
        sd = std_day if std_day is not None else (std_night or 0.05)
        sn = std_night if std_night is not None else (std_day or 0.05)
        day_band = [1.645 * sd] * len(result)
        night_band = [1.645 * sn] * len(result)

    preds = []
    for i, row in result.iterrows():
        t_val = row['POWER_true']
        p_val = row['POWER_pred']
        p_float = None if pd.isna(p_val) else float(p_val)
        band = (day_band[i] if day_mask[i] else night_band[i])
        lo = 0.0
        hi = None
        if p_float is not None and not np.isnan(p_float) and not np.isnan(band):
            lo = max(0.0, p_float - band)
            hi = p_float + band
        preds.append({
            'DATATIME': str(pd.to_datetime(row['DATATIME'])),
            'POWER_true': None if pd.isna(t_val) else round(float(t_val), 4),
            'POWER_pred': None if pd.isna(p_val) else round(float(p_val), 4),
            'POWER_lower': round(lo, 4),
            'POWER_upper': None if hi is None else round(hi, 4),
        })

    # ── 评价指标（与 evaluation/benchmark.py 同口径：白天 MAPE / R² / nRMSE）──
    # GHI 从数据库原始表关联（同 pv_file），供白天过滤 (ghi>50 & power>0.01*cap) 使用。
    metrics = None
    try:
        if t_kw.notna().any() and p_kw.notna().any():
            raw = load_pv_data(pv_file)
            if 'GLOBAL_HORIZONTAL_IRRADIANCE' in raw.columns:
                ghi_map = raw[['DATATIME', 'GLOBAL_HORIZONTAL_IRRADIANCE']].copy()
                ghi_map['DATATIME'] = pd.to_datetime(ghi_map['DATATIME'])
                ghi_map = ghi_map.drop_duplicates('DATATIME')
                tmp = pd.DataFrame({'DATATIME': tstamps})
                tmp = tmp.merge(ghi_map, on='DATATIME', how='left')
                ghi_arr = tmp['GLOBAL_HORIZONTAL_IRRADIANCE'].to_numpy(dtype=float)
                metrics = compute_metrics_like_benchmark(
                    t_kw.to_numpy(dtype=float), p_kw.to_numpy(dtype=float),
                    ghi_arr, capacity_kwp)
    except Exception:
        metrics = None

    # ── 汇总统计（POWER_pred / POWER_true 均为 kW）──────────────────
    if p_kw.notna().any():
        avg_kw = float(p_kw.mean())
        peak_kw = float(p_kw.max())
    else:
        avg_kw = 0.0
        peak_kw = 0.0
    energy_kwh = energy_kwh_from_power_kw(p_kw, tstamps)

    # 物理范围校验：预测与真实功率都应处于 [0, capacity_kwp * 1.2]
    over_p, peak_over_p = power_range_check(p_kw.fillna(0).to_numpy(), capacity_kwp)
    over_t, peak_over_t = power_range_check(t_kw.fillna(0).to_numpy(), capacity_kwp)
    warning = None
    if over_p or over_t:
        peak = max(peak_over_p or 0.0, peak_over_t or 0.0)
        warning = (
            f'检测到功率单位或装机容量可能不一致：站点容量 {capacity_kwp} kWp，'
            f'数据峰值 {peak:.2f} kW。请确认原始字段单位是 W 还是 kW。'
        )

    sd = (round(float(std_day), 4) if std_day is not None else None)
    sn = (round(float(std_night), 4) if std_night is not None else None)
    confidence = {
        'level': '90%',
        'method': conf_method,
        'std_day_kw': sd,
        'std_night_kw': sn,
        'note': '置信带 = 预测值 ± 1.645σ（白天 6~18 时 / 夜间分档）。'
                '未来模式无真实值，采用启发式带宽（预测功率 15% + 0.02 kW），仅供参考。'
                if conf_method == '启发式' else
                '置信带 = 预测值 ± 1.645σ，σ 由本段预测区间内白天/夜间残差统计得到（约 90% 覆盖）。'
    }
    uncertainty = {
        'weather': '预测依赖 NWP/历史辐照数据，天气突变（云团过境、阴雨）可直接导致瞬时功率偏差。',
        'missing': '数据缺失或传感器异常时，模型自动跳过缺失时段；缺口超过模型输入窗口将降低连续性预测精度。',
        'extreme': '极端工况（限电、设备故障、清洗/遮挡）不包含在训练分布内，此场景下置信区间不再适用。',
        'advice': '调度决策建议参考置信区间下界做保守估算；储能充放电策略已内置 10% 安全余量。',
    }

    summary = {
        'capacity_kwp': capacity_kwp,
        'energy_kwh': round(float(energy_kwh), 4),
        'avg_power_kw': round(avg_kw, 4),
        'peak_power_kw': round(peak_kw, 4),
        'warning': warning,
        'unit_power': 'kW',
        'unit_energy': 'kWh',
        'confidence': confidence,
        'uncertainty': uncertainty,
        'model_key': model_key,
        'n_samples': int(len(result)),
        'metrics': metrics,
    }
    return preds, summary


@router.post("/predict")
def predict(request: PredictRequest):
    """执行预测：调用 models/ 目录下已训练的真实模型推理"""
    try:
        if request.model_type == 'cnn_lstm':
            result, error = predict_cnn_lstm_model(
                request.pv_file, request.start_date, request.end_date, mode=request.mode)
        else:
            result, error = predict_pv(
                request.pv_file, request.start_date, request.end_date,
                model_key='iid_transformer_lstm', mode=request.mode)

        if error:
            return {'success': False, 'error': error}

        predictions, summary = _result_to_predictions(
            result, request.pv_file, model_key=request.model_type)
        return {
            'success': True,
            'predictions': predictions,
            'summary': summary,
            'count': len(predictions),
            'model_type': request.model_type,
        }
    except FileNotFoundError as e:
        return {'success': False, 'error': f'模型文件不完整：{str(e)}，请重新训练'}
    except Exception as e:
        return {'success': False, 'error': f'预测失败: {str(e)}'}


# ── 训练任务管理（后台线程 + 内存进度存储）─────────────────────
_train_jobs: dict = {}
_train_jobs_lock = threading.Lock()


class _ProgressBar:
    """适配训练函数 progress_bar.progress(float) 的回调对象"""
    def __init__(self, job_id: str):
        self.job_id = job_id

    def progress(self, value: float):
        with _train_jobs_lock:
            if self.job_id in _train_jobs:
                _train_jobs[self.job_id]['progress'] = round(float(value) * 100, 1)


class _StatusText:
    """适配训练函数 status_text.text(str) 的回调对象"""
    def __init__(self, job_id: str):
        self.job_id = job_id

    def text(self, msg: str):
        with _train_jobs_lock:
            if self.job_id in _train_jobs:
                _train_jobs[self.job_id]['message'] = str(msg)


def _run_training(job_id: str, pv_file: str, model_type: str, cfg: dict):
    """后台线程：执行真实训练并更新任务状态"""
    # 同 _run_hybrid_training：压低训练线程优先级，避免抢核饿死 uvicorn 事件循环
    try:
        import ctypes
        hkernel = ctypes.windll.kernel32
        hkernel.SetThreadPriority(hkernel.GetCurrentThread(), -1)  # BELOW_NORMAL
    except Exception:
        pass
    with _train_jobs_lock:
        _train_jobs[job_id]['status'] = 'running'
        _train_jobs[job_id]['message'] = '准备训练...'

    start_ts = time.time()
    try:
        pb = _ProgressBar(job_id)
        st = _StatusText(job_id)

        if model_type == 'cnn_lstm':
            ok = train_cnn_lstm_model(pv_file, cfg, progress_bar=pb, status_text=st)
        else:
            ok = train_pv_models(pv_file, cfg, progress_bar=pb, status_text=st)

        elapsed = round(time.time() - start_ts, 1)

        with _train_jobs_lock:
            if not ok:
                _train_jobs[job_id].update({
                    'status': 'failed',
                    'progress': 100,
                    'error': '训练失败：数据量不足或训练过程出错',
                })
            else:
                _train_jobs[job_id].update({
                    'status': 'done',
                    'progress': 100,
                    'message': f'模型训练完成并已保存（耗时 {elapsed} 秒）',
                    'result': {
                        'success': True,
                        'message': f'模型训练完成并已保存（耗时 {elapsed} 秒）',
                        'model_type': model_type,
                        'elapsed': elapsed,
                        'training_params': {
                            'seq_len': cfg.get('seq_len'),
                            'epochs': cfg.get('epochs'),
                            'batch_size': cfg.get('batch_size'),
                            'learning_rate': cfg.get('lr'),
                        },
                    },
                })
    except Exception as e:
        with _train_jobs_lock:
            _train_jobs[job_id].update({
                'status': 'failed',
                'error': f'训练失败: {str(e)}',
            })


def start_iid_training(pv_file: str, cfg: Optional[dict] = None,
                       auto: bool = False,
                       model_type: str = 'iid_transformer_lstm') -> dict:
    """启动内置数据集模型的后台训练。

    供 REST `/train` 与 MCP `forecast_power`（无模型时自动触发）共用，统一在
    `_train_jobs_lock` 内去重，避免并发重复拉起训练线程。

    auto=True 是「预测时自动触发」的保守模式：该数据集只要存在过任何训练任务
    （含失败）就不再自动重试，防止反复重训打满 CPU；需要重试请显式调 REST 接口。
    """
    try:
        df = load_pv_data(pv_file)
    except Exception as e:
        return {'success': False, 'error': f'无法加载数据: {e}'}
    if df is None or len(df) == 0:
        return {'success': False, 'error': '无法加载数据'}

    # 自动触发走小预算：实测 epochs=5 在 16.6 万行上约 531 秒，
    # 而 forecast_power 超时只有 120 秒，所以只能后台跑、不能同步等。
    merged = {'d_model': 64, 'nhead': 8, 'num_encoder_layers': 2,
              'lstm_hidden': 64, 'lstm_layers': 2, 'seq_len': 24,
              'epochs': 5 if auto else 50, 'batch_size': 32, 'lr': 0.001,
              'patience': 3 if auto else 10, 'dropout': 0.1}
    merged.update(cfg or {})

    with _train_jobs_lock:
        for j in _train_jobs.values():
            if j.get('pv_file') != pv_file or j.get('model_type') != model_type:
                continue
            if auto:
                return {'success': False, 'skipped': True,
                        'error': f"该数据集已有训练任务（状态 {j.get('status')}），"
                                 f"不自动重试；如需重试请调用 POST /api/prediction/train"}
            # pending 也要拦：建任务到线程真正跑起来之间存在窗口
            if j.get('status') in ('pending', 'running'):
                return {'success': False, 'skipped': True, 'error': '该模型正在训练中'}
        job_id = str(uuid.uuid4())
        _train_jobs[job_id] = {
            'job_id': job_id,
            'pv_file': pv_file,
            'model_type': model_type,
            'status': 'pending',
            'progress': 0.0,
            'message': '任务已创建，等待启动...',
            'error': None,
            'result': None,
            'created_at': time.time(),
        }

    threading.Thread(target=_run_training,
                     args=(job_id, pv_file, model_type, merged),
                     daemon=True).start()
    return {'success': True, 'job_id': job_id, 'message': '模型训练任务已启动'}


@router.post("/train")
def train(request: TrainRequest):
    """启动后台训练任务，立即返回 job_id，前端轮询 /train/progress/{job_id}"""
    out = start_iid_training(
        request.pv_file,
        cfg={'d_model': request.d_model,
             'nhead': request.attention_heads,
             'num_encoder_layers': request.transformer_layers,
             'lstm_hidden': request.lstm_units,
             'lstm_layers': request.lstm_layers,
             'seq_len': request.seq_len,
             'epochs': request.epochs,
             'batch_size': request.batch_size,
             'lr': request.learning_rate,
             'patience': 10,
             'dropout': 0.1},
        model_type=request.model_type,
    )
    if out.get('success'):
        return out
    if out.get('skipped'):
        return {'success': False, 'error': out.get('error')}
    return out




@router.get("/train/progress/{job_id}")
def train_progress(job_id: str):
    """查询训练任务进度"""
    with _train_jobs_lock:
        job = _train_jobs.get(job_id)
        if not job:
            return {'success': False, 'error': '训练任务不存在'}
        # 返回副本，避免外部读到正在写入的 dict
        return {
            'success': True,
            'job_id': job_id,
            'status': job['status'],
            'progress': job['progress'],
            'message': job.get('message', ''),
            'error': job.get('error'),
            'result': job.get('result'),
        }


@router.get("/models")
async def list_models():
    """列出可用的预测模型"""
    return [
        {
            "id": "iid_transformer_lstm",
            "name": "IID-Transformer-LSTM",
            "description": "辐照区间分箱+孤立森林+Transformer+LSTM",
            "category": "interval_based"
        },
        {
            "id": "cnn_lstm",
            "name": "CNN-LSTM",
            "description": "卷积神经网络+长短期记忆网络",
            "category": "sequence"
        }
    ]


@router.post("/compare")
def compare_models(request: PredictRequest):
    """多模型对比：两个模型均使用已训练权重真实推理，任一未训练则报错"""
    try:
        start_ts = time.time()
        iid_result, iid_error = predict_pv(
            request.pv_file, request.start_date, request.end_date,
            model_key='iid_transformer_lstm', mode='historical')
        iid_time = round(time.time() - start_ts, 2)

        start_ts = time.time()
        cnn_result, cnn_error = predict_cnn_lstm_model(
            request.pv_file, request.start_date, request.end_date, mode='historical')
        cnn_time = round(time.time() - start_ts, 2)

        if iid_error or cnn_error:
            missing = []
            if iid_error:
                missing.append(f"IID-Transformer-LSTM（{iid_error}）")
            if cnn_error:
                missing.append(f"CNN-LSTM（{cnn_error}）")
            return {
                'success': False,
                'error': '模型对比需要两个模型都已训练：' + '；'.join(missing)
            }

        iid_preds, iid_summary = _result_to_predictions(
            iid_result, request.pv_file, model_key='iid_transformer_lstm')
        cnn_preds, cnn_summary = _result_to_predictions(
            cnn_result, request.pv_file, model_key='cnn_lstm')

        def calc_metrics(preds):
            valid = [(p['POWER_true'], p['POWER_pred']) for p in preds
                     if p['POWER_true'] is not None and p['POWER_pred'] is not None]
            if not valid:
                return {'MAE': 0, 'RMSE': 0, 'MAPE': 0, 'R2': 0}
            yt = np.array([v[0] for v in valid])
            yp = np.array([v[1] for v in valid])
            m = evaluate_model(yt, yp)
            return {
                'MAE': round(float(m['MAE']), 4),
                'RMSE': round(float(m['RMSE']), 4),
                'MAPE': round(float(m['MAPE']), 4),
                'R2': round(float(m['R2']), 4),
            }

        return {
            'success': True,
            'cnn_lstm': {
                'predictions': cnn_preds,
                'metrics': calc_metrics(cnn_preds),
                'time': cnn_time,
                'summary': cnn_summary,
            },
            'iid_transformer_lstm': {
                'predictions': iid_preds,
                'metrics': calc_metrics(iid_preds),
                'time': iid_time,
                'summary': iid_summary,
            },
            'count': len(cnn_preds),
        }
    except Exception as e:
        return {'success': False, 'error': f'模型对比失败: {str(e)}'}


# =============================================================================
# hybrid v2：物理基准 + ML 残差修正（与旧模型并存，互不影响）
# =============================================================================

class HybridTrainRequest(BaseModel):
    site_id: int
    epochs: int = 50
    batch_size: int = 32
    seq_len: int = 12
    learning_rate: float = 0.001


class HybridForecastRequest(BaseModel):
    site_id: int
    forecast_days: int = 7
    start: Optional[str] = None   # 历史重算模式（physical 混合评估）：YYYY-MM-DD
    end: Optional[str] = None


def _safe_num(v):
    """FastAPI 序列化兜底：NaN/inf → 0.0。"""
    try:
        f = float(v)
        return 0.0 if (math.isnan(f) or math.isinf(f)) else round(f, 4)
    except (TypeError, ValueError):
        return 0.0


def _frame_to_curves(frame: pd.DataFrame) -> list:
    rows = []
    for _, r in frame.iterrows():
        rows.append({
            'ts': str(pd.Timestamp(r['ts'])),
            'ghi': _safe_num(r.get('ghi')),
            't2m': _safe_num(r.get('t2m')),
            'ws2m': _safe_num(r.get('ws2m')),
            'poa_global': _safe_num(r.get('poa_global')),
            't_cell': _safe_num(r.get('t_cell')),
            'p_phys_kw': _safe_num(r['p_phys_kw']),
            'residual_kw': _safe_num(r.get('residual_kw', 0.0)),
            'p_final_kw': _safe_num(r['p_final_kw']),
        })
    return rows


# ── 后台训练任务（复用 /train/progress 轮询存储）────────────────────────────

_hybrid_lock = threading.Lock()


def _run_hybrid_training(job_id: str, user_id: int, site_id: int, cfg: dict):
    # 训练是 CPU 密集型，不降级会与 uvicorn 事件循环抢核：
    # 实测 7+ 核满转 → accept 失败 → 8000 端口掉监听、后续请求全部拒绝连接。
    # 把本线程压到 BELOW_NORMAL，保证服务始终能响应。
    try:
        import ctypes
        THREAD_PRIORITY_BELOW_NORMAL = -1
        hkernel = ctypes.windll.kernel32
        hkernel.SetThreadPriority(hkernel.GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL)
    except Exception:
        pass
    with _hybrid_lock:
        _train_jobs[job_id]['status'] = 'running'
        _train_jobs[job_id]['message'] = '准备训练残差修正模型...'
    start_ts = time.time()
    try:
        def cb(stage, frac, message):
            with _hybrid_lock:
                if job_id in _train_jobs:
                    _train_jobs[job_id].update({
                        'progress': round(float(frac) * 100, 1), 'message': str(message)})

        result = hm.train_hybrid_residual(user_id, site_id, cfg, progress_cb=cb)
        elapsed = round(time.time() - start_ts, 1)
        with _hybrid_lock:
            if not result.get('success'):
                _train_jobs[job_id].update({
                    'status': 'failed', 'progress': 100,
                    'error': result.get('reason', '样本不足，无法训练')})
            else:
                _train_jobs[job_id].update({
                    'status': 'done', 'progress': 100,
                    'message': f'混合模型训练完成（耗时 {elapsed} 秒）',
                    'result': {
                        'success': True, 'model_version': 'hybrid_v2',
                        'elapsed': elapsed,
                        'metrics': result['metrics'],
                        'train_range': result['train_range'],
                        'val_range': result['val_range'],
                        'n_rows': result['n_rows'],
                        'trained_at': result['trained_at'],
                    }})
    except Exception as e:
        with _hybrid_lock:
            _train_jobs[job_id].update({'status': 'failed', 'error': f'训练失败: {str(e)}'})


def start_hybrid_training(user_id: int, site_id: int,
                          cfg: Optional[dict] = None,
                          auto: bool = False) -> dict:
    """启动站点混合残差模型后台训练。

    供 REST 路由 `/hybrid/train` 与 MCP `forecast_power`（无模型时自动触发）共用，
    统一在 `_hybrid_lock` 内去重，避免并发重复拉起训练线程。

    auto=True 是「预测时自动触发」的保守模式：该站点只要存在过任何训练任务
    （含失败）就不再自动重试，防止样本不足时出现「每次预测都失败重训」的循环；
    需要重试请显式调用 REST 接口。
    """
    site = site_store.get_site(site_id, user_id)
    if not site:
        return {'success': False, 'not_found': True,
                'error': '电站不存在或无权访问'}
    if not site_store.generation_range(site_id):
        return {'success': False,
                'error': '该电站还没有真实发电数据，请先在"数据导入"页面上传历史发电 CSV/Excel'}

    # 自动触发走小预算：默认 50 轮是 CPU 密集型，实测会把核打满（7+ 核满转）
    # 饿死 uvicorn 事件循环，导致 /mcp accept 失败、8000 端口失去监听。
    # 预测链路只需要一个能用的残差模型，自动补训不必训满；显式 REST 调用保持 50 轮。
    merged = {'epochs': 5 if auto else 50, 'batch_size': 32, 'seq_len': 12, 'lr': 0.001}
    merged.update(cfg or {})

    with _hybrid_lock:
        for j in _train_jobs.values():
            if j.get('model_type') != 'hybrid_v2' or j.get('site_id') != site_id:
                continue
            if auto:
                return {'success': False, 'skipped': True,
                        'error': f"该站点已有训练任务（状态 {j.get('status')}），"
                                 f"不自动重试；如需重试请调用 POST /api/prediction/hybrid/train"}
            # pending 也要拦：任务创建到线程真正跑起来之间存在窗口，
            # 只查 running 会让并发请求各起一个训练线程
            if j.get('status') in ('pending', 'running'):
                return {'success': False, 'skipped': True,
                        'error': '该站点混合模型正在训练中'}
        job_id = str(uuid.uuid4())
        _train_jobs[job_id] = {
            'job_id': job_id, 'model_type': 'hybrid_v2',
            'site_id': site_id, 'pv_file': None,
            'status': 'pending', 'progress': 0.0,
            'message': '任务已创建，等待启动...', 'error': None, 'result': None,
            'created_at': time.time(),
        }
    threading.Thread(target=_run_hybrid_training,
                     args=(job_id, user_id, site_id, merged),
                     daemon=True).start()
    return {'success': True, 'job_id': job_id, 'message': '混合模型训练任务已启动'}


@router.post("/hybrid/train")
def hybrid_train(request: HybridTrainRequest,
                 access_token: Optional[str] = Cookie(None),
                 authorization: Optional[str] = Header(None)):
    """启动站点混合残差模型后台训练，返回 job_id，复用 /train/progress/{job_id} 轮询。"""
    user = _require_user(access_token, authorization)
    out = start_hybrid_training(user['id'], request.site_id, cfg={
        'epochs': request.epochs, 'batch_size': request.batch_size,
        'seq_len': request.seq_len, 'lr': request.learning_rate,
    })
    if out.get('not_found'):
        raise HTTPException(status_code=404, detail=out['error'])
    return out


@router.post("/hybrid/forecast")
def hybrid_forecast(request: HybridForecastRequest,
                    access_token: Optional[str] = Cookie(None),
                    authorization: Optional[str] = Header(None)):
    """
    混合预测：
      - 默认（不给 start/end）：实时拉 Open-Meteo 未来 forecast_days 天预报
      - 给 start/end：用本地 NASA POWER 缓存做历史重算（需先回填气象）
    返回物理基准 / 残差 / 最终功率三条曲线。
    """
    user = _require_user(access_token, authorization)
    # 预报只读：本人或已分享站点均可分析
    site = site_store.get_site_readable(request.site_id, user['id'])
    if not site:
        raise HTTPException(status_code=404, detail='电站不存在或无权访问')

    t0 = time.time()
    if request.start and request.end:
        wx, meta = wstore.get_weather(site['lat'], site['lon'], request.start, request.end)
        if wx.empty:
            return {'success': False, 'error': '本地无该时间段气象缓存，请先回填 NASA POWER 数据'}
        source = 'nasa_power'
    else:
        try:
            wx = fetch_open_meteo_forecast(site['lat'], site['lon'],
                                          forecast_days=max(1, min(int(request.forecast_days), 16)))
        except Exception as e:
            return {'success': False, 'error': f'天气预报获取失败：{str(e)}（可稍后重试）'}
        meta = {'source': 'open_meteo'}
        source = 'open_meteo'

    result = hm.predict_hybrid(wx, site, user_id=user['id'])
    frame = result['frame']
    curves = _frame_to_curves(frame)

    # 逐日发电量汇总（kWh）
    daily = (frame.assign(day=frame['ts'].dt.strftime('%Y-%m-%d'))
             .groupby('day')[['p_phys_kw', 'p_final_kw']].sum()
             .round(2).reset_index())
    daily_list = [{'date': r['day'],
                   'energy_phys_kwh': _safe_num(r['p_phys_kw']),
                   'energy_final_kwh': _safe_num(r['p_final_kw'])}
                  for _, r in daily.iterrows()]

    return {
        'success': True,
        'source': source,
        'weather_meta': meta,
        'has_ml': result['has_ml'],
        'model_trained_at': (result['meta'] or {}).get('trained_at') if result['meta'] else None,
        'site': {'name': site['name'], 'kwp': site['kwp'],
                 'tilt': site['tilt'], 'azimuth': site['azimuth']},
        'count': len(curves),
        'elapsed': round(time.time() - t0, 2),
        'curves': curves,
        'daily_energy': daily_list,
        'total_energy_phys_kwh': _safe_num(frame['p_phys_kw'].sum()),
        'total_energy_final_kwh': _safe_num(frame['p_final_kw'].sum()),
    }
