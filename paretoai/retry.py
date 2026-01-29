"""
重试机制模块
提供异步和同步的重试装饰器
"""
import asyncio
import logging
from functools import wraps
from typing import Optional, Tuple, Type

logger = logging.getLogger(__name__)


class RetryConfigs:
    """重试配置常量"""
    # DeepSeek API 重试配置
    DEEPSEEK_MAX_RETRIES = 3
    DEEPSEEK_RETRY_DELAY = 2.0
    DEEPSEEK_BACKOFF_FACTOR = 2.0
    
    # 飞书 API 重试配置
    FEISHU_MAX_RETRIES = 3
    FEISHU_RETRY_DELAY = 1.0
    FEISHU_BACKOFF_FACTOR = 2.0
    
    # Google VEO API 重试配置
    VEO_MAX_RETRIES = 3
    VEO_RETRY_DELAY = 2.0
    VEO_BACKOFF_FACTOR = 2.0
    
    # 通用网络请求重试配置
    NETWORK = {
        "max_retries": 3,
        "delay": 1.0,
        "backoff": 2.0,
        "exceptions": (Exception,)
    }


def retry_async(
    config_or_max_retries = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    异步重试装饰器
    
    Args:
        config_or_max_retries: 可以是配置字典或最大重试次数
        delay: 初始延迟时间（秒）
        backoff: 退避系数
        exceptions: 需要重试的异常类型
    """
    # 支持字典配置参数
    if isinstance(config_or_max_retries, dict):
        config = config_or_max_retries
        max_retries = config.get("max_retries", 3)
        delay = config.get("delay", 1.0)
        backoff = config.get("backoff", 2.0)
        exceptions = config.get("exceptions", (Exception,))
    else:
        max_retries = config_or_max_retries
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"{func.__name__} 失败 (尝试 {attempt + 1}/{max_retries + 1}): {e}. "
                            f"等待 {current_delay:.1f}秒后重试..."
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"{func.__name__} 在 {max_retries + 1} 次尝试后仍然失败: {e}"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator


def retry_sync(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    同步重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff: 退避系数
        exceptions: 需要重试的异常类型
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            import time
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"{func.__name__} 失败 (尝试 {attempt + 1}/{max_retries + 1}): {e}. "
                            f"等待 {current_delay:.1f}秒后重试..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"{func.__name__} 在 {max_retries + 1} 次尝试后仍然失败: {e}"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator
