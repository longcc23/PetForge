"""
ParetoAI API Routes - 简化版
只包含已实现的路由
"""

from .health import router as health_router
from .batch import router as batch_router

__all__ = [
    "health_router",
    "batch_router",
]
