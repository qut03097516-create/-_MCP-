import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import math
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from torch.utils.data import TensorDataset, DataLoader

class PositionalEncoding(nn.Module):
    def __init__(self, d_model=64, max_len=1000, batch_first=True):
        super().__init__()
        self.batch_first = batch_first
        position = torch.arange(max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) * (-math.log(10000.0) / d_model))
        pe = torch.zeros(max_len, d_model)
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        if batch_first:
            pe = pe.unsqueeze(0)
        else:
            pe = pe.unsqueeze(1)
        self.register_buffer('pe', pe)

    def forward(self, x):
        if self.batch_first:
            x = x + self.pe[:, :x.size(1)]
        else:
            x = x + self.pe[:x.size(0)]
        return x

class IID_Transformer_LSTM(nn.Module):
    def __init__(self, input_dim=2, d_model=64, nhead=8, num_encoder_layers=2, lstm_hidden=64, lstm_layers=2, dropout=0.1):
        super().__init__()
        self.proj = nn.Linear(input_dim, d_model)
        self.pe = PositionalEncoding(d_model)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=d_model*4,
            dropout=dropout, activation='relu', batch_first=True, norm_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_encoder_layers)
        self.lstm = nn.LSTM(d_model, lstm_hidden, num_layers=lstm_layers, batch_first=True, dropout=dropout)
        self.fc = nn.Sequential(
            nn.Linear(lstm_hidden, 32), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(32, 1)
        )

    def forward(self, x):
        x = self.proj(x)
        x = self.pe(x)
        x = self.transformer(x)
        lstm_out, _ = self.lstm(x)
        out = self.fc(lstm_out[:, -1, :])
        return out

def preprocess_3sigma(df, columns):
    """使用3σ原则检测异常值并用线性插值填充"""
    df = df.copy()
    for col in columns:
        mean = df[col].mean()
        std = df[col].std()
        mask = (df[col] < mean - 3*std) | (df[col] > mean + 3*std)
        df.loc[mask, col] = np.nan
        df[col] = df[col].interpolate(method='linear')
    return df

def convert_to_beijing_time(time_series):
    """
    将时间序列转换为北京时间（Asia/Shanghai）
    :param time_series: pandas Series 或 DatetimeIndex
    :return: 转换后的时间序列（带时区信息）
    """
    # 确保是 datetime 类型
    if not isinstance(time_series, (pd.Series, pd.DatetimeIndex)):
        time_series = pd.to_datetime(time_series)
    
    # 检查是否已经带时区信息
    if isinstance(time_series, pd.Series):
        if pd.api.types.is_datetime64tz_dtype(time_series):
            # 已经有时区，转换为北京时间
            result = time_series.dt.tz_convert('Asia/Shanghai')
        else:
            # 没有时区，假设是UTC时间，先添加UTC时区再转换
            result = time_series.dt.tz_localize('UTC').dt.tz_convert('Asia/Shanghai')
    else:  # DatetimeIndex
        if time_series.tz is not None:
            # 已经有时区，转换为北京时间
            result = time_series.tz_convert('Asia/Shanghai')
        else:
            # 没有时区，假设是UTC时间，先添加UTC时区再转换
            result = time_series.tz_localize('UTC').tz_convert('Asia/Shanghai')
    
    return result

def filter_time_range(df):
    """过滤5:00-20:00时段的数据（使用北京时间）"""
    df = df.copy()
    # 确保时间转换为北京时间
    df['DATATIME'] = convert_to_beijing_time(df['DATATIME'])
    df['hour'] = df['DATATIME'].dt.hour
    df = df[(df['hour'] >= 5) & (df['hour'] <= 20)]
    return df

