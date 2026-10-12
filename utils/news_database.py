import sqlite3
import pandas as pd
from datetime import datetime
import hashlib
import secrets

class PVSystemDatabase:
    """光伏系统数据库管理类"""
    
    def __init__(self, db_path='data/pv_system.db'):
        """初始化数据库连接"""
        self.db_path = db_path
        self._init_db()
    
    def _get_connection(self):
        """获取优化的数据库连接"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        
        # ✅ SQLite PRAGMA 优化
        cursor.execute('PRAGMA journal_mode=WAL')          # 读写不互相阻塞，并发读快2-3倍
        cursor.execute('PRAGMA cache_size=-64000')         # 64MB内存缓存页
        cursor.execute('PRAGMA synchronous=NORMAL')        # 降低同步频率，写入快2倍
        cursor.execute('PRAGMA mmap_size=268435456')      # 256MB内存映射
        cursor.execute('PRAGMA foreign_keys=ON')           # 启用外键约束
        
        return conn
    
    def _init_db(self):
        """初始化数据库表结构"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 1. 新闻表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            source TEXT,
            url TEXT,
            category TEXT,
            publish_time TEXT
        )
        ''')
        
        # 2. 用户表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT,
            role TEXT DEFAULT 'user',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT,
            is_active INTEGER DEFAULT 1,
            avatar TEXT
        )
        ''')
        # 兼容旧库：补 avatar / last_seen 列
        cursor.execute('PRAGMA table_info(users)')
        user_cols = {row[1] for row in cursor.fetchall()}
        if 'avatar' not in user_cols:
            cursor.execute('ALTER TABLE users ADD COLUMN avatar TEXT')
        if 'last_seen' not in user_cols:
            cursor.execute('ALTER TABLE users ADD COLUMN last_seen TEXT')

        # 用户操作日志（登录/接口活动等）
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            action TEXT,
            method TEXT,
            path TEXT,
            ip TEXT,
            status_code INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_user_logs_created ON user_logs(created_at)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_user_logs_user ON user_logs(user_id)'
        )

        # 3. 预测历史表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS prediction_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            pv_file TEXT,
            prediction_date TEXT,
            start_date TEXT,
            end_date TEXT,
            model_type TEXT,
            result_summary TEXT,
            result_data TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        ''')
        
        # 4. 模型训练记录表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS training_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            model_name TEXT,
            pv_file TEXT,
            training_date TEXT,
            metrics TEXT,
            parameters TEXT,
            status TEXT DEFAULT 'completed',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        ''')
        
        # 5. 系统公告表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT,
            priority TEXT DEFAULT 'normal',
            is_pinned INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER,
            expire_date TEXT,
            is_active INTEGER DEFAULT 1
        )
        ''')
        
        # 6. 查询历史表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS query_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            pv_file TEXT,
            query_conditions TEXT,
            result_count INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        ''')
        
        # 7. 知识库表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS model_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            keywords TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_publish_time ON news(publish_time)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_source ON news(source)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_news_category ON news(category)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_prediction_user ON prediction_history(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_training_user ON training_history(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_announcements_active ON announcements(is_active)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_category ON model_knowledge(category)')
        
        conn.commit()
        conn.close()
    
    # ==================== 用户管理 ====================
    
    def _hash_password(self, password, salt=None):
        """密码哈希"""
        if salt is None:
            salt = secrets.token_hex(16)
        password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return salt + password_hash.hex()
    
    def _verify_password(self, password, password_hash):
        """验证密码"""
        salt = password_hash[:32]
        stored_hash = password_hash[32:]
        password_hash_new = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
        return password_hash_new == stored_hash
    
    def create_user(self, username, password, email=None, role='user'):
        """创建用户，返回用户 dict 或 None"""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            password_hash = self._hash_password(password)
            cursor.execute('''
            INSERT INTO users (username, password_hash, email, role)
            VALUES (?, ?, ?, ?)
            ''', (username, password_hash, email, role))
            conn.commit()
            user_id = cursor.lastrowid
            # 返回完整用户信息
            cursor.execute('SELECT id, username, email, role, created_at, avatar FROM users WHERE id = ?', (user_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'username': row[1],
                    'email': row[2],
                    'role': row[3],
                    'created_at': row[4] or '',
                    'avatar': row[5] or '',
                }
            return None
        except sqlite3.IntegrityError:
            return None
        finally:
            conn.close()
    
    def authenticate_user(self, username, password):
        """用户登录验证"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, password_hash, role, created_at, last_login, email, avatar FROM users WHERE username = ? AND is_active = 1', (username,))
        result = cursor.fetchone()
        if result:
            user_id, password_hash, role, created_at, last_login, email, avatar = result
            if self._verify_password(password, password_hash):
                cursor.execute('UPDATE users SET last_login = ? WHERE id = ?', (datetime.now().isoformat(), user_id))
                conn.commit()
                conn.close()
                return {
                    'id': user_id, 'username': username, 'role': role,
                    'created_at': created_at, 'last_login': last_login,
                    'email': email or '', 'avatar': avatar or '',
                }
        conn.close()
        return None

    def get_user(self, user_id):
        """获取用户完整信息（含 password_hash、avatar）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, username, email, role, created_at, last_login, password_hash, avatar '
            'FROM users WHERE id = ?', (user_id,)
        )
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                'id': result[0], 'username': result[1], 'email': result[2] or '',
                'role': result[3], 'created_at': result[4], 'last_login': result[5],
                'password_hash': result[6], 'avatar': result[7] or '',
            }
        return None

    def get_user_by_id(self, user_id):
        """获取用户信息"""
        user = self.get_user(user_id)
        if user:
            user.pop('password_hash', None)
        return user

    def get_user_by_username(self, username):
        """根据用户名获取用户"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, username, email, role, created_at, last_login, avatar '
            'FROM users WHERE username = ?', (username,)
        )
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                'id': result[0], 'username': result[1], 'email': result[2] or '',
                'role': result[3], 'created_at': result[4], 'last_login': result[5],
                'avatar': result[6] or '',
            }
        return None

    def get_all_users(self):
        """获取所有用户"""
        conn = self._get_connection()
        df = pd.read_sql_query(
            'SELECT id, username, email, role, created_at, last_login, is_active, avatar FROM users',
            conn
        )
        conn.close()
        return df

    def verify_password(self, password, password_hash):
        """公开的密码校验"""
        if not password_hash:
            return False
        return self._verify_password(password, password_hash)

    def update_user_password(self, user_id, new_password):
        """更新用户密码"""
        conn = self._get_connection()
        cursor = conn.cursor()
        password_hash = self._hash_password(new_password)
        cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash, user_id))
        conn.commit()
        conn.close()

    def update_user_avatar(self, user_id, avatar):
        """更新用户头像（data URL 或空字符串）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET avatar = ? WHERE id = ?', (avatar or '', user_id))
        conn.commit()
        conn.close()
        return True
    

    
    def touch_user_presence(self, user_id):
        """刷新用户最近活跃时间（在线状态）"""
        if not user_id:
            return
        conn = self._get_connection()
        try:
            conn.execute(
                'UPDATE users SET last_seen = ? WHERE id = ?',
                (datetime.now().isoformat(timespec='seconds'), user_id)
            )
            conn.commit()
        finally:
            conn.close()

    def log_user_action(self, user_id, username, action, method='', path='', ip='', status_code=None):
        """写入用户操作日志；自动裁剪过旧记录"""
        conn = self._get_connection()
        try:
            conn.execute(
                '''
                INSERT INTO user_logs (user_id, username, action, method, path, ip, status_code, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    user_id,
                    username or '',
                    action or '',
                    method or '',
                    path or '',
                    ip or '',
                    status_code,
                    datetime.now().isoformat(timespec='seconds'),
                )
            )
            # 保留最近 20000 条
            conn.execute(
                '''
                DELETE FROM user_logs WHERE id NOT IN (
                    SELECT id FROM user_logs ORDER BY id DESC LIMIT 20000
                )
                '''
            )
            conn.commit()
        finally:
            conn.close()

    def get_online_users(self, window_seconds=300):
        """最近 window_seconds 内活跃过的用户"""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(seconds=window_seconds)).isoformat(timespec='seconds')
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT id, username, role, last_seen, last_login, is_active, avatar
                FROM users
                WHERE last_seen IS NOT NULL AND last_seen >= ?
                ORDER BY last_seen DESC
                ''',
                (cutoff,)
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [
            {
                'id': r[0],
                'username': r[1],
                'role': r[2] or 'user',
                'last_seen': r[3] or '',
                'last_login': r[4] or '',
                'is_active': int(r[5] or 1),
                'avatar': r[6] or '',
            }
            for r in rows
        ]

    def get_user_logs(self, limit=200, username=None, action=None):
        """最近用户操作日志"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            sql = (
                'SELECT id, user_id, username, action, method, path, ip, status_code, created_at '
                'FROM user_logs'
            )
            clauses = []
            params = []
            if username:
                clauses.append('username = ?')
                params.append(username)
            if action:
                clauses.append('action = ?')
                params.append(action)
            if clauses:
                sql += ' WHERE ' + ' AND '.join(clauses)
            sql += ' ORDER BY id DESC LIMIT ?'
            params.append(int(limit))
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [
            {
                'id': r[0],
                'user_id': r[1],
                'username': r[2] or '',
                'action': r[3] or '',
                'method': r[4] or '',
                'path': r[5] or '',
                'ip': r[6] or '',
                'status_code': r[7],
                'created_at': r[8] or '',
            }
            for r in rows
        ]

    # ==================== 预测历史 ====================
    
    def save_prediction(self, user_id, pv_file, prediction_date, start_date, end_date, model_type, result_summary, result_data):
        """保存预测记录"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO prediction_history (user_id, pv_file, prediction_date, start_date, end_date, model_type, result_summary, result_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, pv_file, prediction_date, start_date, end_date, model_type, result_summary, result_data))
        conn.commit()
        conn.close()
    
    def get_prediction_history(self, user_id=None, limit=50):
        """获取预测历史"""
        conn = self._get_connection()
        if user_id:
            df = pd.read_sql_query('''
            SELECT * FROM prediction_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?
            ''', conn, params=[user_id, limit])
        else:
            df = pd.read_sql_query('SELECT * FROM prediction_history ORDER BY created_at DESC LIMIT ?', conn, params=[limit])
        conn.close()
        return df
    
    def delete_prediction(self, prediction_id):
        """删除预测记录"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM prediction_history WHERE id = ?', (prediction_id,))
        conn.commit()
        conn.close()
    
    # ==================== 模型训练记录 ====================
    
    def save_training_record(self, user_id, model_name, pv_file, training_date, metrics, parameters, status='completed'):
        """保存训练记录"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO training_history (user_id, model_name, pv_file, training_date, metrics, parameters, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, model_name, pv_file, training_date, metrics, parameters, status))
        conn.commit()
        conn.close()
    
    def get_training_history(self, user_id=None, limit=50):
        """获取训练历史"""
        conn = self._get_connection()
        if user_id:
            df = pd.read_sql_query('''
            SELECT * FROM training_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?
            ''', conn, params=[user_id, limit])
        else:
            df = pd.read_sql_query('SELECT * FROM training_history ORDER BY created_at DESC LIMIT ?', conn, params=[limit])
        conn.close()
        return df
    
    def delete_training_record(self, training_id):
        """删除训练记录"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM training_history WHERE id = ?', (training_id,))
        conn.commit()
        conn.close()
    
    # ==================== 系统公告 ====================
    
    def create_announcement(self, title, content, priority='normal', is_pinned=0, created_by=None, expire_date=None):
        """创建公告"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO announcements (title, content, priority, is_pinned, created_by, expire_date)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (title, content, priority, is_pinned, created_by, expire_date))
        conn.commit()
        conn.close()
    
    def get_active_announcements(self):
        """获取活跃公告"""
        conn = self._get_connection()
        now = datetime.now().isoformat()
        df = pd.read_sql_query('''
        SELECT * FROM announcements
        WHERE is_active = 1 AND (expire_date IS NULL OR expire_date > ?)
        ORDER BY is_pinned DESC, priority DESC, created_at DESC
        ''', conn, params=[now])
        conn.close()
        return df
    
    def delete_announcement(self, announcement_id):
        """删除公告"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE announcements SET is_active = 0 WHERE id = ?', (announcement_id,))
        conn.commit()
        conn.close()
    
    # ==================== 查询历史 ====================
    
    def save_query_history(self, user_id, pv_file, query_conditions, result_count):
        """保存查询历史"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO query_history (user_id, pv_file, query_conditions, result_count)
        VALUES (?, ?, ?, ?)
        ''', (user_id, pv_file, query_conditions, result_count))
        conn.commit()
        conn.close()
    
    def get_query_history(self, user_id=None, limit=50):
        """获取查询历史"""
        conn = self._get_connection()
        if user_id:
            df = pd.read_sql_query('''
            SELECT * FROM query_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?
            ''', conn, params=[user_id, limit])
        else:
            df = pd.read_sql_query('SELECT * FROM query_history ORDER BY created_at DESC LIMIT ?', conn, params=[limit])
        conn.close()
        return df
    
    # ==================== 新闻管理 ====================
    
    def insert_news(self, news_data):
        """插入新闻数据"""
        if not news_data:
            return
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        if isinstance(news_data, list):
            for news in news_data:
                self._insert_single_news(cursor, news)
        else:
            self._insert_single_news(cursor, news_data)
        
        conn.commit()
        conn.close()
    
    def _insert_single_news(self, cursor, news):
        """插入单条新闻"""
        cursor.execute('SELECT id FROM news WHERE title = ?', (news.get('title'),))
        if cursor.fetchone():
            return
        
        cursor.execute('''
        INSERT INTO news (title, source, url, category, publish_time)
        VALUES (?, ?, ?, ?, ?)
        ''', (
            news.get('title', ''),
            news.get('source', ''),
            news.get('url', ''),
            news.get('category', ''),
            news.get('publish_time', '')
        ))
    
    def get_news(self, limit=15, offset=0, category=None, days=7):
        """获取新闻列表"""
        conn = self._get_connection()
        query = 'SELECT * FROM news WHERE 1=1'
        params = []
        
        if category:
            query += ' AND category = ?'
            params.append(category)
        
        if days > 0:
            cutoff_date = (datetime.now() - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
            query += ' AND publish_time >= ?'
            params.append(cutoff_date)
        
        query += ' ORDER BY publish_time DESC, id DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])
        
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        return df
    
    def get_news_by_category(self, category, limit=10):
        """按分类获取新闻"""
        return self.get_news(limit=limit, category=category)
    
    def get_latest_news(self, limit=15):
        """获取最新新闻"""
        return self.get_news(limit=limit, days=30)
    
    def clear_all_news(self):
        """清空所有新闻"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM news')
        
        conn.commit()
        conn.close()
    
    def clear_old_news(self, days=30):
        """清理旧新闻"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cutoff_date = (datetime.now() - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
        cursor.execute('DELETE FROM news WHERE publish_time < ?', (cutoff_date,))
        
        conn.commit()
        conn.close()
    
    # ==================== 知识库管理 ====================
    
    def insert_knowledge(self, category, title, content, keywords=None):
        """插入知识条目"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO model_knowledge (category, title, content, keywords)
        VALUES (?, ?, ?, ?)
        ''', (category, title, content, keywords))
        conn.commit()
        conn.close()
    
    def insert_knowledge_batch(self, knowledge_list):
        """批量插入知识条目"""
        if not knowledge_list:
            return
        conn = self._get_connection()
        cursor = conn.cursor()
        for item in knowledge_list:
            cursor.execute('''
            INSERT INTO model_knowledge (category, title, content, keywords)
            VALUES (?, ?, ?, ?)
            ''', (item['category'], item['title'], item['content'], item.get('keywords', '')))
        conn.commit()
        conn.close()
    
    def get_knowledge_by_category(self, category):
        """按分类获取知识"""
        conn = self._get_connection()
        df = pd.read_sql_query('''
        SELECT * FROM model_knowledge WHERE category = ? ORDER BY id
        ''', conn, params=[category])
        conn.close()
        return df
    
    def get_all_knowledge(self):
        """获取所有知识"""
        conn = self._get_connection()
        df = pd.read_sql_query('SELECT * FROM model_knowledge ORDER BY category, id', conn)
        conn.close()
        return df
    
    def get_knowledge_categories(self):
        """获取所有分类"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT category FROM model_knowledge ORDER BY category')
        categories = [row[0] for row in cursor.fetchall()]
        conn.close()
        return categories
    
    def search_knowledge(self, keyword):
        """搜索知识"""
        conn = self._get_connection()
        keyword_pattern = f'%{keyword}%'
        df = pd.read_sql_query('''
        SELECT * FROM model_knowledge 
        WHERE title LIKE ? OR content LIKE ? OR keywords LIKE ?
        ORDER BY category, id
        ''', conn, params=[keyword_pattern, keyword_pattern, keyword_pattern])
        conn.close()
        return df
    
    def get_knowledge_count(self):
        """获取知识条目数量"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM model_knowledge')
        count = cursor.fetchone()[0]
        conn.close()
        return count

