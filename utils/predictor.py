import os
import pickle
import re
import warnings
import traceback
from datetime import time
from pathlib import Path
from typing import Callable, Dict, List, Tuple
from functools import lru_cache

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import torch
import torch.nn as nn
from sklearn.ensemble import IsolationForest
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler, MinMaxScaler
from torch.utils.data import DataLoader, TensorDataset

from utils.model_iid import IID_Transformer_LSTM
from utils.config import PREPROCESS_CONFIG, DATA_CONFIG
from utils.model_cnn import CNNLSTMModel, create_sequences

warnings.filterwarnings('ignore')
MODEL_DIR = DATA_CONFIG['model_dir']
os.makedirs(MODEL_DIR, exist_ok=True)


def get_safe_name(pv_file: str) -> str:
    p = Path(pv_file)
    name = p.stem
    return re.sub(r'[^\w\-_]', '_', name)


@lru_cache(maxsize=8)
def _load_models_cached(save_dir, global_cfg_tuple, device_str):
    global_cfg = dict(global_cfg_tuple)
    device = torch.device(device_str)
    models = []

    available_intervals = []
    intervals_path = os.path.join(save_dir, 'available_intervals.pkl')
    if os.path.exists(intervals_path):
        available_intervals = pickle.load(open(intervals_path, 'rb'))

    fallback_model_path = None
    if available_intervals:
        fallback_idx = available_intervals[0]
        fallback_model_path = os.path.join(save_dir, f'interval_{fallback_idx}.pt')
    else:
        fallback_model_path = os.path.join(save_dir, 'interval_0.pt')

    for i in range(4):
        m = IID_Transformer_LSTM(
            input_dim=global_cfg['input_dim'],
            d_model=global_cfg['d_model'],
            nhead=global_cfg['nhead'],
            num_encoder_layers=global_cfg['num_encoder_layers'],
            lstm_hidden=global_cfg['lstm_hidden'],
            lstm_layers=global_cfg['lstm_layers'],
            dropout=global_cfg['dropout']
        ).to(device)
        pt_path = os.path.join(save_dir, f'interval_{i}.pt')
        if os.path.exists(pt_path):
            m.load_state_dict(torch.load(pt_path, map_location=device, weights_only=True))
        else:
            if fallback_model_path and os.path.exists(fallback_model_path):
                m.load_state_dict(torch.load(
                    fallback_model_path,
                    map_location=device, weights_only=True
                ))
            else:
                raise FileNotFoundError(f"无法加载模型，没有可用的区间模型")
        m.eval()
        models.append(m)
    return models


# =============================================================================
# 1. 数据加载 & 列名适配（兼容原有接口）
# =============================================================================

# load_pv_data 从 utils.data_loader 导入


def parse_pv_filename(pv_file: str) -> dict:
    """
    从文件名解析站点信息。
    文件名格式: Timeseries_纬度_经度_E5_1kWp_crystSi_14_v角度deg_起始年份_结束年份.csv
    或: 省份 - Timeseries_纬度_经度_E5_1kWp_crystSi_14_v角度deg_起始年份_结束年份.csv
    """
    import os
    filename = os.path.basename(pv_file)
    
    # 处理带省份前缀的格式
    if " - " in filename:
        filename = filename.split(" - ", 1)[1]
    
    try:
        # 提取文件名部分（去掉扩展名）
        name_part = filename.replace('.csv', '')
        parts = name_part.split('_')
        
        if len(parts) >= 9:
            # 解析各部分
            latitude = f"{parts[1]}°N" if float(parts[1]) >= 0 else f"{abs(float(parts[1]))}°S"
            longitude = f"{parts[2]}°E" if float(parts[2]) >= 0 else f"{abs(float(parts[2]))}°W"
            
            # 提取安装角度
            angle_part = parts[7]
            install_angle = angle_part.replace('v', '').replace('deg', '')
            
            # 提取年份范围
            year_start = parts[8]
            year_end = parts[9] if len(parts) > 9 else parts[8]
            year_range = f"{year_start}-{year_end}"
            
            # 系统规模和组件类型
            system_size = "1 kWp"
            module_type = "Cryst-Si"
            
            return {
                'latitude': latitude,
                'longitude': longitude,
                'system_size': system_size,
                'module_type': module_type,
                'install_angle': install_angle,
                'year_range': year_range
            }
        else:
            # 默认值
            return {
                'latitude': 'N/A',
                'longitude': 'N/A',
                'system_size': 'N/A',
                'module_type': 'N/A',
                'install_angle': 'N/A',
                'year_range': 'N/A'
            }
    except Exception as e:
        # 解析失败时返回默认值
        return {
            'latitude': 'N/A',
            'longitude': 'N/A',
            'system_size': 'N/A',
            'module_type': 'N/A',
            'install_angle': 'N/A',
            'year_range': 'N/A'
        }


def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """模糊匹配列名，统一为内部标准列名"""
    col_map = {}
    # 确保每个标准列名只映射一次
    mapped = set()
    
    for c in df.columns:
        lc = str(c).lower().replace(' ', '').replace('_', '').replace('-', '').replace('(', '').replace(')', '')
        
        # 时间列
        if 'DATATIME' not in mapped and any(k in lc for k in ['datatime', '时间', '日期', 'timestamp', 'time']):
            col_map[c] = 'DATATIME'
            mapped.add('DATATIME')
        # 功率列
        elif 'POWER' not in mapped and any(k in lc for k in ['power', '功率', 'activepower', 'p(kw)', 'p']):
            col_map[c] = 'POWER'
            mapped.add('POWER')
        # 辐照度列（优先选择直接辐照度 Gb）
        elif '辐照度' not in mapped and any(k in lc for k in ['irrad', '辐照', 'ghi', 'solarrad', '辐射', 'irradiance', 'gb', 'gd', 'gr']):
            col_map[c] = '辐照度'
            mapped.add('辐照度')
        # 温度列
        elif '温度' not in mapped and any(k in lc for k in ['temp', '温度', '气温', 'airtemp', 'temperature', 't2m', 'tem']):
            col_map[c] = '温度'
            mapped.add('温度')
    
    # 额外检查：如果没有找到温度列，尝试直接匹配'TEMPERATURE'或类似列名
    if '温度' not in mapped:
        for c in df.columns:
            if 'temperature' in str(c).lower() or 'tem' in str(c).lower():
                col_map[c] = '温度'
                mapped.add('温度')
                break
    
    # 检查是否成功映射了所有必要列
    required_cols = ['DATATIME', 'POWER', '辐照度', '温度']
    missing_cols = [col for col in required_cols if col not in mapped]
    if missing_cols:
        # 返回原 DataFrame，让后续代码给出更清晰的错误信息
        return df
    
    return df.rename(columns=col_map)


