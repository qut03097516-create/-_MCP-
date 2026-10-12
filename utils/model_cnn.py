import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import os
import pickle

# ==============================================
# 1. 超参数（完全按照论文设置）
# ==============================================
TIME_STEPS = 24          # 时间步长（24小时）
FEATURE_DIM = 2          # 特征：辐照度、温度（与 IID 模型保持一致）
CNN_FILTERS = 32         # 卷积输出通道
LSTM_UNITS1 = 64         # LSTM第一层
LSTM_UNITS2 = 128        # LSTM第二层
DROPOUT_RATE = 0.3       # Dropout
LEARNING_RATE = 0.001
BATCH_SIZE = 64
EPOCHS = 100

# ==============================================
# 2. 构建优化的 1D CNN-LSTM 模型（PyTorch 版本）
# ==============================================
class CNNLSTMModel(nn.Module):
    # 单站点务实方案：1D卷积处理时序特征，但严格遵循论文其他设置
    # 论文CNN的核心价值：局部特征提取 + 降维 → 交给LSTM
    # 2维输入（与 IID 模型保持一致）：辐照度、温度
    def __init__(self, time_steps=24, n_features=2):
        super(CNNLSTMModel, self).__init__()
        self.time_steps = time_steps
        self.n_features = n_features
        
        # 1D卷积提取局部时序模式
        self.conv1 = nn.Conv1d(n_features, 32, kernel_size=3, padding=1)
        self.pool1 = nn.MaxPool1d(kernel_size=2, stride=2)
        
        self.conv2 = nn.Conv1d(32, 32, kernel_size=3, padding=1)
        self.pool2 = nn.MaxPool1d(kernel_size=2, stride=2)
        
        self.conv3 = nn.Conv1d(32, 32, kernel_size=3, padding=1)
        self.pool3 = nn.MaxPool1d(kernel_size=2, stride=2)
        
        self.dropout1 = nn.Dropout(0.3)
        
        # 2层LSTM: 64→128
        # 注意：PyTorch LSTM 输入维度是 (batch, seq_len, features)
        self.lstm1 = nn.LSTM(32, 64, batch_first=True)
        self.lstm2 = nn.LSTM(64, 128, batch_first=True)
        self.dropout2 = nn.Dropout(0.3)
        
        self.fc = nn.Linear(128, 1)
    
    def forward(self, x):
        # x shape: (batch, seq_len, features)
        # 转换为 (batch, features, seq_len) 用于 Conv1d
        x = x.permute(0, 2, 1)
        
        x = torch.relu(self.conv1(x))
        x = self.pool1(x)
        
        x = torch.relu(self.conv2(x))
        x = self.pool2(x)
        
        x = torch.relu(self.conv3(x))
        x = self.pool3(x)
        
        x = self.dropout1(x)
        
        # 转换回 (batch, seq_len, features) 用于 LSTM
        x = x.permute(0, 2, 1)
        
        x, _ = self.lstm1(x)
        x, _ = self.lstm2(x)
        # 取最后一个时间步的输出
        x = x[:, -1, :]
        x = self.dropout2(x)
        
        x = self.fc(x)
        return x

# 为保持兼容性，保留原函数名
def build_cnn_lstm_model(time_steps, feature_dim=2):
    return CNNLSTMModel(time_steps, feature_dim)

# ==============================================
# 3. 构造时序样本（滑动窗口）
# ==============================================
def create_sequences(data, time_steps=24):
    """
    构造时序样本。
    data: 包含所有特征的数组 [辐照度, 温度, ...]
    返回: 
        X: 气象特征序列 [samples, time_steps, 2] (辐照度、温度)
        y: 功率目标 [samples, 1]
    """
    X, y = [], []
    for i in range(len(data) - time_steps):
        # X 只取辐照度和温度（前2列）
        X.append(data[i:i + time_steps, :2])
        # y 取功率（最后一列）
        y.append(data[i + time_steps, -1])
    return np.array(X), np.array(y)