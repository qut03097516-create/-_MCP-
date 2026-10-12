import pandas as pd
import numpy as np
from pathlib import Path
from functools import lru_cache
import duckdb

# 经纬度 → 省份 工具类（使用本地文件）
class GeoProvinceFinder:
    def __init__(self):
        # 加载中国省级地图数据
        try:
            import geopandas as gpd
            from shapely.geometry import Point
            
            # 使用本地文件加载数据
            local_file = Path('data/china_provinces.json')
            if local_file.exists():
                print("使用本地地理数据文件")
                self.provinces = gpd.read_file(local_file)
                self.available = True
            else:
                print("本地地理数据文件不存在")
                self.available = False
        except Exception as e:
            print(f"无法加载地理数据: {e}")
            self.available = False
    
    def get_province(self, lon: float, lat: float):
        """
        输入经纬度 → 返回省份名称
        :param lon: 经度 (如 116.403876)
        :param lat: 纬度 (如 39.914885)
        :return: 省份名称 如 "北京"
        """
        # 特殊处理台湾省（更精确的坐标范围，避免与福建重叠）
        # 台湾岛的精确坐标范围
        if 120.0 <= lon <= 122.0 and 21.8 <= lat <= 25.3:
            # 进一步排除金门、马祖等离岛，这些属于福建省
            # 金门岛：约118.3°E, 24.4°N
            # 马祖岛：约119.9°E, 26.1°N
            if not ((118.2 <= lon <= 118.4 and 24.3 <= lat <= 24.5) or 
                    (119.8 <= lon <= 120.0 and 26.0 <= lat <= 26.2)):
                return "台湾"
        
        if not self.available:
            return "未知"
        
        # 使用精确的地理边界方法
        from shapely.geometry import Point
        point = Point(lon, lat)
        
        for idx, row in self.provinces.iterrows():
            if row.geometry.contains(point):
                name = row["name"]
                # 清洗成数据库里的格式
                return self._clean_name(name)
        return "未知"
    
    def _clean_name(self, name):
        # 把 "北京市" → "北京"，"新疆维吾尔自治区" → "新疆"
        replace_dict = {
            "市": "", "自治区": "", "省": "", "回族": "", "壮族": "", "维吾尔": ""
        }
        for k, v in replace_dict.items():
            name = name.replace(k, v)
        return name

# 创建全局的GeoProvinceFinder实例
_geo_finder = None

def get_geo_finder():
    # 获取 GeoProvinceFinder 实例（单例模式）
    global _geo_finder
    if _geo_finder is None:
        _geo_finder = GeoProvinceFinder()
    return _geo_finder

@lru_cache(maxsize=32)
def get_data_files(data_dir='data'):
    # 从数据库获取所有光伏站点信息（带缓存）
    db_path = 'data/pv_data.duckdb'
    
    try:
        # 快速连接数据库
        conn = duckdb.connect(db_path)
        
        # 从 pv_data 表中获取站点信息（使用 DISTINCT 避免重复）
        query = '''
        SELECT DISTINCT filename, province
        FROM pv_data
        WHERE province IS NOT NULL
        ORDER BY province, filename
        '''
        
        # 快速执行查询
        df = conn.execute(query).df()
        conn.close()
        
        if df.empty:
            # 如果数据库中没有数据，回退到文件系统
            pv_files = []
            for file in Path(data_dir).glob('*.csv'):
                filename = file.name
                if filename.endswith('.csv') and filename.startswith('Timeseries_'):
                    pv_files.append(filename)
            return sorted(pv_files)
        
        # 生成站点显示名称
        sites = []
        for _, row in df.iterrows():
            province = row['province']
            if province:
                display_name = f"{province} - {row['filename']}"
            else:
                display_name = f"未知 - {row['filename']}"
            sites.append(display_name)
        
        return sorted(sites)
        
    except Exception as e:
        print(f"从数据库获取站点失败: {e}")
        # 回退到文件系统
        pv_files = []
        for file in Path(data_dir).glob('*.csv'):
            filename = file.name
            if filename.endswith('.csv') and filename.startswith('Timeseries_'):
                pv_files.append(filename)
        return sorted(pv_files)


def get_raw_filename(display_name):
    # 从显示名称中提取原始文件名
    if " - " in display_name:
        return display_name.split(" - ", 1)[1]
    return display_name