# =============================================================================
# 2. 数据预处理（对齐论文：3σ → 插值 → 分箱 → 孤立森林 → Z-score）
# =============================================================================

def _basic_clean(df: pd.DataFrame) -> pd.DataFrame:
    """
    基础清洗：仅保留 05:00–20:00（论文设定）；
    3σ 异常标记为 NaN；线性插值；缺失行删除。
    """
    df = df.copy()
    df['DATATIME'] = pd.to_datetime(df['DATATIME'])
    df = df.sort_values('DATATIME').reset_index(drop=True)

    # 仅保留发电时段
    t = df['DATATIME'].dt.time
    mask = (t >= PREPROCESS_CONFIG['day_start']) & (t <= PREPROCESS_CONFIG['day_end'])
    df = df[mask].reset_index(drop=True)

    numeric_cols = ['辐照度', '温度', 'POWER']
    # 先转换为数值类型，避免字符串列导致 mean/std 报错
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # 3σ 检测（仅标记，不删除，后续插值）
    stats_3sigma = {}
    for col in numeric_cols:
        if col not in df.columns:
            raise ValueError(f"数据缺少必要列: {col}，实际列: {list(df.columns)}")
        mu, sigma = df[col].mean(), df[col].std()
        stats_3sigma[col] = (mu, sigma)
        if sigma > 0:
            mask_out = np.abs(df[col] - mu) > PREPROCESS_CONFIG['sigma_threshold'] * sigma
            df.loc[mask_out, col] = np.nan

    # 线性插值并删除仍缺失的行
    df[numeric_cols] = df[numeric_cols].interpolate(method='linear')
    df = df.dropna(subset=numeric_cols).reset_index(drop=True)
    return df, stats_3sigma


