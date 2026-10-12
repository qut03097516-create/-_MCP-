"""
混合预测模型 hybrid v2：物理基准 + ML 残差修正
============================================

思想：
  P_final = P_phys(pvlib 物理模型) + r_ML(气象 + P_phys)
模型不再从零学习"气象→功率"，只学习物理模型的系统性残差，
因此样本需求更少、外推（未来预报）更稳。

模型结构与旧版完全一致（IID_Transformer_LSTM），仅输入改为 4 维：
  [GHI, T2M, WS2M, P_phys]，目标为标准化残差 r = P_real − P_phys。

资产目录：models/user_{uid}/site_{site_id}/hybrid_residual/
  model.pt / feat_scaler.pkl / target_scaler.pkl / config.pkl
"""
from __future__ import annotations

import os
import pickle
import datetime as dt
from typing import Optional

import numpy as np
import pandas as pd
import torch
from sklearn.preprocessing import StandardScaler

from utils.config import DATA_CONFIG
from utils import site_store
from utils.weather import store as wstore
from utils.pv_physics import compute_physics_power
from utils.model_iid import IID_Transformer_LSTM
from utils.predictor import _train_one_model, temporal_split, EarlyStopping

MODEL_DIR = DATA_CONFIG['model_dir']

FEATURES = ['ghi', 't2m', 'ws2m', 'p_phys_kw']
SEQ_LEN = 12
MIN_TRAIN_ROWS = 200          # 少于此时长不训练（约 8 天）
MIN_VAL_ROWS = 24


def hybrid_model_dir(user_id: int, site_id: int) -> str:
    return os.path.join(MODEL_DIR, f'user_{int(user_id)}',
                        f'site_{int(site_id)}', 'hybrid_residual')


def has_trained_model(user_id: int, site_id: int) -> bool:
    d = hybrid_model_dir(user_id, site_id)
    return os.path.exists(os.path.join(d, 'model.pt'))


# ── 数据集构建 ───────────────────────────────────────────────────────────────

def build_hybrid_frame(site: dict, start: Optional[str] = None,
                       end: Optional[str] = None) -> pd.DataFrame:
    """
    真实发电 ⨝ NASA POWER 缓存气象 → 物理基准 → 残差。
    返回列 [ts, ghi, t2m, ws2m, power_kw, p_phys_kw, poa_global, t_cell, residual]
    """
    gen = site_store.get_generation(site['id'], start, end)
    if gen.empty:
        return gen
    t0, t1 = gen['ts'].min(), gen['ts'].max() + pd.Timedelta(hours=1)
    wx, _ = wstore.get_weather(site['lat'], site['lon'],
                               t0.strftime('%Y-%m-%d %H:%M:%S'),
                               t1.strftime('%Y-%m-%d %H:%M:%S'))
    if wx.empty:
        raise RuntimeError('本地气象缓存为空，请先回填该站点 NASA POWER 气象数据')

    phys = compute_physics_power(
        wx, site['lat'], site['lon'], tilt=site['tilt'],
        azimuth=site['azimuth'], kwp=site['kwp'], loss_pct=site['loss_pct'])

    m = gen.merge(phys, on='ts', how='inner')
    if m.empty:
        raise RuntimeError('真实发电与气象数据时间无交集，请检查上传数据的时间戳（需为北京时间整点）')
    m = m.sort_values('ts').reset_index(drop=True)
    # 真实功率异常防御：非负、不超过装机 1.5 倍（超容多半是单位错误）
    m['power_kw'] = pd.to_numeric(m['power_kw'], errors='coerce').clip(lower=0)
    cap = float(site['kwp'])
    m.loc[m['power_kw'] > cap * 1.5, 'power_kw'] = np.nan
    m['power_kw'] = m['power_kw'].interpolate(limit=3).fillna(0.0)
    m['residual'] = m['power_kw'] - m['p_phys_kw']
    return m


def _make_sequences(vals: np.ndarray, seq_len: int, n_feat: int):
    """vals: [T, n_feat+1]（最后一列是目标）。返回 X[N,seq,n_feat], y[N]。"""
    X, y = [], []
    for i in range(len(vals) - seq_len):
        X.append(vals[i:i + seq_len, :n_feat])
        y.append(vals[i + seq_len, n_feat])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


# ── 训练 ─────────────────────────────────────────────────────────────────────

