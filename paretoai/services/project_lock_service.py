"""
项目锁定服务 - 防止并发操作导致数据错乱

核心功能：
1. 在对项目执行写操作前获取锁
2. 如果项目已被锁定，返回失败
3. 操作完成后释放锁
4. 支持锁超时自动释放（防止死锁）

使用方式：
    lock_service = get_project_lock_service()
    
    # 方式1：上下文管理器（推荐）
    async with lock_service.acquire_lock(project_id, operation="generate_segment"):
        # 执行操作
        pass
    
    # 方式2：手动获取/释放
    if lock_service.try_lock(project_id, operation="cascade_redo"):
        try:
            # 执行操作
            pass
        finally:
            lock_service.release_lock(project_id)
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LockInfo:
    """锁信息"""
    project_id: str
    operation: str  # 操作类型：generate_segment, cascade_redo, edit_regenerate, etc.
    locked_at: datetime
    expires_at: datetime
    holder_id: str  # 持有者标识（用于调试）


class ProjectLockService:
    """
    项目锁定服务
    
    使用内存锁实现（单实例部署适用）
    生产环境建议改为 Redis 分布式锁
    """
    
    # 默认锁超时时间（秒）
    DEFAULT_LOCK_TIMEOUT = 600  # 10分钟，视频生成可能较慢
    
    # 不同操作的超时时间
    OPERATION_TIMEOUTS = {
        "generate_segment": 600,    # 10分钟
        "generate_storyboard": 120, # 2分钟
        "cascade_redo": 60,         # 1分钟
        "edit_regenerate": 600,     # 10分钟
        "merge_videos": 300,        # 5分钟
    }
    
    def __init__(self):
        self._locks: Dict[str, LockInfo] = {}
        self._lock = asyncio.Lock()  # 保护 _locks 字典的并发访问
    
    def _get_timeout(self, operation: str) -> int:
        """获取操作的超时时间"""
        return self.OPERATION_TIMEOUTS.get(operation, self.DEFAULT_LOCK_TIMEOUT)
    
    def _is_lock_expired(self, lock_info: LockInfo) -> bool:
        """检查锁是否已过期"""
        return datetime.utcnow() > lock_info.expires_at
    
    def _generate_holder_id(self) -> str:
        """生成持有者ID"""
        import uuid
        return f"holder_{uuid.uuid4().hex[:8]}_{int(time.time())}"
    
    async def try_lock(
        self,
        project_id: str,
        operation: str = "unknown",
        timeout: Optional[int] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        尝试获取项目锁
        
        Args:
            project_id: 项目ID
            operation: 操作类型
            timeout: 锁超时时间（秒），None 则使用默认值
        
        Returns:
            (success, error_message)
            - success: 是否成功获取锁
            - error_message: 失败时的错误信息
        """
        async with self._lock:
            # 检查是否已有锁
            existing_lock = self._locks.get(project_id)
            
            if existing_lock:
                # 检查锁是否过期
                if self._is_lock_expired(existing_lock):
                    logger.warning(
                        f"项目 {project_id} 的锁已过期，自动释放 "
                        f"(原操作: {existing_lock.operation}, 锁定于: {existing_lock.locked_at})"
                    )
                    del self._locks[project_id]
                else:
                    # 锁未过期，返回失败
                    error_msg = (
                        f"项目正在处理中，请稍后再试。"
                        f"当前操作: {existing_lock.operation}，"
                        f"开始时间: {existing_lock.locked_at.strftime('%H:%M:%S')}"
                    )
                    logger.warning(
                        f"项目 {project_id} 锁定失败: {error_msg} "
                        f"(请求操作: {operation})"
                    )
                    return False, error_msg
            
            # 创建新锁
            lock_timeout = timeout or self._get_timeout(operation)
            now = datetime.utcnow()
            holder_id = self._generate_holder_id()
            
            self._locks[project_id] = LockInfo(
                project_id=project_id,
                operation=operation,
                locked_at=now,
                expires_at=now + timedelta(seconds=lock_timeout),
                holder_id=holder_id,
            )
            
            logger.info(
                f"项目 {project_id} 已锁定 "
                f"(操作: {operation}, 超时: {lock_timeout}s, holder: {holder_id})"
            )
            return True, None
    
    async def release_lock(self, project_id: str, holder_id: Optional[str] = None) -> bool:
        """
        释放项目锁
        
        Args:
            project_id: 项目ID
            holder_id: 持有者ID（可选，用于验证）
        
        Returns:
            是否成功释放
        """
        async with self._lock:
            existing_lock = self._locks.get(project_id)
            
            if not existing_lock:
                logger.debug(f"项目 {project_id} 没有锁，无需释放")
                return True
            
            # 可选：验证持有者
            if holder_id and existing_lock.holder_id != holder_id:
                logger.warning(
                    f"项目 {project_id} 锁释放失败: holder_id 不匹配 "
                    f"(期望: {existing_lock.holder_id}, 实际: {holder_id})"
                )
                return False
            
            del self._locks[project_id]
            logger.info(f"项目 {project_id} 锁已释放 (操作: {existing_lock.operation})")
            return True
    
    def is_locked(self, project_id: str) -> bool:
        """
        检查项目是否被锁定
        
        Args:
            project_id: 项目ID
        
        Returns:
            是否被锁定（不包括已过期的锁）
        """
        lock_info = self._locks.get(project_id)
        if not lock_info:
            return False
        
        if self._is_lock_expired(lock_info):
            return False
        
        return True
    
    def get_lock_info(self, project_id: str) -> Optional[Dict[str, Any]]:
        """
        获取项目锁信息
        
        Args:
            project_id: 项目ID
        
        Returns:
            锁信息字典，或 None
        """
        lock_info = self._locks.get(project_id)
        if not lock_info:
            return None
        
        if self._is_lock_expired(lock_info):
            return None
        
        return {
            "project_id": lock_info.project_id,
            "operation": lock_info.operation,
            "locked_at": lock_info.locked_at.isoformat(),
            "expires_at": lock_info.expires_at.isoformat(),
            "holder_id": lock_info.holder_id,
        }
    
    @asynccontextmanager
    async def acquire_lock(
        self,
        project_id: str,
        operation: str = "unknown",
        timeout: Optional[int] = None,
    ):
        """
        上下文管理器：获取锁并在完成后自动释放
        
        使用方式：
            async with lock_service.acquire_lock(project_id, "generate_segment"):
                # 执行操作
                pass
        
        Raises:
            ProjectLockError: 如果无法获取锁
        """
        success, error_msg = await self.try_lock(project_id, operation, timeout)
        
        if not success:
            raise ProjectLockError(project_id, error_msg)
        
        try:
            yield
        finally:
            await self.release_lock(project_id)
    
    def get_all_locks(self) -> Dict[str, Dict[str, Any]]:
        """获取所有活跃的锁（用于调试/监控）"""
        result = {}
        for project_id, lock_info in self._locks.items():
            if not self._is_lock_expired(lock_info):
                result[project_id] = {
                    "operation": lock_info.operation,
                    "locked_at": lock_info.locked_at.isoformat(),
                    "expires_at": lock_info.expires_at.isoformat(),
                }
        return result
    
    async def cleanup_expired_locks(self) -> int:
        """清理过期的锁（可定期调用）"""
        async with self._lock:
            expired = []
            for project_id, lock_info in self._locks.items():
                if self._is_lock_expired(lock_info):
                    expired.append(project_id)
            
            for project_id in expired:
                del self._locks[project_id]
                logger.info(f"清理过期锁: {project_id}")
            
            return len(expired)


class ProjectLockError(Exception):
    """项目锁定错误"""
    
    def __init__(self, project_id: str, message: str):
        self.project_id = project_id
        self.message = message
        super().__init__(f"项目 {project_id} 锁定失败: {message}")


# 全局单例
_project_lock_service: Optional[ProjectLockService] = None


def get_project_lock_service() -> ProjectLockService:
    """获取项目锁服务实例"""
    global _project_lock_service
    if _project_lock_service is None:
        _project_lock_service = ProjectLockService()
    return _project_lock_service