class IrradiationIntervalDistribution:
    """基于箱线图的辐照度区间分布"""
    
    def __init__(self, irradiation_col='辐照度'):
        self.irr_col = irradiation_col
        self.intervals = {}
        self.models = {}      # 每个区间一个模型
        self.scalers = {}     # 每个区间一个归一化器
        self.features = {}    # 每个区间选中的特征
        
    def fit(self, df, n_groups=4):
        """
        论文要求：提取>100 W/m²的数据分成A/B/C/D四组
        计算m1,m2,m3,m4确定四个区间
        """
        high_irr = df[df[self.irr_col] > 100].copy()
        
        # 分成4组
        group_size = len(high_irr) // n_groups
        groups = []
        for i in range(n_groups):
            start = i * group_size
            end = start + group_size if i < n_groups - 1 else len(high_irr)
            groups.append(high_irr.iloc[start:end])
        
        # 计算每组统计量
        stats = []
        for g in groups:
            stats.append({
                'min': g[self.irr_col].min(),
                'q1': g[self.irr_col].quantile(0.25),
                'median': g[self.irr_col].median(),
                'q3': g[self.irr_col].quantile(0.75),
                'max': g[self.irr_col].max()
            })
        
        # 论文公式(1)
        m1 = np.mean([s['min'] for s in stats])
        m2 = np.mean([s['q1'] for s in stats])
        m3 = np.mean([s['q3'] for s in stats])
        m4 = np.max([s['max'] for s in stats])
        
        self.intervals = {
            'ultra_low': (0, m1),
            'low': (m1, m2),
            'medium': (m2, m3),
            'high': (m3, m4)
        }
        
        # 返回 bins 格式 [0, m1, m2, m3, m4]
        return [0.0, float(m1), float(m2), float(m3), float(m4)]
    
    def get_interval(self, value):
        """判断辐照度属于哪个区间"""
        for name, (low, high) in self.intervals.items():
            if low <= value < high or (name == 'high' and value <= high):
                return name
        return 'ultra_low'
    
    def remove_outliers(self, df, interval_name):
        """
        孤立森林异常检测（论文图3-4）
        只使用5:00-20:00数据
        """
        mask = df['interval'] == interval_name
        data = df[mask].copy()
        
        # 5:00-20:00筛选
        if 'DATATIME' in data.columns:
            data['hour'] = pd.to_datetime(data['DATATIME']).dt.hour
            data = data[(data['hour'] >= 5) & (data['hour'] <= 20)]
        
        if len(data) < 10:
            return data
        
        # 孤立森林：辐照度-功率二维异常检测
        X = data[[self.irr_col, 'POWER']].values
        clf = IsolationForest(contamination=0.1, random_state=42)
        preds = clf.fit_predict(X)
        
        return data[preds == 1]  # 只保留正常点
    
    def select_features(self, df, target='POWER'):
        """相关性分析选择特征（论文提到）"""
        corr = df.corr()[target].abs().sort_values(ascending=False)
        # 取top5相关特征（排除目标本身）
        selected = [c for c in corr.index if c != target][:5]
        return selected
    
    def create_sequences(self, data, time_steps):
        """滑动窗口构造时序样本"""
        X, y = [], []
        for i in range(len(data) - time_steps):
            X.append(data[i:i+time_steps, :-1])
            y.append(data[i+time_steps, -1])
        return np.array(X), np.array(y)
    
    def fit(self, df, time_steps=24):
        """完整训练流程"""
        # 1. 计算辐照度区间分布
        intervals = self.fit(df)
        
        # 2. 标注每条数据的区间
        df = df.copy()
        df['interval'] = df[self.irr_col].apply(self.get_interval)
        
        # 3. 每个区间独立训练
        for interval_name in ['ultra_low', 'low', 'medium', 'high']:
            # 3.1 孤立森林去噪
            clean_df = self.remove_outliers(df, interval_name)
            if len(clean_df) < 100:
                continue
            
            # 3.2 特征选择
            selected = self.select_features(clean_df)
            self.features[interval_name] = selected
            
            # 3.3 归一化 [0,1]（论文要求）
            feature_cols = selected + ['POWER']
            data = clean_df[feature_cols].values
            
            scaler = MinMaxScaler(feature_range=(0, 1))
            data_scaled = scaler.fit_transform(data)
            self.scalers[interval_name] = scaler
            
            # 3.4 构造时序样本
            X, y = self.create_sequences(data_scaled, time_steps)
            if len(X) < 50:
                continue
            
            # 3.5 划分训练/验证（论文8:2）
            split = int(len(X) * 0.8)
            X_train, X_val = X[:split], X[split:]
            y_train, y_val = y[:split], y[split:]
            
            # 3.6 训练独立模型
            try:
                from utils.model_iid import IID_Transformer_LSTM
                model = IID_Transformer_LSTM(input_dim=len(selected))
                
                # 转换为torch张量
                X_train_t = torch.FloatTensor(X_train)
                y_train_t = torch.FloatTensor(y_train).unsqueeze(-1)
                X_val_t = torch.FloatTensor(X_val)
                y_val_t = torch.FloatTensor(y_val).unsqueeze(-1)
                
                # 训练（简化版，建议加early stopping）
                optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
                criterion = nn.MSELoss()
                
                best_loss = float('inf')
                patience = 10
                patience_counter = 0
                
                for epoch in range(100):
                    model.train()
                    optimizer.zero_grad()
                    pred = model(X_train_t)
                    loss = criterion(pred, y_train_t)
                    loss.backward()
                    optimizer.step()
                    
                    # 验证
                    model.eval()
                    with torch.no_grad():
                        val_pred = model(X_val_t)
                        val_loss = criterion(val_pred, y_val_t).item()
                    
                    if val_loss < best_loss:
                        best_loss = val_loss
                        patience_counter = 0
                        # 保存最佳模型
                        self.models[interval_name] = model
                    else:
                        patience_counter += 1
                        if patience_counter >= patience:
                            break
            except Exception as e:
                continue
        
        return self
    
    def predict(self, df, time_steps=24):
        """分区间预测并重组"""
        df = df.copy()
        df['interval'] = df[self.irr_col].apply(self.get_interval)
        all_preds = []
        all_indices = []
        
        for interval_name in df['interval'].unique():
            if interval_name not in self.models:
                continue
            
            mask = df['interval'] == interval_name
            sub_df = df[mask].copy()
            
            # 使用对应区间的scaler和特征
            scaler = self.scalers[interval_name]
            features = self.features[interval_name]
            
            # 归一化
            feature_cols = features + ['POWER']
            data = sub_df[feature_cols].values
            data_scaled = scaler.transform(data)
            
            # 构造时序样本
            X, _ = self.create_sequences(data_scaled, time_steps)
            if len(X) == 0:
                continue
            
            # 预测
            model = self.models[interval_name]
            model.eval()
            with torch.no_grad():
                X_t = torch.FloatTensor(X)
                preds = model(X_t).numpy().flatten()
            
            # 反归一化（恢复功率真实值）
            # scaler是对[features + POWER]做的，POWER在最后一位
            power_idx = -1
            power_min = scaler.data_min_[power_idx]
            power_max = scaler.data_max_[power_idx]
            preds_real = preds * (power_max - power_min) + power_min
            
            all_preds.extend(preds_real)
            # 记录对应的原始索引（用于重组）
            all_indices.extend(sub_df.index[time_steps:].tolist())
        
        # 按原始时间顺序重组
        if all_indices:
            result = pd.DataFrame({
                'index': all_indices,
                'prediction': all_preds
            }).sort_values('index').set_index('index')
            return result
        else:
            return pd.DataFrame()


def _calc_irradiation_bins(df: pd.DataFrame) -> List[float]:
    """
    基于论文箱线图思想计算 4 个辐照区间阈值（物理量，非标准化）。
    区间：[0, m1), [m1, m2), [m2, m3), [m3, m4]
    其中 m2/m3 对应第一/第三分位数（>100 W/m² 样本）。
    """
    # 使用新的 IrradiationIntervalDistribution 类
    distributor = IrradiationIntervalDistribution(irradiation_col='辐照度')
    try:
        bins = distributor.fit(df)
        return bins
    except Exception as e:
        # 数据不足时的默认兜底
        return [0.0, 50.0, 200.0, 600.0, 1200.0]


def _isolation_forest_clean(df: pd.DataFrame, bins: List[float]) -> pd.DataFrame:
    """
    按辐照区间分别进行孤立森林异常检测，剔除功率-辐照异常点。
    """
    # 创建辐照度区间分布对象
    distributor = IrradiationIntervalDistribution(irradiation_col='辐照度')
    
    # 手动设置 intervals，使用传入的 bins 参数
    # bins = [0, m1, m2, m3, m4]
    distributor.intervals = {
        'ultra_low': (bins[0], bins[1]),
        'low': (bins[1], bins[2]),
        'medium': (bins[2], bins[3]),
        'high': (bins[3], bins[4]),
    }
    
    # 为每个数据点添加区间标签
    df_with_interval = df.copy()
    df_with_interval['interval'] = df_with_interval['辐照度'].apply(distributor.get_interval)
    
    # 按区间进行异常检测
    clean_dfs = []
    for interval_name in ['ultra_low', 'low', 'medium', 'high']:
        # 使用新的 remove_outliers 方法
        clean_data = distributor.remove_outliers(df_with_interval, interval_name)
        if not clean_data.empty:
            clean_dfs.append(clean_data)
    
    # 合并所有清洁数据
    if clean_dfs:
        df_clean = pd.concat(clean_dfs, ignore_index=True)
        # 按时间排序
        if 'DATATIME' in df_clean.columns:
            df_clean = df_clean.sort_values('DATATIME').reset_index(drop=True)
    else:
        # 如果没有清洁数据，返回原始数据
        df_clean = df.copy()
    
    return df_clean