def train_hybrid_residual(user_id: int, site_id: int, cfg: Optional[dict] = None,
                          progress_cb=None) -> dict:
    """
    训练残差修正模型并保存。

    progress_cb(stage:str, frac:float, message:str)
    返回 {'success': bool, ...指标}；样本不足时 success=False 且不生成模型。
    """
    cfg = cfg or {}
    site = site_store.get_site(site_id, user_id)
    if not site:
        raise RuntimeError('电站不存在或无权访问')

    if progress_cb:
        progress_cb('data', 0.05, '正在对齐真实发电与气象数据...')
    df = build_hybrid_frame(site)
    if len(df) < MIN_TRAIN_ROWS:
        return {'success': False,
                'reason': f'有效样本仅 {len(df)} 条，至少需要 {MIN_TRAIN_ROWS} 条（约8天逐小时数据）'}

    seq_len = cfg.get('seq_len', SEQ_LEN)
    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx]
    val_df = df.iloc[split_idx:]
    if len(val_df) < MIN_VAL_ROWS:
        split_idx = max(MIN_TRAIN_ROWS, len(df) - max(MIN_VAL_ROWS, len(df) // 5))
        train_df, val_df = df.iloc[:split_idx], df.iloc[split_idx:]

    # scaler 只在训练段 fit（防泄漏）：特征 4 维 + 残差目标各一个
    feat_scaler = StandardScaler().fit(train_df[FEATURES].values)
    target_scaler = StandardScaler().fit(train_df[['residual']].values)

    all_x = feat_scaler.transform(df[FEATURES].values)
    all_y = target_scaler.transform(df[['residual']].values)
    vals = np.concatenate([all_x, all_y], axis=1)
    X_all, y_all = _make_sequences(vals.astype(np.float32), seq_len, len(FEATURES))
    n_train_win = max(0, split_idx - seq_len)
    X_tr, y_tr = X_all[:n_train_win], y_all[:n_train_win]
    X_va, y_va = X_all[n_train_win:], y_all[n_train_win:]

    model_cfg = {
        'input_dim': len(FEATURES), 'd_model': cfg.get('d_model', 64),
        'nhead': cfg.get('nhead', 8),
        'num_encoder_layers': cfg.get('num_encoder_layers', 2),
        'lstm_hidden': cfg.get('lstm_hidden', 64),
        'lstm_layers': cfg.get('lstm_layers', 2),
        'dropout': cfg.get('dropout', 0.1),
        'batch_size': cfg.get('batch_size', 64),
        'epochs': cfg.get('epochs', 50), 'lr': cfg.get('lr', 0.001),
        'patience': cfg.get('patience', 10),
    }
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    device_info = f'🚀 使用设备: {torch.cuda.get_device_name(0)}' if device.type == 'cuda' else '💻 使用设备: CPU'

    if progress_cb:
        progress_cb('train', 0.12, device_info)
        progress_cb('train', 0.15, f'开始训练残差模型（{len(X_tr)} 训练窗口 / {len(X_va)} 验证窗口）')

    def _cb(epoch, epochs, tr_loss, val_loss):
        if progress_cb:
            frac = (epoch + 1) / max(epochs, 1)
            progress_cb('train', 0.15 + 0.7 * frac,
                        f'Epoch {epoch+1}/{epochs} | TrainLoss={tr_loss:.5f} ValLoss={val_loss:.5f}')

    model = _train_one_model(X_tr, y_tr, X_va, y_va, model_cfg, device, progress_cb=_cb)

    # 验证集指标：标准化残差 RMSE → 反标准化；以及最终功率 vs 纯物理
    model.eval()
    with torch.no_grad():
        pred_r_std = model(torch.FloatTensor(X_va).to(device)).squeeze().cpu().numpy()
    pred_r = target_scaler.inverse_transform(pred_r_std.reshape(-1, 1)).ravel()
    true_r = target_scaler.inverse_transform(y_va.reshape(-1, 1)).ravel()

    val_start = n_train_win + seq_len
    val_phys = df['p_phys_kw'].iloc[val_start:].to_numpy()
    val_real = df['power_kw'].iloc[val_start:].to_numpy()
    cap = float(site['kwp'])
    p_hybrid = np.clip(val_phys + pred_r, 0, cap)

    rmse_phys = float(np.sqrt(np.mean((val_real - val_phys) ** 2)))
    rmse_hybrid = float(np.mean((val_real - p_hybrid) ** 2) ** 0.5)
    mae_hybrid = float(np.mean(np.abs(val_real - p_hybrid)))

    save_dir = hybrid_model_dir(user_id, site_id)
    os.makedirs(save_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(save_dir, 'model.pt'))
    pickle.dump(feat_scaler, open(os.path.join(save_dir, 'feat_scaler.pkl'), 'wb'))
    pickle.dump(target_scaler, open(os.path.join(save_dir, 'target_scaler.pkl'), 'wb'))
    meta = {
        'model_version': 'hybrid_v2',
        'source': 'nasa_power',
        'seq_len': seq_len, 'features': FEATURES,
        'model_cfg': model_cfg,
        'site': {k: site[k] for k in ('lat', 'lon', 'tilt', 'azimuth', 'kwp', 'loss_pct')},
        'trained_at': dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'n_rows': int(len(df)),
        'train_range': [str(df['ts'].iloc[0]), str(df['ts'].iloc[split_idx - 1])],
        'val_range': [str(df['ts'].iloc[split_idx]), str(df['ts'].iloc[-1])],
        'metrics': {'rmse_physical_kw': round(rmse_phys, 4),
                    'rmse_hybrid_kw': round(rmse_hybrid, 4),
                    'mae_hybrid_kw': round(mae_hybrid, 4),
                    'improvement_pct': round((rmse_phys - rmse_hybrid) /
                                             max(rmse_phys, 1e-9) * 100, 2)},
    }
    pickle.dump(meta, open(os.path.join(save_dir, 'config.pkl'), 'wb'))

    if progress_cb:
        progress_cb('done', 1.0, '训练完成')
    return {'success': True, **meta}


# ── 预测 ─────────────────────────────────────────────────────────────────────

def predict_hybrid(weather_df: pd.DataFrame, site: dict,
                   user_id: Optional[int] = None) -> dict:
    """
    给定逐小时气象 [ts,ghi,t2m,ws2m] 计算混合预测。

    返回 {'has_ml': bool, 'frame': DataFrame[p_phys_kw, residual_kw, p_final_kw, ...],
          'meta': dict|None}
    无训练模型时残差为 0，最终功率即物理基准。
    """
    phys = compute_physics_power(
        weather_df, site['lat'], site['lon'], tilt=site['tilt'],
        azimuth=site['azimuth'], kwp=site['kwp'], loss_pct=site['loss_pct'])

    uid = user_id if user_id is not None else site.get('user_id')
    save_dir = hybrid_model_dir(uid, site['id']) if uid is not None else None
    model_path = os.path.join(save_dir, 'model.pt') if save_dir else None

    residual = np.zeros(len(phys), dtype=float)
    meta = None
    has_ml = bool(model_path and os.path.exists(model_path))

    if has_ml:
        feat_scaler = pickle.load(open(os.path.join(save_dir, 'feat_scaler.pkl'), 'rb'))
        target_scaler = pickle.load(open(os.path.join(save_dir, 'target_scaler.pkl'), 'rb'))
        meta = pickle.load(open(os.path.join(save_dir, 'config.pkl'), 'rb'))
        seq_len = meta['seq_len']
        model_cfg = meta['model_cfg']

        x = feat_scaler.transform(phys[FEATURES].values).astype(np.float32)
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        model = IID_Transformer_LSTM(**{k: v for k, v in model_cfg.items()
                                        if k in ('input_dim', 'd_model', 'nhead',
                                                 'num_encoder_layers', 'lstm_hidden',
                                                 'lstm_layers', 'dropout')}).to(device)
        model.load_state_dict(torch.load(model_path, map_location=device))
        model.eval()
        with torch.no_grad():
            wins = np.stack([x[i:i + seq_len] for i in range(len(x) - seq_len)]) \
                if len(x) > seq_len else np.empty((0, seq_len, len(FEATURES)), np.float32)
            if len(wins):
                r_std = model(torch.FloatTensor(wins).to(device)).squeeze(-1).cpu().numpy()
                residual[seq_len:] = target_scaler.inverse_transform(
                    r_std.reshape(-1, 1)).ravel()

    cap = float(site['kwp'])
    phys['residual_kw'] = np.round(residual, 4)
    phys['p_final_kw'] = np.round(
        np.clip(phys['p_phys_kw'].to_numpy() + residual, 0, cap), 4)
    return {'has_ml': has_ml, 'frame': phys, 'meta': meta}
