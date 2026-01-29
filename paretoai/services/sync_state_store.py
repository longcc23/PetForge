"""
同步状态缓存管理

维护本地文件与飞书云空间的同步状态，避免重复查询远端 API。

数据结构:
{
    "20260125-abc123": {
        "folder_token": "LO1jf...",
        "segments_folder_token": "AB2cd...",
        "files": {
            "opening_image.jpg": {"mtime": 1706174400, "size": 12345, "token": "xxx"},
            "segments/segment_0.mp4": {"mtime": 1706174500, "size": 5000000, "token": "yyy"}
        },
        "last_sync": "2026-01-25T10:00:00"
    }
}
"""

import json
import os
import logging
from datetime import datetime
from typing import Dict, Optional, Any
from pathlib import Path
import asyncio
from threading import Lock

logger = logging.getLogger(__name__)


class SyncStateStore:
    """同步状态缓存管理器"""

    def __init__(self, state_file_path: Optional[str] = None):
        """
        初始化同步状态存储

        Args:
            state_file_path: 状态文件路径，默认为 data/sync_state.json
        """
        if state_file_path is None:
            base_path = os.getenv("LOCAL_STORAGE_PATH", "./data/uploads")
            state_file_path = os.path.join(os.path.dirname(base_path), "sync_state.json")

        self.state_file_path = state_file_path
        self._state: Dict[str, Any] = {}
        self._lock = Lock()
        self._load_state()

    def _load_state(self) -> None:
        """从文件加载状态"""
        try:
            if os.path.exists(self.state_file_path):
                with open(self.state_file_path, "r", encoding="utf-8") as f:
                    self._state = json.load(f)
                logger.info(f"[SyncState] 加载同步状态: {len(self._state)} 个项目")
            else:
                self._state = {}
                logger.info("[SyncState] 状态文件不存在，初始化为空")
        except Exception as e:
            logger.error(f"[SyncState] 加载状态文件失败: {e}")
            self._state = {}

    def _save_state(self) -> None:
        """保存状态到文件"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.state_file_path), exist_ok=True)

            with open(self.state_file_path, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
            logger.debug(f"[SyncState] 保存同步状态: {len(self._state)} 个项目")
        except Exception as e:
            logger.error(f"[SyncState] 保存状态文件失败: {e}")

    def get_project_state(self, folder_name: str) -> Optional[Dict]:
        """
        获取项目的同步状态

        Args:
            folder_name: 项目文件夹名称（如 "20260125-abc123"）

        Returns:
            项目状态字典，如果不存在则返回 None
        """
        with self._lock:
            return self._state.get(folder_name)

    def get_folder_token(self, folder_name: str) -> Optional[str]:
        """获取已缓存的项目文件夹 token"""
        state = self.get_project_state(folder_name)
        return state.get("folder_token") if state else None

    def get_segments_folder_token(self, folder_name: str) -> Optional[str]:
        """获取已缓存的 segments 子文件夹 token"""
        state = self.get_project_state(folder_name)
        return state.get("segments_folder_token") if state else None

    def get_file_state(self, folder_name: str, file_path: str) -> Optional[Dict]:
        """
        获取文件的同步状态

        Args:
            folder_name: 项目文件夹名称
            file_path: 文件相对路径（如 "opening_image.jpg" 或 "segments/segment_0.mp4"）

        Returns:
            文件状态字典 {"mtime": ..., "size": ..., "token": ...}
        """
        state = self.get_project_state(folder_name)
        if state and "files" in state:
            return state["files"].get(file_path)
        return None

    def is_file_changed(
        self,
        folder_name: str,
        file_path: str,
        local_file_path: str
    ) -> bool:
        """
        检查文件是否发生变化（需要重新上传）

        比较本地文件的 mtime 和 size 与缓存状态

        Args:
            folder_name: 项目文件夹名称
            file_path: 文件相对路径
            local_file_path: 本地文件绝对路径

        Returns:
            True 表示文件有变化或从未同步，False 表示无变化
        """
        if not os.path.exists(local_file_path):
            return False

        cached = self.get_file_state(folder_name, file_path)
        if not cached:
            # 从未同步过，需要上传
            return True

        # 获取本地文件信息
        stat = os.stat(local_file_path)
        local_mtime = int(stat.st_mtime)
        local_size = stat.st_size

        cached_mtime = cached.get("mtime", 0)
        cached_size = cached.get("size", 0)

        # 比较 mtime 和 size
        if local_mtime != cached_mtime or local_size != cached_size:
            logger.info(
                f"[SyncState] 文件已变化: {file_path} "
                f"(mtime: {cached_mtime} -> {local_mtime}, size: {cached_size} -> {local_size})"
            )
            return True

        logger.debug(f"[SyncState] 文件未变化: {file_path}")
        return False

    def update_project_state(
        self,
        folder_name: str,
        folder_token: str,
        segments_folder_token: Optional[str] = None
    ) -> None:
        """
        更新项目的文件夹 token

        Args:
            folder_name: 项目文件夹名称
            folder_token: 项目文件夹 token
            segments_folder_token: segments 子文件夹 token
        """
        with self._lock:
            if folder_name not in self._state:
                self._state[folder_name] = {"files": {}}

            self._state[folder_name]["folder_token"] = folder_token
            if segments_folder_token:
                self._state[folder_name]["segments_folder_token"] = segments_folder_token
            self._state[folder_name]["last_sync"] = datetime.now().isoformat()

            self._save_state()

    def update_file_state(
        self,
        folder_name: str,
        file_path: str,
        local_file_path: str,
        file_token: Optional[str] = None
    ) -> None:
        """
        更新文件的同步状态

        Args:
            folder_name: 项目文件夹名称
            file_path: 文件相对路径
            local_file_path: 本地文件绝对路径
            file_token: 飞书文件 token（可选）
        """
        if not os.path.exists(local_file_path):
            return

        stat = os.stat(local_file_path)

        with self._lock:
            if folder_name not in self._state:
                self._state[folder_name] = {"files": {}}

            if "files" not in self._state[folder_name]:
                self._state[folder_name]["files"] = {}

            self._state[folder_name]["files"][file_path] = {
                "mtime": int(stat.st_mtime),
                "size": stat.st_size,
                "token": file_token,
                "synced_at": datetime.now().isoformat()
            }

            self._save_state()

    def mark_file_synced(
        self,
        folder_name: str,
        file_path: str,
        local_file_path: str,
        file_token: Optional[str] = None
    ) -> None:
        """标记文件已同步（update_file_state 的别名）"""
        self.update_file_state(folder_name, file_path, local_file_path, file_token)

    def remove_project_state(self, folder_name: str) -> None:
        """删除项目的同步状态"""
        with self._lock:
            if folder_name in self._state:
                del self._state[folder_name]
                self._save_state()
                logger.info(f"[SyncState] 删除项目状态: {folder_name}")

    def clear_all(self) -> None:
        """清空所有同步状态"""
        with self._lock:
            self._state = {}
            self._save_state()
            logger.info("[SyncState] 清空所有同步状态")

    def refresh_project_cache(
        self,
        folder_name: str,
        project_path: str
    ) -> Dict:
        """
        同步前刷新缓存：检测本地文件变化，返回需要强制查询远端的文件列表

        注意：此方法不再更新缓存中的 mtime/size，而是标记哪些文件需要查询远端。
        这样可以确保本地文件变化时，会查询远端状态并正确决定是否上传。

        Args:
            folder_name: 项目文件夹名称（如 "20260125-abc123"）
            project_path: 项目本地路径

        Returns:
            {
                "updated": 数量,
                "removed": 数量,
                "changed_files": ["segments/segment_4_segment.mp4", ...]  # 需要强制查询远端的文件
            }
        """
        if not os.path.exists(project_path):
            return {"updated": 0, "removed": 0, "changed_files": []}

        stats = {"updated": 0, "removed": 0, "changed_files": []}

        with self._lock:
            if folder_name not in self._state:
                return stats

            project_state = self._state[folder_name]
            if "files" not in project_state:
                return stats

            files_to_remove = []
            files_cache = project_state["files"]

            # 遍历缓存中的文件记录
            for file_rel_path, cached_info in files_cache.items():
                # 构建本地文件完整路径
                local_path = os.path.join(project_path, file_rel_path)

                if os.path.exists(local_path):
                    # 文件存在，检查 mtime/size 是否变化
                    stat = os.stat(local_path)
                    new_mtime = int(stat.st_mtime)
                    new_size = stat.st_size

                    if cached_info.get("mtime") != new_mtime or cached_info.get("size") != new_size:
                        # 标记为需要查询远端（不更新缓存，让同步逻辑决定）
                        stats["changed_files"].append(file_rel_path)
                        stats["updated"] += 1
                        logger.info(f"[SyncState] 检测到本地文件变化: {file_rel_path} (mtime: {cached_info.get('mtime')} -> {new_mtime}, size: {cached_info.get('size')} -> {new_size})")
                else:
                    # 文件不存在，标记删除
                    files_to_remove.append(file_rel_path)

            # 删除不存在的文件记录
            for file_rel_path in files_to_remove:
                del files_cache[file_rel_path]
                stats["removed"] += 1
                logger.info(f"[SyncState] 清理缓存: {file_rel_path}（本地文件已删除）")

            if stats["removed"] > 0:
                self._save_state()

            if stats["updated"] > 0 or stats["removed"] > 0:
                logger.info(f"[SyncState] 刷新缓存完成: {folder_name}, 变化 {stats['updated']} 个，清理 {stats['removed']} 个")

        return stats

    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._lock:
            total_projects = len(self._state)
            total_files = sum(
                len(p.get("files", {})) for p in self._state.values()
            )
            return {
                "total_projects": total_projects,
                "total_files": total_files,
                "state_file": self.state_file_path
            }


# 单例实例
_sync_state_store: Optional[SyncStateStore] = None


def get_sync_state_store() -> SyncStateStore:
    """获取同步状态存储的单例实例"""
    global _sync_state_store
    if _sync_state_store is None:
        _sync_state_store = SyncStateStore()
    return _sync_state_store