db = PVSystemDatabase()

# ==================== 便捷函数 ====================

# 用户相关
def create_user(username, password, email=None, role='user'):
    return db.create_user(username, password, email, role)

def authenticate_user(username, password):
    return db.authenticate_user(username, password)

def get_user_by_id(user_id):
    return db.get_user_by_id(user_id)

def get_all_users():
    return db.get_all_users()

def update_user_password(user_id, new_password):
    return db.update_user_password(user_id, new_password)

def verify_and_update_password(username, old_password, new_password):
    """验证旧密码并更新新密码"""
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT id, password_hash FROM users WHERE username = ? AND is_active = 1', (username,))
    result = cursor.fetchone()
    if not result:
        conn.close()
        return False
    user_id, password_hash = result
    if not db._verify_password(old_password, password_hash):
        conn.close()
        return False
    password_hash_new = db._hash_password(new_password)
    cursor.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash_new, user_id))
    conn.commit()
    conn.close()
    return True

def get_user_by_username(username):
    """根据用户名获取用户"""
    conn = sqlite3.connect(db.db_path)
    df = pd.read_sql_query('SELECT * FROM users WHERE username = ?', conn, params=(username,))
    conn.close()
    if df.empty:
        return None
    return df.iloc[0].to_dict()

# 预测历史相关
def save_prediction(user_id, pv_file, prediction_date, start_date, end_date, model_type, result_summary, result_data):
    return db.save_prediction(user_id, pv_file, prediction_date, start_date, end_date, model_type, result_summary, result_data)