def preprocess_pipeline(df_raw: pd.DataFrame, fit_scaler: bool = True,
                        scaler: StandardScaler = None,
                        stats_3sigma: dict = None):
    """
    完整预处理管道。
    返回: (df_processed, scaler, bins_raw, bins_std, stats_3sigma)
    """
    df = _standardize_columns(df_raw)

    # 检查必要的列是否存在
    required_cols = ['DATATIME', '辐照度', '温度']
    if 'POWER' not in df.columns:
        df['POWER'] = 0.0  # 预测时可能没有 POWER 列
    
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"数据缺少必要列: {missing_cols}，实际列: {list(df.columns)}")

    # 若为未来预测场景，可能没有 POWER 列
    has_power = 'POWER' in df.columns
    if not has_power:
        # 用 0 占位，保证后续流程统一（预测时不使用真实功率作为输入特征）
        df['POWER'] = 0.0

    # 1. 基础清洗（3σ + 插值）
    df, stats_3sigma = _basic_clean(df)

    # 2. 计算原始空间分箱阈值
    bins_raw = _calc_irradiation_bins(df)

    # 3. ❌ 孤立森林去异常（仅在训练阶段使用，预测阶段禁用以避免时间轴空洞）
    # 孤立森林只应在 model_iid.py 的 build_iid_datasets() 中、按区间独立清洗训练数据时使用
    # df = _isolation_forest_clean(df, bins_raw)

    # 4. Z-score 标准化
    numeric_cols = ['辐照度', '温度', 'POWER']
    if fit_scaler:
        scaler = StandardScaler()
        df[numeric_cols] = scaler.fit_transform(df[numeric_cols])
    else:
        if scaler is None:
            raise ValueError("预测时必须传入已 fit 的 scaler")
        df[numeric_cols] = scaler.transform(df[numeric_cols])

    # 5. 将分箱阈值转换到标准化空间（用于后续区间判断）
    irr_mean, irr_scale = scaler.mean_[0], scaler.scale_[0]  # 辐照度在第0列
    bins_std = [(b - irr_mean) / irr_scale for b in bins_raw]

    return df, scaler, bins_raw, bins_std, stats_3sigma


# =============================================================================
# 3. 时序样本构建（滑动窗口）
# =============================================================================

def create_iid_sequences(df: pd.DataFrame, seq_len: int = 12):
    """
    用过去 seq_len 个时间步的 [辐照度, 温度] 预测当前时刻 POWER。
    返回: X[num_samples, seq_len, 2], y[num_samples], times[num_samples]
    """
    feat_cols = ['辐照度', '温度']
    target_col = 'POWER'
    vals = df[feat_cols + [target_col]].values
    times = df['DATATIME'].values

    X, y, t_out = [], [], []
    for i in range(len(vals) - seq_len):
        X.append(vals[i:i + seq_len, :-1])
        y.append(vals[i + seq_len, -1])      # 预测第 i+seq_len 时刻（对应输入序列的下一个点）
        t_out.append(times[i + seq_len])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32), np.array(t_out)


def temporal_split(X, y, ratio=0.8):
    """
    时序-aware 划分：前 80% 训练，后 20% 验证
    保持时间顺序，避免破坏时间依赖性
    """
    split_idx = int(len(X) * ratio)
    return X[:split_idx], y[:split_idx], X[split_idx:], y[split_idx:]


# =============================================================================
# 4. 训练逻辑（在线训练 + 早停）
# =============================================================================

class EarlyStopping:
    def __init__(self, patience=10, min_delta=1e-4, save_path=None):
        self.patience = patience
        self.min_delta = min_delta
        self.save_path = save_path
        self.counter = 0
        self.best_loss = float('inf')
        self.best_state = None
        self.early_stop = False

    def __call__(self, val_loss, model=None):
        if val_loss < self.best_loss - self.min_delta:
            self.best_loss = val_loss
            if model is not None and self.save_path:
                self.best_state = model.state_dict().copy()
            self.counter = 0
        else:
            self.counter += 1
            if self.counter >= self.patience:
                self.early_stop = True
        return self.early_stop
    
    def restore_best(self, model):
        if self.best_state is not None:
            model.load_state_dict(self.best_state)
            return True
        return False


def _train_one_model(X_train, y_train, X_val, y_val, cfg: dict, device, progress_cb=None):
    """训练单个区间的 Transformer-LSTM"""
    batch_size = cfg.get('batch_size', 64)
    epochs = cfg.get('epochs', 50)
    lr = cfg.get('lr', 0.001)

    train_ds = TensorDataset(torch.FloatTensor(X_train), torch.FloatTensor(y_train))
    val_ds = TensorDataset(torch.FloatTensor(X_val), torch.FloatTensor(y_val))
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    model = IID_Transformer_LSTM(
        input_dim=cfg.get('input_dim', 2),
        d_model=cfg.get('d_model', 64),
        nhead=cfg.get('nhead', 8),
        num_encoder_layers=cfg.get('num_encoder_layers', 2),
        lstm_hidden=cfg.get('lstm_hidden', 64),
        lstm_layers=cfg.get('lstm_layers', 2),
        dropout=cfg.get('dropout', 0.1)
    ).to(device)

    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)
    
    # 使用带模型保存功能的 EarlyStopping
    early_stop = EarlyStopping(patience=cfg.get('patience', 10))

    for epoch in range(epochs):
        model.train()
        train_losses = []
        for bx, by in train_loader:
            bx, by = bx.to(device), by.to(device)
            optimizer.zero_grad()
            pred = model(bx).squeeze()
            loss = criterion(pred, by)
            loss.backward()
            optimizer.step()
            train_losses.append(loss.item())

        model.eval()
        val_losses = []
        with torch.no_grad():
            for bx, by in val_loader:
                bx, by = bx.to(device), by.to(device)
                pred = model(bx).squeeze()
                val_losses.append(criterion(pred, by).item())
        val_loss = np.mean(val_losses)
        scheduler.step(val_loss)
        
        # 传入模型以便保存最佳状态
        stop = early_stop(val_loss, model)
        if progress_cb:
            progress_cb(epoch, epochs, np.mean(train_losses), val_loss)
        if stop:
            break
    
    # 恢复最佳模型状态
    early_stop.restore_best(model)
    return model


