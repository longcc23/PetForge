"""
健康检查和性能监控路由
"""
import re
from collections import Counter
from fastapi import APIRouter
from datetime import datetime
from sqlmodel import select, func

from ..db import session_scope
from ..models import Note, Creator, TwinAnalysis
from ..rate_limiter import get_rate_limiter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    """健康检查端点"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@router.get("/radar/rate-limit")
def get_rate_limit_status():
    """获取速率限制器状态"""
    limiter = get_rate_limiter()
    return limiter.get_status()


@router.get("/dashboard/stats")
def get_dashboard_stats(top_tags_limit: int = 30):
    """
    获取首页 Dashboard 所需的汇总统计数据
    优化：单次 API 调用返回所有首页需要的数据，避免多次请求
    """
    with session_scope() as session:
        # 使用 COUNT 查询，避免全表扫描
        creators_count = session.exec(select(func.count()).select_from(Creator)).one()
        notes_count = session.exec(select(func.count()).select_from(Note)).one()
        analyses_count = session.exec(select(func.count()).select_from(TwinAnalysis)).one()

        # 获取热门标签（从笔记内容中提取并聚合）
        # 限制只处理最近的笔记以提高性能
        recent_notes = session.exec(
            select(Note.content)
            .where(Note.content != None)
            .where(Note.content != "")
            .order_by(Note.likes.desc())
            .limit(500)  # 只取点赞最高的500条计算标签
        ).all()

        tag_counts = Counter()
        tag_pattern = re.compile(r'#[^\s#\[]+(?:\[话题\])?')
        for content in recent_notes:
            if content:
                matches = tag_pattern.findall(str(content))
                for raw in matches:
                    tag = raw.replace('[话题]', '').strip()
                    if tag:
                        tag_counts[tag] += 1

        top_tags = [
            {"tag": tag, "count": count}
            for tag, count in tag_counts.most_common(top_tags_limit)
        ]

        return {
            "stats": {
                "creators": creators_count,
                "notes": notes_count,
                "analyses": analyses_count,
            },
            "top_tags": top_tags,
            "timestamp": datetime.now().isoformat()
        }