def get_prediction_history(user_id=None, limit=50):
    return db.get_prediction_history(user_id, limit)

def delete_prediction(prediction_id):
    return db.delete_prediction(prediction_id)

# 训练历史相关
def save_training_record(user_id, model_name, pv_file, training_date, metrics, parameters, status='completed'):
    return db.save_training_record(user_id, model_name, pv_file, training_date, metrics, parameters, status)

def get_training_history(user_id=None, limit=50):
    return db.get_training_history(user_id, limit)

def delete_training_record(training_id):
    return db.delete_training_record(training_id)

# 公告相关
def create_announcement(title, content, priority='normal', is_pinned=0, created_by=None, expire_date=None):
    return db.create_announcement(title, content, priority, is_pinned, created_by, expire_date)

def get_active_announcements():
    return db.get_active_announcements()

def delete_announcement(announcement_id):
    return db.delete_announcement(announcement_id)

# 查询历史相关
def save_query_history(user_id, pv_file, query_conditions, result_count):
    return db.save_query_history(user_id, pv_file, query_conditions, result_count)

def get_query_history(user_id=None, limit=50):
    return db.get_query_history(user_id, limit)

# 新闻相关
def save_news_to_db(news_data):
    return db.insert_news(news_data)

def get_news_from_db(limit=15, category=None, days=7):
    return db.get_news(limit=limit, category=category, days=days)

def get_latest_news_from_db():
    return db.get_latest_news()

def get_news_by_category_from_db(category, limit=10):
    return db.get_news_by_category(category, limit)

def clear_old_news_from_db(days=30):
    return db.clear_old_news(days)

def clear_all_news_from_db():
    return db.clear_all_news()

def get_categories():
    return db.get_knowledge_categories()

def get_all_knowledge():
    return db.get_all_knowledge()

def search_knowledge(keyword):
    return db.search_knowledge(keyword)

def get_knowledge_by_category(category):
    return db.get_knowledge_by_category(category)