@lru_cache(maxsize=32)
def get_date_range(pv_file, data_dir='data'):
    # 优化：从数据库获取日期范围，避免读取 CSV 文件
    # 极大减少 IO，特别适合大 CSV 文件
    # 提取原始文件名
    raw_filename = get_raw_filename(pv_file)
    
    db_path = 'data/pv_data.duckdb'
    conn = duckdb.connect(db_path)
    
    try:
        # 从数据库中查询最小和最大日期
        query = '''
        SELECT MIN(datatime) as min_date, MAX(datatime) as max_date
        FROM pv_data 
        WHERE filename = ?
        '''
        
        result = conn.execute(query, [raw_filename]).fetchone()
        
        if result and result[0] and result[1]:
            min_date = pd.to_datetime(result[0]).date()
            max_date = pd.to_datetime(result[1]).date()
            # T6: 最大日可能是不完整日（如仅 00:30~07:30 的几行）。
            # 完整日容忍少量缺失按 <22 行判定不完整；
            # 不完整则回退到最后一个完整日，避免默认日期落在 2024-01-01 这类不完整日上。
            if _day_row_count(conn, raw_filename, max_date) < 22:
                full = conn.execute("""
                    SELECT CAST(DATATIME AS DATE) AS d, COUNT(*) AS n
                    FROM pv_data
                    WHERE filename = ? AND CAST(DATATIME AS DATE) < ?
                    GROUP BY d HAVING n >= 22
                    ORDER BY d DESC LIMIT 1
                """, [raw_filename, max_date]).fetchone()
                if full:
                    max_date = pd.Timestamp(full[0]).date()
            return min_date, max_date
        else:
            from datetime import datetime
            return datetime(2023, 1, 1).date(), datetime(2023, 12, 31).date()
    except Exception:
        from datetime import datetime
        return datetime(2023, 1, 1).date(), datetime(2023, 12, 31).date()
    finally:
        conn.close()


def _day_row_count(conn, raw_filename, day) -> int:
    """某站某日的数据行数（用于判定最大日是否为不完整日）。"""
    row = conn.execute("""
        SELECT COUNT(*) FROM pv_data
        WHERE filename = ? AND CAST(DATATIME AS DATE) = ?
    """, [raw_filename, day]).fetchone()
    return int(row[0]) if row else 0

def downsample_for_plot(df, max_points=2000, freq='1H'):
    """
    降采样函数，仅用于绘图，不影响指标计算
    只对数值列求平均，保留时间索引
    """
    if len(df) <= max_points:
        return df

    if 'DATATIME' not in df.columns:
        return df
        
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    # 确保 DATATIME 不在 numeric_cols 里
    numeric_cols = [c for c in numeric_cols if c != 'DATATIME']
    
    if len(numeric_cols) == 0:
        return df

    # 确保频率格式正确
    if freq == 'H':
        freq = '1H'
    
    try:
        result = df.set_index('DATATIME')[numeric_cols].resample(freq).mean().reset_index()
        # 显式确保时间列名正确
        if 'index' in result.columns:
            result = result.rename(columns={'index': 'DATATIME'})
        return result
    except Exception as e:
        # 如果重采样失败，返回原始数据
        return df

@lru_cache(maxsize=32)
def load_pv_data(filename, data_dir='data'):
    """从数据库加载光伏数据，返回DataFrame（带缓存）"""
    # 提取原始文件名
    raw_filename = get_raw_filename(filename)
    
    db_path = 'data/pv_data.duckdb'
    conn = duckdb.connect(db_path)

    try:
        query = '''
        SELECT
            CAST(datatime AS TEXT) AS DATATIME,
            CAST(power AS REAL) AS POWER,
            CAST(global_horizontal_irradiance AS REAL) AS GLOBAL_HORIZONTAL_IRRADIANCE,
            CAST(temperature AS REAL) AS TEMPERATURE,
            CAST(windspeed AS REAL) AS WINDSPEED,
            CAST(gb AS REAL) AS Gb,
            CAST(gd AS REAL) AS Gd,
            CAST(gr AS REAL) AS Gr,
            CAST(h_sun AS REAL) AS H_sun,
            CAST(int AS REAL) AS Int
        FROM pv_data
        WHERE filename = ?
        ORDER BY datatime
        '''

        df = conn.execute(query, [raw_filename]).df()
        
        # Parse dates
        if 'DATATIME' in df.columns:
            df['DATATIME'] = pd.to_datetime(df['DATATIME'])
        
        return df
    finally:
        conn.close()

@lru_cache(maxsize=32)
def load_pv_data_by_date_range(filename, start_date, end_date, data_dir='data'):
    """从数据库加载指定日期范围的光伏数据，返回DataFrame（带缓存）"""
    # 提取原始文件名
    raw_filename = get_raw_filename(filename)
    
    db_path = 'data/pv_data.duckdb'
    conn = duckdb.connect(db_path)
    
    try:
        query = '''
        SELECT
            CAST(datatime AS TEXT) AS DATATIME,
            CAST(power AS REAL) AS POWER,
            CAST(global_horizontal_irradiance AS REAL) AS GLOBAL_HORIZONTAL_IRRADIANCE,
            CAST(temperature AS REAL) AS TEMPERATURE,
            CAST(windspeed AS REAL) AS WINDSPEED,
            CAST(gb AS REAL) AS Gb,
            CAST(gd AS REAL) AS Gd,
            CAST(gr AS REAL) AS Gr,
            CAST(h_sun AS REAL) AS H_sun,
            CAST(int AS REAL) AS Int
        FROM pv_data
        WHERE filename = ? AND datatime >= ? AND datatime <= ?
        ORDER BY datatime
        '''
        
        start_str = pd.to_datetime(start_date).strftime('%Y-%m-%d')
        end_str = pd.to_datetime(end_date).strftime('%Y-%m-%d 23:59:59')
        
        df = conn.execute(query, [raw_filename, start_str, end_str]).df()
        
        # Parse dates
        if 'DATATIME' in df.columns:
            df['DATATIME'] = pd.to_datetime(df['DATATIME'])
        
        return df
    finally:
        conn.close()

