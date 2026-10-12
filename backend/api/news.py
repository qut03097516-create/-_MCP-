from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()

class NewsItem(BaseModel):
    id: int
    title: str
    source: str
    url: str
    category: str
    publish_time: str

@router.get("/latest")
async def get_news(category: Optional[str] = None):
    """获取新闻列表"""
    sample_news = [
        {
            'id': 1,
            'title': '国家能源局发布2024年光伏装机目标',
            'source': '中国能源报',
            'url': 'https://example.com/news/1',
            'category': 'policy',
            'publish_time': '2024-05-20'
        },
        {
            'id': 2,
            'title': '新型高效太阳能电池转换效率突破26%',
            'source': '科技日报',
            'url': 'https://example.com/news/2',
            'category': 'technology',
            'publish_time': '2024-05-18'
        },
        {
            'id': 3,
            'title': '全球光伏市场持续增长，中国占比超60%',
            'source': '经济观察报',
            'url': 'https://example.com/news/3',
            'category': 'market',
            'publish_time': '2024-05-15'
        },
        {
            'id': 4,
            'title': '分布式光伏迎来发展新机遇',
            'source': '行业动态',
            'url': 'https://example.com/news/4',
            'category': 'industry',
            'publish_time': '2024-05-12'
        },
        {
            'id': 5,
            'title': '欧盟宣布新的可再生能源支持计划',
            'source': '国际新闻',
            'url': 'https://example.com/news/5',
            'category': 'international',
            'publish_time': '2024-05-10'
        }
    ]
    
    filtered_news = sample_news
    if category:
        filtered_news = [n for n in sample_news if n['category'] == category]
    
    return {'success': True, 'data': filtered_news}

@router.get("/categories")
async def get_categories():
    """获取新闻分类"""
    return [
        {'id': 'industry', 'name': '行业动态', 'icon': '🏭'},
        {'id': 'technology', 'name': '技术创新', 'icon': '🔬'},
        {'id': 'policy', 'name': '政策法规', 'icon': '📝'},
        {'id': 'market', 'name': '市场分析', 'icon': '📊'},
        {'id': 'international', 'name': '国际新闻', 'icon': '🌍'}
    ]