def train_pv_models(pv_file: str, cfg: dict, progress_bar=None, status_text=None):
    """
    在线训练入口。对每个辐照区间独立训练一个 Transformer-LSTM。
    保存：scaler, bins, config, 4个模型权重。
    """
    from utils.data_loader import load_pv_data
    df_raw = load_pv_data(pv_file)
    base_name = get_safe_name(pv_file)
    save_dir = os.path.join(MODEL_DIR, base_name, 'iid_transformer_lstm')
    os.makedirs(save_dir, exist_ok=True)

    if status_text:
        status_text.text('Step 1/4: 数据预处理与辐照区间分箱...')
    if progress_bar:
        progress_bar.progress(0.05)

    # 预处理
    df_proc, scaler, bins_raw, bins_std, stats_3sigma = preprocess_pipeline(df_raw, fit_scaler=True)

    # 保存预处理资产
    pickle.dump(scaler, open(os.path.join(save_dir, 'scaler.pkl'), 'wb'))
    pickle.dump(bins_std, open(os.path.join(save_dir, 'bins.pkl'), 'wb'))
    pickle.dump(bins_raw, open(os.path.join(save_dir, 'bins_raw.pkl'), 'wb'))
    pickle.dump(stats_3sigma, open(os.path.join(save_dir, 'stats.pkl'), 'wb'))

    # 全局配置
    seq_len = cfg.get('seq_len', 12)
    global_cfg = {
        'seq_len': seq_len,
        'input_dim': 2,
        'd_model': cfg.get('d_model', 64),
        'nhead': cfg.get('nhead', 8),
        'num_encoder_layers': cfg.get('num_encoder_layers', 2),
        'lstm_hidden': cfg.get('lstm_hidden', 64),
        'lstm_layers': cfg.get('lstm_layers', 2),
        'dropout': cfg.get('dropout', 0.1),
        'batch_size': cfg.get('batch_size', 64),
        'epochs': cfg.get('epochs', 50),
        'lr': cfg.get('lr', 0.001),
        'patience': cfg.get('patience', 10),
        'power_idx': 2  # scaler 中 POWER 的列序号（辐照度0，温度1，功率2）
    }
    pickle.dump(global_cfg, open(os.path.join(save_dir, 'config.pkl'), 'wb'))

    if status_text:
        status_text.text('Step 2/4: 构建时序样本...')
    if progress_bar:
        progress_bar.progress(0.15)

    # 构建全量时序样本
    X_all, y_all, t_all = create_iid_sequences(df_proc, seq_len=seq_len)

    # 按最后一个时间步的辐照度划分区间
    last_irr = X_all[:, -1, 0]
    intervals = np.digitize(last_irr, bins_std) - 1
    intervals = np.clip(intervals, 0, 3)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    device_info = f'🚀 GPU: {torch.cuda.get_device_name(0)}' if device.type == 'cuda' else '💻 CPU'

    # 划分训练/验证（80/20），按区间独立划分
    available_intervals = []
    MIN_SAMPLES = 50
    
    for i in range(4):
        if status_text:
            prefix = f'Step 3/4 [{device_info}]: ' if i == 0 else 'Step 3/4: '
            status_text.text(f'{prefix}正在训练第 {i+1}/4 个辐照区间模型...')
        if progress_bar:
            progress_bar.progress(0.2 + i * 0.18)

        mask = (intervals == i)
        if mask.sum() < MIN_SAMPLES:
            # 数据过少时跳过，记录警告
            if status_text:
                status_text.text(f'区间 {i} 样本不足({mask.sum()}), 将使用最近邻区间模型')
            continue

        available_intervals.append(i)
        
        X_i = X_all[mask]
        y_i = y_all[mask]
        # 使用时序划分，保持时间顺序
        X_tr, y_tr, X_va, y_va = temporal_split(X_i, y_i, ratio=PREPROCESS_CONFIG['train_val_split'])

        # 区间 i 的进度区间: [base, base+0.18)，epoch 级细粒度推进
        base_progress = 0.2 + i * 0.18

        def cb(epoch, epochs, tr_loss, val_loss):
            frac = (epoch + 1) / max(epochs, 1)
            if progress_bar:
                progress_bar.progress(min(base_progress + frac * 0.18, base_progress + 0.179))
            if status_text:
                status_text.text(f'区间 {i+1}/4 | Epoch {epoch+1}/{epochs} | '
                                f'TrainLoss={tr_loss:.4f} ValLoss={val_loss:.4f}')

        model = _train_one_model(X_tr, y_tr, X_va, y_va, global_cfg, device, progress_cb=cb)
        torch.save(model.state_dict(), os.path.join(save_dir, f'interval_{i}.pt'))

    # 保存可用的区间信息
    pickle.dump(available_intervals, open(os.path.join(save_dir, 'available_intervals.pkl'), 'wb'))

    _load_models_cached.cache_clear()

    if status_text:
        status_text.text('Step 4/4: 训练完成，模型已保存。')
    if progress_bar:
        progress_bar.progress(1.0)

    return True


# =============================================================================
# 5. 预测逻辑（历史回测 & 未来预测）
# =============================================================================