def split_irradiance_by_boxplot(df):
    """
    按照论文Section 2.2, Equation 1的方法计算箱线图区间
    1. 过滤辐射 > 100 W/m² 的数据
    2. 按月份分为A、B、C、D四组
    3. 每组计算Q1, Q2, Q3, max
    4. 取四组Q1、Q2、Q3的平均值作为区间边界
    5. 取四组max中的最大值作为上限
    
    注意：输入的df应该已经转换为北京时间
    """
    # 论文要求：先过滤辐射 > 100 W/m²
    df_filtered = df[df['GHI'] > 100].copy()
    
    if df_filtered.empty:
        # 如果没有满足条件的数据，使用全局百分位数作为备选
        ghi = df['GHI'].values
        q1 = np.percentile(ghi, 25)
        q2 = np.percentile(ghi, 50)
        q3 = np.percentile(ghi, 75)
        m1, m2, m3, m4 = q1, q2, q3, np.max(ghi)
    else:
        # 论文要求：分为A, B, C, D四组（按月份分）
        # 使用已转换为北京时间的时间列提取月份
        df_filtered['month'] = df_filtered['DATATIME'].dt.month
        groups = [group['GHI'].values for _, group in df_filtered.groupby('month')]
        
        # 如果分组数不足4个，使用全部数据作为一组
        if len(groups) == 0:
            groups = [df_filtered['GHI'].values]
        
        # 每组计算Q1, Q2, Q3, max
        q1s, q2s, q3s, maxs = [], [], [], []
        for ghi_group in groups:
            q1s.append(np.percentile(ghi_group, 25))
            q2s.append(np.percentile(ghi_group, 50))
            q3s.append(np.percentile(ghi_group, 75))
            maxs.append(np.max(ghi_group))
        
        # 取平均
        m1 = np.mean(q1s)
        m2 = np.mean(q2s)
        m3 = np.mean(q3s)
        m4 = np.max(maxs)
    
    splits = [m1, m2, m3, m4]
    
    def get_bin(x):
        if x < m1: return 0
        elif x < m2: return 1
        elif x < m3: return 2
        else: return 3
    
    bins = np.array([get_bin(x) for x in df['GHI']])
    return bins, splits

def remove_outliers_iforest(df):
    X = df[['GHI', 'TEMPERATURE']].values
    clf = IsolationForest(contamination=0.05, random_state=42)
    df['iforest'] = clf.fit_predict(X)
    return df[df['iforest'] == 1].copy()

def build_iid_datasets(df, time_steps=24):
    """
    构建 IID 数据集（不进行归一化，避免数据泄露）
    返回原始数据，归一化将在训练阶段进行
    """
    # 论文要求：过滤5:00-20:00时段的数据
    df = filter_time_range(df)
    
    # 论文要求：先使用3σ原则预处理气象因子和光伏功率
    df = df.dropna(subset=['GHI', 'TEMPERATURE', 'POWER']).copy()
    df = preprocess_3sigma(df, ['GHI', 'TEMPERATURE', 'POWER'])
    
    # 使用论文方法的箱线图区间划分
    bins, splits = split_irradiance_by_boxplot(df)
    df['bin'] = bins

    datasets = []
    for b in range(4):
        d = df[df['bin'] == b].copy()
        
        # 在孤立森林之前已经做了3σ预处理
        d = remove_outliers_iforest(d)
        
        if d.empty:
            datasets.append((np.array([]), np.array([])))
            continue
        
        feat = d[['GHI', 'TEMPERATURE']].values
        power = d['POWER'].values.reshape(-1, 1)

        # 不做归一化，返回原始数据
        X, y = [], []
        for i in range(len(feat) - time_steps):
            X.append(feat[i:i+time_steps, :])
            y.append(power[i+time_steps, 0])
        X, y = np.array(X), np.array(y).reshape(-1, 1)
        datasets.append((X, y))
    
    return datasets, splits

def train_iid_models(datasets, device='cpu', epochs=50, lr=0.001, batch_size=64, patience=10):
    models = []
    feat_scalers = []
    power_scalers = []
    
    for idx, (X, y) in enumerate(datasets):
        if len(X) == 0:
            models.append(None)
            feat_scalers.append(None)
            power_scalers.append(None)
            continue
        
        print(f'训练第 {idx+1} 个区间模型')
        
        # 先切分数据（80/20）
        split_idx = int(len(X) * 0.8)
        X_train_raw, X_val_raw = X[:split_idx], X[split_idx:]
        y_train_raw, y_val_raw = y[:split_idx], y[split_idx:]
        
        # 只用训练数据 fit scaler，避免数据泄露
        # 特征归一化
        feat_scaler = StandardScaler()
        # 展平后fit再恢复形状
        X_train_shape = X_train_raw.shape
        X_train = feat_scaler.fit_transform(X_train_raw.reshape(-1, X_train_shape[-1])).reshape(X_train_shape)
        X_val = feat_scaler.transform(X_val_raw.reshape(-1, X_train_shape[-1])).reshape(X_val_raw.shape)
        
        # 功率归一化
        power_scaler = StandardScaler()
        y_train = power_scaler.fit_transform(y_train_raw)
        y_val = power_scaler.transform(y_val_raw)
        
        # 创建数据集和数据加载器
        train_dataset = TensorDataset(torch.tensor(X_train, dtype=torch.float32), torch.tensor(y_train, dtype=torch.float32))
        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
        
        val_tensor = torch.tensor(X_val, dtype=torch.float32).to(device)
        val_target = torch.tensor(y_val, dtype=torch.float32).to(device)

        model = IID_Transformer_LSTM(input_dim=2).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=lr)
        criterion = nn.MSELoss()
        
        best_val_loss = float('inf')
        best_model_state = None
        patience_counter = 0

        for e in range(epochs):
            model.train()
            epoch_loss = 0
            
            for xb, yb in train_loader:
                xb = xb.to(device)
                yb = yb.to(device)
                
                optimizer.zero_grad()
                pred = model(xb)
                loss = criterion(pred, yb)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()
                epoch_loss += loss.item()
            
            model.eval()
            with torch.no_grad():
                val_pred = model(val_tensor)
                val_loss = criterion(val_pred, val_target).item()
            
            print(f'Epoch {e+1}/{epochs}, Train Loss: {epoch_loss/len(train_loader):.4f}, Val Loss: {val_loss:.4f}')
            
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_model_state = model.state_dict()
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    print(f'Early stopping at epoch {e+1}')
                    break
        
        if best_model_state is not None:
            model.load_state_dict(best_model_state)
        
        models.append(model)
        feat_scalers.append(feat_scaler)
        power_scalers.append(power_scaler)
    
    return models, feat_scalers, power_scalers

