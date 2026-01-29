"""
项目路径管理服务 - 数据结构 V2

负责管理项目文件的物理存储路径，遵循新的目录结构：
{STORAGE_ROOT}/projects/{YYYY-MM-DD}/{template_id}/{project_id}/

核心原则：
1. 数据库即真理：所有路径必须从数据库查询获取
2. 严禁拼接路径猜测文件位置
3. 文件系统为人服务：目录结构对开发/运维友好
"""
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
from sqlmodel import Session, select

from paretoai.models import BatchTask
from paretoai.db import engine

logger = logging.getLogger(__name__)


class ProjectPathService:
    """项目路径管理服务"""

    # 模板ID安全化映射（特殊字符转义）
    TEMPLATE_SAFE_NAMES: Dict[str, str] = {
        "eating": "eating-template",
        "eating-template": "eating-template",
        "daily-vlog": "daily-vlog",
        "adventure": "adventure",
    }

    @classmethod
    def get_storage_root(cls) -> Path:
        """获取存储根目录"""
        storage_path = os.getenv("LOCAL_STORAGE_PATH", "./data/uploads")
        return Path(storage_path) / "projects"

    @classmethod
    def sanitize_template_id(cls, template_id: Optional[str]) -> str:
        """
        安全化模板ID，用于文件系统路径

        Args:
            template_id: 原始模板ID

        Returns:
            安全化的模板ID（小写、连字符替换空格和特殊字符）
        """
        if not template_id:
            return "unknown-template"

        # 预定义映射
        if template_id in cls.TEMPLATE_SAFE_NAMES:
            return cls.TEMPLATE_SAFE_NAMES[template_id]

        # 自动转换：小写、替换特殊字符为连字符
        safe_name = template_id.lower()
        safe_name = safe_name.replace(" ", "-")
        safe_name = safe_name.replace("_", "-")
        # 移除除字母、数字、连字符外的所有字符
        safe_name = "".join(c for c in safe_name if c.isalnum() or c == "-")
        # 移除多余的连字符
        safe_name = "-".join(filter(None, safe_name.split("-")))

        return safe_name or "unknown-template"

    @classmethod
    def build_storage_path(
        cls,
        project_id: str,
        template_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> str:
        """
        构建项目存储路径（V2 结构）

        Args:
            project_id: 项目ID
            template_id: 模板ID
            created_at: 创建时间（默认为当前时间）

        Returns:
            完整的绝对路径字符串
        """
        storage_root = cls.get_storage_root()

        # 日期部分
        if created_at:
            date_str = created_at.strftime("%Y-%m-%d")
        else:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")

        # 模板部分（安全化）
        template_safe = cls.sanitize_template_id(template_id)

        # 构建完整路径
        full_path = storage_root / date_str / template_safe / project_id

        return str(full_path.absolute())

    @classmethod
    def create_project_directory(
        cls,
        project_id: str,
        template_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> str:
        """
        创建项目目录并返回路径

        Args:
            project_id: 项目ID
            template_id: 模板ID
            created_at: 创建时间

        Returns:
            创建的目录路径
        """
        storage_path = cls.build_storage_path(project_id, template_id, created_at)
        Path(storage_path).mkdir(parents=True, exist_ok=True)

        # 创建子目录
        (Path(storage_path) / "segments").mkdir(exist_ok=True)
        (Path(storage_path) / "frames").mkdir(exist_ok=True)

        logger.info(f"Created project directory: {storage_path}")
        return storage_path

    @classmethod
    def get_project_storage_path(cls, project_id: str) -> Optional[str]:
        """
        从数据库获取项目的存储路径（核心方法）

        Args:
            project_id: 项目ID

        Returns:
            项目存储路径，如果不存在则返回 None
        """
        with Session(engine) as session:
            statement = select(BatchTask.storage_path).where(
                BatchTask.project_id == project_id
            )
            result = session.exec(statement).first()

            if result:
                return result
            else:
                logger.warning(f"Project {project_id} not found in database")
                return None

    @classmethod
    def get_or_create_storage_path(
        cls,
        project_id: str,
        template_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
        feishu_table_id: Optional[str] = None,
        feishu_record_id: Optional[str] = None,
    ) -> str:
        """
        获取项目存储路径，如果不存在则创建

        首先尝试从数据库获取，如果不存在则创建新目录并更新数据库

        Args:
            project_id: 项目ID
            template_id: 模板ID
            created_at: 创建时间
            feishu_table_id: 飞书表格ID（新项目必填）
            feishu_record_id: 飞书记录ID（新项目必填）

        Returns:
            项目存储路径
        """
        # 先尝试从数据库获取
        existing_path = cls.get_project_storage_path(project_id)
        if existing_path:
            return existing_path

        # 不存在则创建目录并写入数据库
        if created_at is None:
            created_at = datetime.utcnow()

        storage_path = cls.create_project_directory(project_id, template_id, created_at)

        # 写入数据库（包含飞书关联信息）
        try:
            with Session(engine) as session:
                task = BatchTask(
                    project_id=project_id,
                    template_id=template_id,
                    storage_path=storage_path,
                    feishu_table_id=feishu_table_id,
                    feishu_record_id=feishu_record_id,
                    status="pending",
                    created_at=created_at,
                    updated_at=created_at,
                )
                session.add(task)
                session.commit()
                logger.info(f"Registered new project {project_id} in database with feishu association: table={feishu_table_id}, record={feishu_record_id}")
        except Exception as e:
            logger.error(f"Failed to register project {project_id} in database: {e}")

        return storage_path

    @classmethod
    def get_project_file_path(
        cls,
        project_id: str,
        filename: str,
    ) -> Optional[str]:
        """
        获取项目内文件的完整路径

        Args:
            project_id: 项目ID
            filename: 文件名（如 "storyboard.json", "opening_image.jpg"）

        Returns:
            文件完整路径，如果项目不存在则返回 None
        """
        storage_path = cls.get_project_storage_path(project_id)
        if storage_path:
            return str(Path(storage_path) / filename)
        return None

    @classmethod
    def get_segment_video_path(
        cls,
        project_id: str,
        segment_index: int,
        segment_type: Optional[str] = None,
    ) -> Optional[str]:
        """
        获取分段视频文件路径

        Args:
            project_id: 项目ID
            segment_index: 段索引
            segment_type: 段类型（可选，用于文件命名）

        Returns:
            视频文件路径，如果项目不存在则返回 None
        """
        storage_path = cls.get_project_storage_path(project_id)
        if not storage_path:
            return None

        # 生成文件名
        type_map = {
            'intro': 'intro',
            'eating': 'eating',
            'outro': 'outro'
        }
        type_suffix = type_map.get(segment_type, 'segment') if segment_type else 'segment'
        filename = f"segment_{segment_index}_{type_suffix}.mp4"

        return str(Path(storage_path) / "segments" / filename)

    @classmethod
    def get_segment_frame_path(
        cls,
        project_id: str,
        segment_index: int,
        frame_type: str,  # "first" or "last"
    ) -> Optional[str]:
        """
        获取分段帧文件路径

        Args:
            project_id: 项目ID
            segment_index: 段索引
            frame_type: 帧类型 ("first" or "last")

        Returns:
            帧文件路径，如果项目不存在则返回 None
        """
        storage_path = cls.get_project_storage_path(project_id)
        if not storage_path:
            return None

        filename = f"segment_{segment_index}_{frame_type}.jpg"
        return str(Path(storage_path) / "frames" / filename)

    @classmethod
    def update_project_storage_path(
        cls,
        project_id: str,
        storage_path: str,
    ) -> bool:
        """
        更新数据库中的项目存储路径

        Args:
            project_id: 项目ID
            storage_path: 新的存储路径

        Returns:
            是否更新成功
        """
        try:
            with Session(engine) as session:
                statement = select(BatchTask).where(
                    BatchTask.project_id == project_id
                )
                task = session.exec(statement).first()

                if task:
                    task.storage_path = storage_path
                    session.add(task)
                    session.commit()
                    logger.info(f"Updated storage_path for project {project_id}: {storage_path}")
                    return True
                else:
                    logger.warning(f"Project {project_id} not found for update")
                    return False
        except Exception as e:
            logger.error(f"Failed to update storage_path for project {project_id}: {e}")
            return False

    @classmethod
    def register_new_project(
        cls,
        project_id: str,
        feishu_table_id: str,
        feishu_record_id: str,
        template_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """
        注册新项目到数据库并创建目录

        Args:
            project_id: 项目ID
            feishu_table_id: 飞书表格ID
            feishu_record_id: 飞书记录ID
            template_id: 模板ID
            user_id: 用户ID

        Returns:
            创建的项目存储路径
        """
        # 创建目录
        created_at = datetime.utcnow()
        storage_path = cls.create_project_directory(project_id, template_id, created_at)

        # 写入数据库
        try:
            with Session(engine) as session:
                task = BatchTask(
                    project_id=project_id,
                    feishu_table_id=feishu_table_id,
                    feishu_record_id=feishu_record_id,
                    template_id=template_id,
                    storage_path=storage_path,
                    user_id=user_id,
                    status="pending",
                    created_at=created_at,
                    updated_at=created_at,
                )
                session.add(task)
                session.commit()
                logger.info(f"Registered new project {project_id} in database")
        except Exception as e:
            logger.error(f"Failed to register project {project_id}: {e}")
            # 目录已创建，但数据库写入失败

        return storage_path


    @classmethod
    def get_project_url_prefix(cls, project_id: str) -> Optional[str]:
        """
        获取项目的 URL 前缀（用于前端访问）

        Args:
            project_id: 项目ID

        Returns:
            如 "/storage/projects/2026-01-26/eating-template/abc123"
        """
        storage_path = cls.get_project_storage_path(project_id)
        if not storage_path:
            return None

        uploads_root = Path(os.getenv("LOCAL_STORAGE_PATH", "./data/uploads")).resolve()
        try:
            relative_path = Path(storage_path).relative_to(uploads_root)
            return f"/storage/{relative_path}"
        except ValueError:
            logger.error(f"无法计算相对路径: {storage_path} vs {uploads_root}")
            return None

    @classmethod
    def get_file_url(cls, project_id: str, filename: str) -> Optional[str]:
        """
        获取项目内文件的 URL

        Args:
            project_id: 项目ID
            filename: 文件名（如 "opening_image.jpg", "frames/segment_0_last.jpg"）

        Returns:
            完整 URL，如 "/storage/projects/2026-01-26/eating-template/abc123/opening_image.jpg"
        """
        prefix = cls.get_project_url_prefix(project_id)
        if prefix:
            return f"{prefix}/{filename}"
        return None

    @classmethod
    def get_segment_video_url(
        cls,
        project_id: str,
        segment_index: int,
        segment_type: Optional[str] = None,
    ) -> Optional[str]:
        """
        获取分段视频的 URL

        Args:
            project_id: 项目ID
            segment_index: 段索引
            segment_type: 段类型

        Returns:
            视频 URL
        """
        type_map = {
            'intro': 'intro',
            'eating': 'eating',
            'outro': 'outro'
        }
        type_suffix = type_map.get(segment_type, 'segment') if segment_type else 'segment'
        filename = f"segments/segment_{segment_index}_{type_suffix}.mp4"
        return cls.get_file_url(project_id, filename)

    @classmethod
    def get_segment_frame_url(
        cls,
        project_id: str,
        segment_index: int,
        frame_type: str,  # "first" or "last"
    ) -> Optional[str]:
        """
        获取分段帧的 URL

        Args:
            project_id: 项目ID
            segment_index: 段索引
            frame_type: 帧类型 ("first" or "last")

        Returns:
            帧 URL
        """
        filename = f"frames/segment_{segment_index}_{frame_type}.jpg"
        return cls.get_file_url(project_id, filename)


# 全局实例
_project_path_service = ProjectPathService()


def get_project_path_service() -> ProjectPathService:
    """获取项目路径服务实例"""
    return _project_path_service
