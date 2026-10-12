"""配置文件 - 提取所有硬编码参数"""
from datetime import time


# 预处理配置
PREPROCESS_CONFIG = {
    'day_start': time(5, 0),          # 发电时段开始时间
    'day_end': time(20, 0),           # 发电时段结束时间
    'sigma_threshold': 3.0,            # 3σ 异常检测阈值
    'isolation_forest_contamination': 0.05,  # 孤立森林污染率
    'min_samples_per_bin': 10,         # 每个辐照区间最小样本数
    'train_val_split': 0.8             # 训练验证集比例
}

# 模型训练配置
TRAIN_CONFIG = {
    'default_epochs': 50,
    'default_batch_size': 64,
    'default_lr': 0.001,
    'default_patience': 10,
    'default_seq_len': 12,
    'default_d_model': 64,
    'default_nhead': 8,
    'default_num_encoder_layers': 2,
    'default_lstm_hidden': 64,
    'default_lstm_layers': 2,
    'default_dropout': 0.1
}

# 绘图配置
PLOT_CONFIG = {
    'max_plot_points': 2000,           # 绘图最大点数
    'default_resample_freq': '1H'       # 默认重采样频率
}

# 数据加载配置
DATA_CONFIG = {
    'data_dir': 'data',                # 数据目录
    'model_dir': 'models',             # 模型保存目录
    'cache_ttl': 3600                  # 缓存过期时间（秒）
}