def predict_iid(models, df, splits, feat_scalers, power_scalers, look_back=24, device='cpu', batch_size=64):
    """
    IID 模型预测函数
    :param models: 训练好的模型列表
    :param df: 测试数据
    :param splits: 区间边界
    :param feat_scalers: 特征归一化器（来自训练阶段）
    :param power_scalers: 功率归一化器（来自训练阶段）
    :param look_back: 时间步长
    :param device: 设备
    :param batch_size: 批大小
    :return: 预测结果DataFrame（包含原始尺度的功率值）
    """
    # 论文要求：过滤5:00-20:00时段的数据
    df = filter_time_range(df)
    
    # 移除缺失值（不再在测试集上做3σ预处理，避免使用测试集统计量）
    df = df.dropna(subset=['GHI', 'TEMPERATURE', 'POWER']).copy()
    
    interval_bins = [0, 1, 2, 3]
    interval_datetimes = {b: [] for b in interval_bins}
    interval_sequences = {b: [] for b in interval_bins}
    interval_true_values = {b: [] for b in interval_bins}
    
    for i in range(look_back, len(df)):
        row = df.iloc[i]
        ghi = row['GHI']

        if ghi < splits[0]: b = 0
        elif ghi < splits[1]: b = 1
        elif ghi < splits[2]: b = 2
        else: b = 3

        model = models[b]
        feat_scaler = feat_scalers[b]
        if model is None or feat_scaler is None:
            continue

        seq = df.iloc[i-look_back:i][['GHI', 'TEMPERATURE']].values
        # 使用训练集的scaler进行转换
        seq_norm = feat_scaler.transform(seq)
        interval_sequences[b].append(seq_norm)
        interval_true_values[b].append(row['POWER'])
        interval_datetimes[b].append(row['DATATIME'])
    
    all_datetime = []
    all_true = []
    all_pred = []
    
    for b in interval_bins:
        if not interval_sequences[b]:
            continue
        
        model = models[b]
        power_scaler = power_scalers[b]
        if model is None or power_scaler is None:
            continue
        
        seqs = np.array(interval_sequences[b])
        model.eval()
        
        num_batches = (len(seqs) + batch_size - 1) // batch_size
        batch_predictions = []
        
        for batch_idx in range(num_batches):
            start_idx = batch_idx * batch_size
            end_idx = min((batch_idx + 1) * batch_size, len(seqs))
            batch_seq = seqs[start_idx:end_idx]
            
            batch_tensor = torch.tensor(batch_seq, dtype=torch.float32).to(device)
            with torch.no_grad():
                batch_pred = model(batch_tensor).cpu().numpy()
            batch_predictions.append(batch_pred)
        
        predictions = np.concatenate(batch_predictions).flatten()
        
        # 反归一化：将预测值转换回原始尺度
        predictions = power_scaler.inverse_transform(predictions.reshape(-1, 1)).flatten()
        
        all_pred.extend(predictions.tolist())
        all_true.extend(interval_true_values[b])
        all_datetime.extend(interval_datetimes[b])
    
    # 创建结果DataFrame并按时间排序
    result = pd.DataFrame({
        'DATATIME': all_datetime, 
        'POWER_true': all_true, 
        'POWER_pred': all_pred
    })
    
    # 按时间排序（修复时间顺序被打乱的问题）
    result = result.sort_values('DATATIME').reset_index(drop=True)
    
    return result