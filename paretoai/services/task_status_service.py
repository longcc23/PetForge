"""
任务状态管理服务 - 数据结构 V2

核心原则：数据库是唯一事实来源
- 所有状态变更首先写入数据库
- 飞书同步降级为通知操作，失败不阻断业务流程
"""
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
from sqlmodel import Session, select

from paretoai.models import BatchTask
from paretoai.db import engine

logger = logging.getLogger(__name__)


class TaskStatusService:
    """任务状态管理服务 - 确保数据库是唯一事实来源"""

    @classmethod
    def get_task(cls, project_id: str) -> Optional[BatchTask]:
        """
        获取任务完整数据

        Args:
            project_id: 项目ID

        Returns:
            BatchTask 对象，不存在则返回 None
        """
        try:
            with Session(engine) as session:
                task = session.exec(
                    select(BatchTask).where(BatchTask.project_id == project_id)
                ).first()
                if task:
                    # Detach from session to avoid lazy loading issues
                    session.expunge(task)
                return task
        except Exception as e:
            logger.error(f"获取任务失败: {project_id}, error: {e}")
            return None

    @classmethod
    def get_storyboard(cls, project_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        获取分镜数据（从数据库读取）

        Args:
            project_id: 项目ID

        Returns:
            分镜列表，不存在则返回 None
        """
        task = cls.get_task(project_id)
        if not task or not task.storyboard_json:
            return None

        try:
            storyboard_data = json.loads(task.storyboard_json)
            # 支持两种格式：直接列表 或 {"storyboards": [...]}
            if isinstance(storyboard_data, list):
                return storyboard_data
            elif isinstance(storyboard_data, dict):
                return storyboard_data.get("storyboards", [])
            return None
        except json.JSONDecodeError as e:
            logger.error(f"解析 storyboard_json 失败: {project_id}, error: {e}")
            return None

    @classmethod
    def get_storyboard_with_fallback(
        cls,
        project_id: str,
        storage_path: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        获取分镜数据，带本地文件回退

        优先从数据库读取，如果不存在则尝试从本地 storyboard.json 读取

        Args:
            project_id: 项目ID
            storage_path: 项目存储路径（可选，用于回退）

        Returns:
            分镜列表
        """
        # 1. 优先从数据库读取
        storyboards = cls.get_storyboard(project_id)
        if storyboards:
            return storyboards

        # 2. 回退到本地文件
        if storage_path:
            local_file = Path(storage_path) / "storyboard.json"
            if local_file.exists():
                try:
                    with open(local_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return data
                        elif isinstance(data, dict):
                            return data.get("storyboards", [])
                except Exception as e:
                    logger.error(f"读取本地 storyboard.json 失败: {e}")

        return None

    @classmethod
    def get_project_id_by_feishu_record(
        cls,
        feishu_record_id: str
    ) -> Optional[str]:
        """
        根据飞书记录ID查找对应的项目ID
        
        【根因修复】用于在生成分镜前检查是否已有项目与此飞书记录关联，
        避免重复创建 project_id（孤儿项目问题）
        
        Args:
            feishu_record_id: 飞书记录ID
            
        Returns:
            项目ID，如果不存在则返回 None
        """
        try:
            with Session(engine) as session:
                task = session.exec(
                    select(BatchTask).where(BatchTask.feishu_record_id == feishu_record_id)
                ).first()
                
                if task:
                    logger.info(f"✅ 找到已关联项目: feishu_record_id={feishu_record_id} -> project_id={task.project_id}")
                    return task.project_id
                else:
                    logger.debug(f"未找到关联项目: feishu_record_id={feishu_record_id}")
                    return None
                    
        except Exception as e:
            logger.error(f"查询飞书关联失败: feishu_record_id={feishu_record_id}, error: {e}")
            return None

    @classmethod
    def ensure_feishu_association(
        cls,
        project_id: str,
        feishu_table_id: str,
        feishu_record_id: str,
        publish_date: Optional[str] = None
    ) -> bool:
        """
        确保数据库中的任务记录关联了飞书表格和记录ID

        如果记录已存在但缺少飞书关联，则更新；如果不存在则跳过（让 get_or_create_storage_path 创建）

        Args:
            project_id: 项目ID
            feishu_table_id: 飞书表格ID
            feishu_record_id: 飞书记录ID
            publish_date: 发布日期（YYYYMMDD格式），可选

        Returns:
            是否更新成功
        """
        try:
            with Session(engine) as session:
                task = session.exec(
                    select(BatchTask).where(BatchTask.project_id == project_id)
                ).first()

                if not task:
                    logger.warning(f"任务不存在，跳过飞书关联: {project_id}")
                    return False

                # 更新飞书关联信息（即使已有也更新，确保最新）
                task.feishu_table_id = feishu_table_id
                task.feishu_record_id = feishu_record_id
                
                # 更新发布日期（如果提供）
                if publish_date:
                    task.publish_date = publish_date
                    
                task.updated_at = datetime.utcnow()

                session.add(task)
                session.commit()

                logger.info(f"✅ 已关联飞书: project_id={project_id}, record_id={feishu_record_id}, publish_date={publish_date}")
                return True

        except Exception as e:
            logger.error(f"关联飞书失败: {project_id}, error: {e}")
            return False

    @classmethod
    def update_task_status(
        cls,
        project_id: str,
        status: str,
        storyboard_json: Optional[str] = None,
        segment_urls: Optional[str] = None,
        error_message: Optional[str] = None,
        progress: Optional[str] = None,
        total_segments: Optional[int] = None,
        current_segment: Optional[int] = None,
        final_video_url: Optional[str] = None,
    ) -> bool:
        """
        更新任务状态（主要操作：写数据库）

        Args:
            project_id: 项目ID
            status: 新状态
            storyboard_json: 分镜数据 JSON 字符串
            segment_urls: 分段视频 URL JSON 字符串
            error_message: 错误信息
            progress: 进度文本
            total_segments: 总段数
            current_segment: 当前段
            final_video_url: 最终视频 URL

        Returns:
            是否更新成功
        """
        try:
            with Session(engine) as session:
                task = session.exec(
                    select(BatchTask).where(BatchTask.project_id == project_id)
                ).first()

                if not task:
                    logger.error(f"任务不存在: {project_id}")
                    return False

                task.status = status
                task.updated_at = datetime.utcnow()

                if storyboard_json is not None:
                    task.storyboard_json = storyboard_json
                if segment_urls is not None:
                    task.segment_urls = segment_urls
                if error_message is not None:
                    task.error_message = error_message
                if progress is not None:
                    task.progress = progress
                if total_segments is not None:
                    task.total_segments = total_segments
                if current_segment is not None:
                    task.current_segment = current_segment
                if final_video_url is not None:
                    task.final_video_url = final_video_url

                session.add(task)
                session.commit()
                logger.info(f"✅ 任务状态已更新: {project_id} -> {status}")
                return True

        except Exception as e:
            logger.error(f"更新任务状态失败: {project_id}, error: {e}")
            return False

    @classmethod
    def save_storyboard(
        cls,
        project_id: str,
        storyboards: List[Dict[str, Any]],
        storage_path: Optional[str] = None,
        status: str = "storyboard_ready",
    ) -> bool:
        """
        保存分镜数据（写数据库 + 可选写本地文件）

        Args:
            project_id: 项目ID
            storyboards: 分镜数据列表
            storage_path: 项目存储路径（可选，用于同步到本地文件）
            status: 新状态

        Returns:
            是否保存成功
        """
        try:
            storyboard_json = json.dumps(storyboards, ensure_ascii=False)

            # 1. 写入数据库
            success = cls.update_task_status(
                project_id=project_id,
                status=status,
                storyboard_json=storyboard_json,
                total_segments=len(storyboards),
            )

            if not success:
                return False

            # 2. 同步到本地文件（可选）
            if storage_path:
                local_file = Path(storage_path) / "storyboard.json"
                try:
                    # 构建完整的 storyboard 数据结构
                    full_data = {
                        "storyboards": storyboards,
                        "timestamp": datetime.utcnow().isoformat(),
                        "project_id": project_id,
                    }
                    with open(local_file, "w", encoding="utf-8") as f:
                        json.dump(full_data, f, ensure_ascii=False, indent=2)
                    logger.debug(f"✅ 分镜已同步到本地: {local_file}")
                except Exception as e:
                    logger.warning(f"⚠️ 同步本地文件失败（不影响主流程）: {e}")

            return True

        except Exception as e:
            logger.error(f"保存分镜失败: {project_id}, error: {e}")
            return False

    @classmethod
    def update_segment_result(
        cls,
        project_id: str,
        segment_index: int,
        video_url: Optional[str] = None,
        first_frame_url: Optional[str] = None,
        last_frame_url: Optional[str] = None,
        status: str = "completed",
    ) -> bool:
        """
        更新单个分段的生成结果

        Args:
            project_id: 项目ID
            segment_index: 段索引
            video_url: 视频 URL
            first_frame_url: 首帧 URL
            last_frame_url: 尾帧 URL
            status: 段状态

        Returns:
            是否更新成功
        """
        try:
            with Session(engine) as session:
                task = session.exec(
                    select(BatchTask).where(BatchTask.project_id == project_id)
                ).first()

                if not task:
                    logger.error(f"任务不存在: {project_id}")
                    return False

                # 解析现有的 segment_urls
                if task.segment_urls:
                    segment_data = json.loads(task.segment_urls)
                else:
                    segment_data = {}

                # 更新指定段的数据
                segment_key = f"segment_{segment_index}"
                segment_data[segment_key] = {
                    "video_url": video_url,
                    "first_frame_url": first_frame_url,
                    "last_frame_url": last_frame_url,
                    "status": status,
                    "updated_at": datetime.utcnow().isoformat(),
                }

                task.segment_urls = json.dumps(segment_data, ensure_ascii=False)
                task.current_segment = segment_index
                task.updated_at = datetime.utcnow()

                # 【修复问题#2】同步更新 storyboard_json 中对应段的状态
                # 前端的 getNextSegmentIndex 依赖 storyboard_json 中的 status 字段
                if task.storyboard_json:
                    try:
                        storyboard_data = json.loads(task.storyboard_json)
                        storyboards = storyboard_data.get("storyboards", [])
                        
                        if segment_index < len(storyboards):
                            # 更新段状态和URL
                            storyboards[segment_index]["status"] = status
                            if video_url:
                                storyboards[segment_index]["videoUrl"] = video_url
                            if last_frame_url:
                                storyboards[segment_index]["lastFrameUrl"] = last_frame_url
                                storyboards[segment_index]["last_frame_url"] = last_frame_url  # 兼容两种命名
                            
                            storyboard_data["storyboards"] = storyboards
                            task.storyboard_json = json.dumps(storyboard_data, ensure_ascii=False)
                            logger.info(f"✅ 已同步更新 storyboard_json 中段{segment_index}的状态为 {status}")
                    except Exception as e:
                        logger.warning(f"更新 storyboard_json 失败（不影响主流程）: {e}")

                # 检查是否所有段都完成
                if task.total_segments:
                    completed_count = sum(
                        1 for i in range(task.total_segments)
                        if segment_data.get(f"segment_{i}", {}).get("status") == "completed"
                    )
                    if completed_count == task.total_segments:
                        task.status = "all_segments_ready"
                        task.progress = f"{completed_count}/{task.total_segments}段已完成"
                    else:
                        # 【修复】段生成完成后，状态应该是 storyboard_ready（等待用户推进）
                        # 而不是 generating_segment_{N+1}（表示正在生成）
                        task.status = "storyboard_ready"
                        task.progress = f"{completed_count}/{task.total_segments}段已完成"

                session.add(task)
                session.commit()
                logger.info(f"✅ 段{segment_index}结果已更新: {project_id}")
                return True

        except Exception as e:
            logger.error(f"更新段结果失败: {project_id}, segment_{segment_index}, error: {e}")
            return False

    @classmethod
    async def sync_to_feishu(
        cls,
        feishu_service,
        app_token: str,
        table_id: str,
        record_id: str,
        fields: dict,
    ):
        """
        同步状态到飞书（次要操作：通知，失败不阻断）

        Args:
            feishu_service: 飞书服务实例
            app_token: 应用 token
            table_id: 表格 ID
            record_id: 记录 ID
            fields: 要更新的字段
        """
        try:
            await feishu_service.update_record(app_token, table_id, record_id, fields)
            logger.debug(f"✅ 飞书同步成功: {record_id}")
        except Exception as e:
            logger.warning(f"⚠️ 飞书同步失败（不影响主流程）: {e}")


# 全局实例获取函数
_task_status_service = TaskStatusService()


def get_task_status_service() -> TaskStatusService:
    """获取任务状态服务实例"""
    return _task_status_service