def predict_pv(pv_file: str, start_pred, end_pred,
               model_key: str = 'iid_transformer_lstm',
               mode: str = 'historical',
               model_dir: str = MODEL_DIR,
               progress_bar=None, status_text=None):
    """
    核心预测接口（兼容原有系统签名）。
    mode='historical' -> 历史回测（有真实功率对比）
    mode='future'     -> 未来预测（仅用 NWP 输入）
    返回: (result_df, error_msg)
    result_df 列: DATATIME, POWER_true, POWER_pred
    """
    from utils.data_loader import load_pv_data
    base_name = get_safe_name(pv_file)
    save_dir = os.path.join(model_dir, base_name, model_key)
    
    # 检查模型文件是否存在（更严格的检查）
    config_path = os.path.join(save_dir, 'config.pkl')
    scaler_path = os.path.join(save_dir, 'scaler.pkl')
    bins_path = os.path.join(save_dir, 'bins.pkl')
    
    if not os.path.exists(config_path):
        return None, "未找到预训练模型，请先点击【🚀 在线训练模型】"
    if not os.path.exists(scaler_path):
        return None, "模型文件损坏：缺少 scaler.pkl，请重新训练"
    if not os.path.exists(bins_path):
        return None, "模型文件损坏：缺少 bins.pkl，请重新训练"

    # 加载资产
    scaler = pickle.load(open(scaler_path, 'rb'))
    bins_std = pickle.load(open(bins_path, 'rb'))
    global_cfg = pickle.load(open(config_path, 'rb'))
    stats_3sigma_path = os.path.join(save_dir, 'stats.pkl')
    if os.path.exists(stats_3sigma_path):
        stats_3sigma = pickle.load(open(stats_3sigma_path, 'rb'))
    else:
        stats_3sigma = None
    
    # 加载可用区间信息
    available_intervals = []
    intervals_path = os.path.join(save_dir, 'available_intervals.pkl')
    if os.path.exists(intervals_path):
        available_intervals = pickle.load(open(intervals_path, 'rb'))

    seq_len = global_cfg['seq_len']
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    if status_text:
        status_text.text('正在加载数据...')
    if progress_bar:
        progress_bar.progress(0.1)

    # 加载全量文件（确保边界处有足够历史 seq_len 构造样本）
    df_raw = load_pv_data(pv_file)

    if status_text:
        status_text.text('正在预处理...')
    if progress_bar:
        progress_bar.progress(0.25)

    # 预测时：使用已保存的 scaler & stats，不再 fit
    try:
        df_proc, _, _, _, _ = preprocess_pipeline(df_raw, fit_scaler=False,
                                                   scaler=scaler, stats_3sigma=stats_3sigma)
    except ValueError as e:
        return None, f"数据预处理失败: {str(e)}"

    # 构建全量时序样本
    X_all, y_all, t_all = create_iid_sequences(df_proc, seq_len=seq_len)

    if status_text:
        status_text.text('正在匹配辐照区间并加载子模型...')
    if progress_bar:
        progress_bar.progress(0.4)

    # 加载模型（使用缓存，避免重复加载）
    device_str = 'cuda' if torch.cuda.is_available() else 'cpu'
    models = _load_models_cached(save_dir, tuple(sorted(global_cfg.items())), device_str)

    # 按最后一个时间步的辐照度划分区间（与训练时保持一致）
    last_irr = X_all[:, -1, 0]
    intervals = np.digitize(last_irr, bins_std) - 1
    intervals = np.clip(intervals, 0, 3)
    
    # ✅ 并行推理：4个子模型同时预测
    from concurrent.futures import ThreadPoolExecutor
    
    batch_size = global_cfg.get('batch_size', 64)
    
    def predict_interval(i, models_ref, X_all_ref, intervals_ref, device_ref, batch_size_ref):
        """预测单个区间，返回 (mask_indices, predictions)"""
        mask = (intervals_ref == i)
        if mask.sum() == 0:
            return None
        
        X_interval = X_all_ref[mask]
        num_batches = (len(X_interval) + batch_size_ref - 1) // batch_size_ref
        interval_preds = []
        
        for batch_idx in range(num_batches):
            start_idx = batch_idx * batch_size_ref
            end_idx = min((batch_idx + 1) * batch_size_ref, len(X_interval))
            X_batch = torch.FloatTensor(X_interval[start_idx:end_idx]).to(device_ref)
            with torch.no_grad():
                p = models_ref[i](X_batch).cpu().numpy().squeeze()
            interval_preds.append(p)
        
        interval_preds = np.concatenate(interval_preds).flatten()
        indices = np.where(mask)[0]
        return (indices, interval_preds)
    
    preds = np.zeros(len(X_all))
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(predict_interval, i, models, X_all, intervals, device, batch_size) for i in range(4)]
        for future in futures:
            result = future.result()
            if result is not None:
                indices, interval_preds = result
                preds[indices] = interval_preds

    # 反标准化 POWER
    p_idx = global_cfg['power_idx']
    preds_inv = preds * scaler.scale_[p_idx] + scaler.mean_[p_idx]
    y_inv = y_all * scaler.scale_[p_idx] + scaler.mean_[p_idx]

    # 组装 DataFrame，并截取目标日期
    result = pd.DataFrame({
        'DATATIME': pd.to_datetime(t_all),
        'POWER_true': y_inv,
        'POWER_pred': preds_inv
    })

    # 日期截取
    # 确保 start_pred 和 end_pred 是日期类型
    import datetime
    if isinstance(start_pred, str):
        start_pred = pd.to_datetime(start_pred).date()
    elif isinstance(start_pred, datetime.datetime):
        start_pred = start_pred.date()
    if isinstance(end_pred, str):
        end_pred = pd.to_datetime(end_pred).date()
    elif isinstance(end_pred, datetime.datetime):
        end_pred = end_pred.date()
    
    mask_date = (result['DATATIME'].dt.date >= start_pred) & \
                (result['DATATIME'].dt.date <= end_pred)
    result = result[mask_date].reset_index(drop=True)

    if len(result) == 0:
        return None, "选定日期范围内无有效预测样本（请确保数据覆盖该时段且不是全夜间数据）"

    # 若原始文件中没有真实 POWER（未来模式），将 POWER_true 置为 NaN
    if mode == 'future':
        # 简单判定：若输入文件该时段 POWER 全为 0/NaN，则视为未来
        result['POWER_true'] = np.nan

    if progress_bar:
        progress_bar.progress(1.0)

    return result, None


# =============================================================================
# 6. 评估 & 可视化（兼容原有系统）
# =============================================================================

