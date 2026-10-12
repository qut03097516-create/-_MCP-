from fastapi import APIRouter
import sys
import os
import duckdb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

router = APIRouter()

@router.get("/stats")
async def get_home_stats():
    """获取首页统计数据"""
    db_path = 'data/pv_data.duckdb'
    conn = duckdb.connect(db_path, read_only=True)

    stats = conn.execute("""
        SELECT
            COUNT(DISTINCT filename) AS pv_count,
            COUNT(*) AS total_records,
            MIN(DATATIME) AS min_date,
            MAX(DATATIME) AS max_date
        FROM pv_data
    """).fetchone()

    conn.close()
    return {
        'pv_count': stats[0] if stats else 0,
        'total_records': stats[1] if stats else 0,
        'min_date': str(stats[2])[:10] if stats else '',
        'max_date': str(stats[3])[:10] if stats else '',
    }

@router.get("/features")
async def get_features():
    """获取系统功能列表"""
    return [
        {
            "id": "data_explore",
            "title": "数据集显示",
            "description": "浏览和分析光伏站点的详细数据，支持多种可视化方式",
            "icon": "📊",
            "page": "数据集显示"
        },
        {
            "id": "prediction",
            "title": "功率预测",
            "description": "使用先进的深度学习模型预测光伏发电功率，支持中长期预测",
            "icon": "📈",
            "page": "功率预测"
        },
        {
            "id": "knowledge",
            "title": "知识库",
            "description": "浏览 Obsidian 知识库笔记，支持目录、标签与全文检索",
            "icon": "📚",
            "page": "知识库"
        },
        {
            "id": "query",
            "title": "资料查询",
            "description": "查询系统相关知识，包括字段说明、模型原理、系统功能和数据来源",
            "icon": "🔍",
            "page": "资料查询"
        },
        {
            "id": "application",
            "title": "应用场景",
            "description": "探索光伏发电在不同场景下的应用，包括收益测算和系统优化",
            "icon": "📱",
            "page": "应用场景"
        },
        {
            "id": "profile",
            "title": "个人资料",
            "description": "管理个人账号信息，修改密码，查看账号详情",
            "icon": "👤",
            "page": "个人资料"
        }
    ]