@lru_cache(maxsize=32)
def load_pv_data_with_pagination(filename, start_date, end_date, page=1, page_size=1000, data_dir='data'):
    """从数据库加载指定日期范围的光伏数据，支持分页（带缓存）"""
    # 提取原始文件名
    raw_filename = get_raw_filename(filename)
    
    db_path = 'data/pv_data.duckdb'
    conn = duckdb.connect(db_path)
    
    try:
        # 计算偏移量
        offset = (page - 1) * page_size
        
        query = '''
        SELECT
            CAST(datatime AS TEXT) AS DATATIME,
            CAST(power AS REAL) AS POWER,
            CAST(global_horizontal_irradiance AS REAL) AS GLOBAL_HORIZONTAL_IRRADIANCE,
            CAST(temperature AS REAL) AS TEMPERATURE,
            CAST(windspeed AS REAL) AS WINDSPEED,
            CAST(gb AS REAL) AS Gb,
            CAST(gd AS REAL) AS Gd,
            CAST(gr AS REAL) AS Gr,
            CAST(h_sun AS REAL) AS H_sun,
            CAST(int AS REAL) AS Int
        FROM pv_data
        WHERE filename = ? AND datatime >= ? AND datatime <= ?
        ORDER BY datatime
        LIMIT ? OFFSET ?
        '''
        
        start_str = pd.to_datetime(start_date).strftime('%Y-%m-%d')
        end_str = pd.to_datetime(end_date).strftime('%Y-%m-%d 23:59:59')
        
        # 执行分页查询
        df = conn.execute(query, [raw_filename, start_str, end_str, page_size, offset]).df()
        
        # 解析日期
        if 'DATATIME' in df.columns:
            df['DATATIME'] = pd.to_datetime(df['DATATIME'])
        
        # 获取总记录数
        count_query = '''
        SELECT COUNT(*)
        FROM pv_data
        WHERE filename = ? AND datatime >= ? AND datatime <= ?
        '''
        total_count = conn.execute(count_query, [raw_filename, start_str, end_str]).fetchone()[0]
        
        return df, total_count
    finally:
        conn.close()


def load_pv_data_with_chunks(filename, start_date, end_date, chunksize=10000, data_dir='data'):
    """从数据库加载指定日期范围的光伏数据，支持分块读取"""
    # 提取原始文件名
    raw_filename = get_raw_filename(filename)
    
    db_path = 'data/pv_data.duckdb'
    conn = duckdb.connect(db_path)
    
    try:
        query = '''
        SELECT
            CAST(datatime AS TEXT) AS DATATIME,
            CAST(power AS REAL) AS POWER,
            CAST(global_horizontal_irradiance AS REAL) AS GLOBAL_HORIZONTAL_IRRADIANCE,
            CAST(temperature AS REAL) AS TEMPERATURE,
            CAST(windspeed AS REAL) AS WINDSPEED,
            CAST(gb AS REAL) AS Gb,
            CAST(gd AS REAL) AS Gd,
            CAST(gr AS REAL) AS Gr,
            CAST(h_sun AS REAL) AS H_sun,
            CAST(int AS REAL) AS Int
        FROM pv_data
        WHERE filename = ? AND datatime >= ? AND datatime <= ?
        ORDER BY datatime
        '''
        
        start_str = pd.to_datetime(start_date).strftime('%Y-%m-%d')
        end_str = pd.to_datetime(end_date).strftime('%Y-%m-%d 23:59:59')
        
        # 执行查询并获取所有数据
        df = conn.execute(query, [raw_filename, start_str, end_str]).df()
        
        # 解析日期
        if 'DATATIME' in df.columns:
            df['DATATIME'] = pd.to_datetime(df['DATATIME'])
        
        # 分块返回数据
        chunks = []
        for i in range(0, len(df), chunksize):
            chunks.append(df.iloc[i:i+chunksize])
        
        return chunks
    finally:
        conn.close()


def preprocess_data(df):
    """
    预处理光伏数据
    :param df: 原始数据DataFrame
    :return: 预处理后的数据和特征列
    """
    if df.empty:
        return df, []
    
    # 复制数据以避免修改原始数据
    df_clean = df.copy()
    
    # 处理缺失值
    if not df_clean.empty:
        # 填充缺失值（使用前向填充）
        df_clean = df_clean.ffill()
        # 再使用后向填充确保所有缺失值都被处理
        df_clean = df_clean.bfill()
    
    # 提取特征列（所有数值列）
    numeric_cols = df_clean.select_dtypes(include=[np.number]).columns.tolist()
    # 移除可能的时间列
    features_cols = [col for col in numeric_cols if col not in ['DATATIME']]
    
    return df_clean, features_cols