def evaluate_model(y_true, y_pred):
    """
    兼容原有接口。自动过滤 NaN（用于未来预测时 y_true 为 NaN 的场景）。
    """
    mask = ~(np.isnan(y_true) | np.isnan(y_pred))
    yt, yp = y_true[mask], y_pred[mask]
    if len(yt) == 0:
        return {'MSE': 0, 'MSE': 0, 'MAE': 0, 'MAPE': 0, 'R2': 0}

    mse = mean_squared_error(yt, yp)
    rmse = np.sqrt(mse)
    mae = mean_absolute_error(yt, yp)
    
    # 计算 MAPE，过滤掉真实值接近 0 的数据
    # 避免分母过小导致 MAPE 异常
    valid_mask = np.abs(yt) > 1e-4  # 只考虑真实值大于 0.0001 的数据
    if np.sum(valid_mask) > 0:
        mape = np.mean(np.abs((yt[valid_mask] - yp[valid_mask]) / (np.abs(yt[valid_mask]) + 1e-8))) * 100
    else:
        mape = 0  # 如果所有真实值都接近 0，MAPE 设为 0
    
    r2 = r2_score(yt, yp)
    return {'MSE': mse, 'RMSE': rmse, 'MAE': mae, 'MAPE': mape, 'R2': r2}


def plot_prediction_comparison(y_true, y_pred, datetimes, title,
                               lower_bounds=None, upper_bounds=None):
    """
    兼容原有接口，返回 plotly Figure。
    """
    fig = go.Figure()

    fig.add_trace(go.Scattergl(
        x=datetimes, y=y_true,
        mode='lines', name='实际功率',
        line=dict(color='#00E4FF', width=1.5)
    ))
    fig.add_trace(go.Scattergl(
        x=datetimes, y=y_pred,
        mode='lines', name='预测功率',
        line=dict(color='#FF6B6B', width=1.5)
    ))

    if lower_bounds is not None and upper_bounds is not None:
        fig.add_trace(go.Scattergl(
            x=datetimes, y=upper_bounds,
            mode='lines', name='上限',
            line=dict(width=0), showlegend=False
        ))
        fig.add_trace(go.Scattergl(
            x=datetimes, y=lower_bounds,
            mode='lines', name='置信区间',
            fill='tonexty', fillcolor='rgba(102,126,234,0.2)',
            line=dict(width=0)
        ))

    fig.update_layout(
        title=title,
        xaxis_title='时间',
        yaxis_title='功率 (kW)',
        hovermode='x unified',
        template='plotly_white'
    )
    return fig


# ==============================================
# CNN-LSTM 模型训练和预测
# ==============================================
def train_cnn_lstm_model(pv_file: str, cfg: dict, progress_bar=None, status_text=None):
    """
    训练 CNN-LSTM 模型
    保存：模型权重、scaler、配置
    """
    from utils.data_loader import load_pv_data
    df = load_pv_data(pv_file)
    base_name = get_safe_name(pv_file)
    save_dir = os.path.join(MODEL_DIR, base_name, 'cnn_lstm')
    os.makedirs(save_dir, exist_ok=True)

    if status_text:
        status_text.text('Step 1/3: 数据预处理...')
    if progress_bar:
        progress_bar.progress(0.1)

    # 准备特征数据（2维输入：辐照度、温度，与 IID 模型保持一致）
    # 辐照度和温度
    weather_features = ['GLOBAL_HORIZONTAL_IRRADIANCE', 'TEMPERATURE']
    
    # 提取气象特征数据
    weather_data = df[weather_features].values
    
    # 提取功率数据
    power_data = np.array(df['POWER'].values).reshape(-1, 1)
    
    # 合并气象特征和功率（用于标准化和创建序列）
    # 顺序：[辐照度, 温度, 功率]
    data = np.hstack([weather_data, power_data])
    
    # 归一化 [0,1]（论文要求）
    scaler = MinMaxScaler(feature_range=(0, 1))
    data_scaled = scaler.fit_transform(data)

    # 构建时序数据
    seq_len = cfg.get('seq_len', 24)
    X, y = create_sequences(data_scaled, seq_len)
    
    # 数据量检查
    if len(X) < 100:
        if status_text:
            status_text.text("数据量不足，训练失败")
        if progress_bar:
            progress_bar.progress(1.0)
        return None

    # 确定设备（GPU 优先）
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    device_info = f'🚀 GPU: {torch.cuda.get_device_name(0)}' if device.type == 'cuda' else '💻 CPU'

    if status_text:
        status_text.text(f'Step 2/3 [{device_info}]: 训练模型...')
    if progress_bar:
        progress_bar.progress(0.3)

    # 划分训练/验证（论文8:2）
    split = int(len(X) * 0.8)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    # 转换为 PyTorch 张量
    X_train = torch.FloatTensor(X_train)
    y_train = torch.FloatTensor(y_train).unsqueeze(-1)
    X_test = torch.FloatTensor(X_test)
    y_test = torch.FloatTensor(y_test).unsqueeze(-1)

    # 创建 DataLoader（批处理，减少内存占用）
    batch_size = cfg.get('batch_size', 16)
    train_dataset = TensorDataset(X_train, y_train)
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    
    test_dataset = TensorDataset(X_test, y_test)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False)

    # 训练模型
    model = CNNLSTMModel(seq_len, 2).to(device)  # 2 是特征维度（辐照度、温度），搬到 GPU
    
    # 打印模型结构（注释掉，避免在命令行显示）
    # print(model)

    # 优化器和损失函数
    lr = cfg.get('lr', 0.001)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.MSELoss()

    # 训练循环
    epochs = cfg.get('epochs', 100)
    patience = cfg.get('patience', 10)
    best_loss = float('inf')
    patience_counter = 0
    
    for epoch in range(epochs):
        model.train()
        train_loss = 0
        
        # 批处理训练
        for batch_X, batch_y in train_loader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)
            optimizer.zero_grad()
            
            # 前向传播
            outputs = model(batch_X)
            loss = criterion(outputs, batch_y)
            
            # 反向传播
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item()
        
        train_loss /= len(train_loader)
        
        # 验证
        model.eval()
        val_loss = 0
        with torch.no_grad():
            for batch_X, batch_y in test_loader:
                batch_X, batch_y = batch_X.to(device), batch_y.to(device)
                val_outputs = model(batch_X)
                val_loss += criterion(val_outputs, batch_y).item()
        
        val_loss /= len(test_loader)
        
        # 每个 epoch 都显示训练信息
        if status_text:
            status_text.text(f"训练中... Epoch {epoch+1}/{epochs} | Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f}")
        
        # 更新进度条
        if progress_bar:
            # 将进度转换为 0-1 之间的值
            progress = 0.3 + (epoch + 1) / epochs * 0.6
            progress_bar.progress(min(progress, 0.9))
        
        # 早停策略
        if val_loss < best_loss:
            best_loss = val_loss
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= patience:
                if status_text:
                    status_text.text(f"早停：Epoch {epoch}, Val Loss: {val_loss:.4f}")
                break

    if status_text:
        status_text.text('Step 3/3: 评估和保存模型...')
    if progress_bar:
        progress_bar.progress(0.9)

    # 评估模型
    model.eval()
    y_pred_list = []
    with torch.no_grad():
        for batch_X, _ in test_loader:
            batch_X = batch_X.to(device)
            y_pred_list.append(model(batch_X).cpu().numpy())
    
    y_pred = np.concatenate(y_pred_list, axis=0)

    # 反归一化（POWER 在最后一列，索引为2）
    power_max = scaler.data_max_[2]
    power_min = scaler.data_min_[2]
    y_pred_real = y_pred * (power_max - power_min) + power_min
    y_test_real = y_test.numpy() * (power_max - power_min) + power_min

    mse = mean_squared_error(y_test_real, y_pred_real)
    mae = mean_absolute_error(y_test_real, y_pred_real)
    r2 = r2_score(y_test_real, y_pred_real)

    # 保存模型和相关文件
    # 保存模型
    torch.save(model.state_dict(), os.path.join(save_dir, 'cnn_lstm_model.pt'))
    
    # 保存scaler
    with open(os.path.join(save_dir, 'scaler.pkl'), 'wb') as f:
        pickle.dump(scaler, f)
    
    # 保存配置
    config = {
        'time_steps': seq_len,
        'feature_dim': 2,  # 2维输入：辐照度、温度
        'weather_features': weather_features,  # 保存气象特征列表
        'scaler_params': {
            'data_max': scaler.data_max_.tolist(),
            'data_min': scaler.data_min_.tolist()
        }
    }
    with open(os.path.join(save_dir, 'config.pkl'), 'wb') as f:
        pickle.dump(config, f)

    if status_text:
        status_text.text(f"训练完成！MSE: {mse:.2f}, MAE: {mae:.2f}, R²: {r2:.4f}")
    if progress_bar:
        progress_bar.progress(1.0)

    return True


