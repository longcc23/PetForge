"""
归档服务 - 处理视频重新生成时的历史记录管理

功能：
1. 归档旧视频数据（URL、帧图片路径、时间戳）
2. 移动旧本地文件到 archive 目录
3. 查询历史记录
4. 清理过期归档（可选）
"""

import json
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from sqlmodel import Session, select

from paretoai.models import BatchTask
from paretoai.db import engine

logger = logging.getLogger(__name__)


class ArchiveService:
    """视频归档服务"""
    
    def __init__(self):
        self.max_history_per_segment = 10  # 每个段最多保留10条历史记录
    
    def archive_segment(
        self,
        project_id: str,
        segment_index: int,
        old_video_url: Optional[str] = None,
        old_first_frame_url: Optional[str] = None,
        old_last_frame_url: Optional[str] = None,
        old_local_video_path: Optional[str] = None,
        reason: str = "regenerate"
    ) -> bool:
        """
        归档指定段的旧数据
        
        Args:
            project_id: 项目ID
            segment_index: 段索引
            old_video_url: 旧视频URL
            old_first_frame_url: 旧首帧URL
            old_last_frame_url: 旧尾帧URL
            old_local_video_path: 旧本地视频路径
            reason: 归档原因 (regenerate, edit, delete)
        
        Returns:
            是否归档成功
        """
        try:
            with Session(engine) as session:
                task = session.exec(
                    select(BatchTask).where(BatchTask.project_id == project_id)
                ).first()
                
                if not task:
                    logger.error(f"归档失败：任务不存在 project_id={project_id}")
                    return False
                
                # 解析现有历史记录
                segment_history = {}
                if task.segment_history:
                    try:
                        segment_history = json.loads(task.segment_history)
                    except:
                        segment_history = {}
                
                # 创建历史记录条目
                segment_key = f"segment_{segment_index}"
                if segment_key not in segment_history:
                    segment_history[segment_key] = []
                
                history_entry = {
                    "video_url": old_video_url,
                    "first_frame_url": old_first_frame_url,
                    "last_frame_url": old_last_frame_url,
                    "local_video_path": old_local_video_path,
                    "archived_at": datetime.utcnow().isoformat(),
                    "reason": reason
                }
                
                # 只有当有实际数据时才添加
                if old_video_url or old_local_video_path:
                    segment_history[segment_key].insert(0, history_entry)
                    
                    # 限制历史记录数量
                    if len(segment_history[segment_key]) > self.max_history_per_segment:
                        segment_history[segment_key] = segment_history[segment_key][:self.max_history_per_segment]
                    
                    # 保存到数据库
                    task.segment_history = json.dumps(segment_history, ensure_ascii=False)
                    task.updated_at = datetime.utcnow()
                    session.add(task)
                    session.commit()
                    
                    logger.info(f"✅ 已归档 {project_id} 段{segment_index} 的历史记录")
                else:
                    logger.info(f"ℹ️ 段{segment_index} 无旧数据需要归档")
                
                return True
                
        except Exception as e:
            logger.error(f"归档失败: {e}", exc_info=True)
            return False
    
    def move_local_files_to_archive(
        self,
        project_id: str,
        segment_index: int,
        project_storage_path: str
    ) -> Dict[str, str]:
        """
        将本地视频和帧文件移动到 archive 目录
        
        Args:
            project_id: 项目ID
            segment_index: 段索引
            project_storage_path: 项目存储路径
        
        Returns:
            移动后的文件路径映射 {原路径: 新路径}
        """
        moved_files = {}
        
        try:
            project_path = Path(project_storage_path)
            archive_dir = project_path / "archive" / f"segment_{segment_index}"
            archive_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成唯一的归档子目录（基于时间戳）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_subdir = archive_dir / timestamp
            archive_subdir.mkdir(parents=True, exist_ok=True)
            
            # 移动视频文件
            segments_dir = project_path / "segments"
            if segments_dir.exists():
                for video_file in segments_dir.glob(f"segment_{segment_index}*"):
                    if video_file.is_file():
                        dest = archive_subdir / video_file.name
                        shutil.move(str(video_file), str(dest))
                        moved_files[str(video_file)] = str(dest)
                        logger.info(f"✅ 已移动视频文件: {video_file.name} -> archive/{timestamp}/")
            
            # 移动帧文件
            frames_dir = project_path / "frames"
            if frames_dir.exists():
                for frame_file in frames_dir.glob(f"segment_{segment_index}*"):
                    if frame_file.is_file():
                        dest = archive_subdir / frame_file.name
                        shutil.move(str(frame_file), str(dest))
                        moved_files[str(frame_file)] = str(dest)
                        logger.info(f"✅ 已移动帧文件: {frame_file.name} -> archive/{timestamp}/")
            
            if moved_files:
                logger.info(f"✅ 已将 {len(moved_files)} 个文件归档到 archive/segment_{segment_index}/{timestamp}/")
            else:
                logger.info(f"ℹ️ 段{segment_index} 无本地文件需要归档")
                
        except Exception as e:
            logger.error(f"移动文件到归档目录失败: {e}", exc_info=True)
        
        return moved_files
    
    def get_segment_history(
        self,
        project_id: str,
        segment_index: Optional[int] = None
    ) -> Dict[str, List[Dict]]:
        """
        获取段的历史记录
        
        Args:
            project_id: 项目ID
            segment_index: 段索引（可选，不指定则返回所有段的历史）
        
        Returns:
            历史记录字典 {segment_0: [...], segment_1: [...]}
        """
        try:
            with Session(engine) as session:
                task = session.exec(
                    select(BatchTask).where(BatchTask.project_id == project_id)
                ).first()
                
                if not task or not task.segment_history:
                    return {}
                
                history = json.loads(task.segment_history)
                
                if segment_index is not None:
                    segment_key = f"segment_{segment_index}"
                    return {segment_key: history.get(segment_key, [])}
                
                return history
                
        except Exception as e:
            logger.error(f"获取历史记录失败: {e}")
            return {}
    
    def archive_and_prepare_for_regenerate(
        self,
        project_id: str,
        segment_index: int,
        project_storage_path: str,
        current_segment_data: Dict[str, Any]
    ) -> bool:
        """
        重新生成前的完整归档流程
        
        Args:
            project_id: 项目ID
            segment_index: 段索引
            project_storage_path: 项目存储路径
            current_segment_data: 当前段数据（包含 video_url, first_frame_url, last_frame_url 等）
        
        Returns:
            是否成功
        """
        try:
            # 1. 归档数据库中的旧数据
            self.archive_segment(
                project_id=project_id,
                segment_index=segment_index,
                old_video_url=current_segment_data.get("video_url") or current_segment_data.get("videoUrl"),
                old_first_frame_url=current_segment_data.get("first_frame_url") or current_segment_data.get("firstFrameUrl"),
                old_last_frame_url=current_segment_data.get("last_frame_url") or current_segment_data.get("lastFrameUrl"),
                old_local_video_path=current_segment_data.get("local_video_path"),
                reason="regenerate"
            )
            
            # 2. 移动本地文件到归档目录
            self.move_local_files_to_archive(
                project_id=project_id,
                segment_index=segment_index,
                project_storage_path=project_storage_path
            )
            
            logger.info(f"✅ 段{segment_index} 归档完成，准备重新生成")
            return True
            
        except Exception as e:
            logger.error(f"归档准备失败: {e}", exc_info=True)
            return False


# 单例
_archive_service: Optional[ArchiveService] = None


def get_archive_service() -> ArchiveService:
    """获取归档服务单例"""
    global _archive_service
    if _archive_service is None:
        _archive_service = ArchiveService()
    return _archive_service
