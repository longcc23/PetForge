"""
速率限制模块
简化实现，用于 API 请求限流
"""
import time
import logging
from collections import defaultdict
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


class RateLimiter:
    """简单的速率限制器"""
    
    def __init__(self, max_requests: int = 100, time_window: int = 60):
        """
        Args:
            max_requests: 时间窗口内最大请求数
            time_window: 时间窗口（秒）
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self._requests: Dict[str, list] = defaultdict(list)
    
    def is_allowed(self, key: str) -> Tuple[bool, int]:
        """
        检查是否允许请求
        
        Args:
            key: 限流键（如 IP 地址、用户 ID 等）
        
        Returns:
            (是否允许, 剩余配额)
        """
        now = time.time()
        
        # 清理过期记录
        self._requests[key] = [
            req_time for req_time in self._requests[key]
            if now - req_time < self.time_window
        ]
        
        # 检查是否超限
        current_count = len(self._requests[key])
        if current_count >= self.max_requests:
            return False, 0
        
        # 记录新请求
        self._requests[key].append(now)
        return True, self.max_requests - current_count - 1
    
    def get_remaining(self, key: str) -> int:
        """获取剩余配额"""
        now = time.time()
        self._requests[key] = [
            req_time for req_time in self._requests[key]
            if now - req_time < self.time_window
        ]
        return max(0, self.max_requests - len(self._requests[key]))


# 全局速率限制器实例
_rate_limiter = RateLimiter(max_requests=100, time_window=60)


def get_rate_limiter() -> RateLimiter:
    """获取全局速率限制器实例"""
    return _rate_limiter