def predict_cnn_lstm_model(pv_file, start_date, end_date, model_key='cnn_lstm', mode='historical', progress_bar=None, status_text=None):
    """
    使用训练好的 CNN-LSTM 模型进行预测
    """
    from utils.data_loader import load_pv_data_by_date_range
    
    if status_text:
        status_text.text('加载数据...')
    if progress_bar:
        progress_bar.progress(0.1)
    
    # 加载数据
    df = load_pv_data_by_date_range(pv_file, start_date, end_date)
    if df.empty:
        return None, "数据加载失败"
    
    if status_text:
        status_text.text('准备模型...')
    if progress_bar:
        progress_bar.progress(0.3)
    
    # 加载模型
    base_name = get_safe_name(pv_file)
    save_dir = os.path.join(MODEL_DIR, base_name, 'cnn_lstm')
    
    # 检查模型文件是否存在
    model_path = os.path.join(save_dir, 'cnn_lstm_model.pt')
    scaler_path = os.path.join(save_dir, 'scaler.pkl')
    config_path = os.path.join(save_dir, 'config.pkl')
    
    if not (os.path.exists(model_path) and os.path.exists(scaler_path) and os.path.exists(config_path)):
        return None, "模型文件不存在，请先训练模型"
    
    # 加载scaler
    with open(scaler_path, 'rb') as f:
        scaler = pickle.load(f)
    
    # 加载配置
    with open(config_path, 'rb') as f:
        config = pickle.load(f)
    
    if status_text:
        status_text.text('预测中...')
    if progress_bar:
        progress_bar.progress(0.6)
    
    # 确定设备（GPU 优先）
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    # 准备特征数据（2维输入：辐照度、温度）
    weather_features = config['weather_features']
    weather_data = df[weather_features].values
    power_data = np.array(df['POWER'].values).reshape(-1, 1)
    
    # 合并气象特征和功率（用于标准化）
    data = np.hstack([weather_data, power_data])
    
    # 归一化
    data_scaled = scaler.transform(data)
    
    # 构建时序数据
    X, _ = create_sequences(data_scaled, config['time_steps'])
    
    if len(X) == 0:
        return None, "数据量不足，无法预测"
    
    # 转换为 PyTorch 张量
    X = torch.FloatTensor(X).to(device)
    
    # 加载模型
    model = CNNLSTMModel(config['time_steps'], 2).to(device)  # 2 是特征维度（辐照度、温度）
    model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
    model.eval()
    
    # 预测
    with torch.no_grad():
        y_pred = model(X).cpu().numpy()
    
    # 反归一化（POWER 在最后一列，索引为2）
    power_max = scaler.data_max_[2]
    power_min = scaler.data_min_[2]
    y_pred_real = y_pred * (power_max - power_min) + power_min
    
    # 创建结果DataFrame
    result = pd.DataFrame({
        'DATATIME': df['DATATIME'].iloc[len(df)-len(y_pred):].values,
        'POWER_pred': y_pred_real.flatten()
    })
    
    # 如果是历史回测模式，添加真实值
    if mode == 'historical':
        result['POWER_true'] = df['POWER'].iloc[len(df)-len(y_pred):].values
    
    if status_text:
        status_text.text('预测完成！')
    if progress_bar:
        progress_bar.progress(1.0)
    
    return result, None