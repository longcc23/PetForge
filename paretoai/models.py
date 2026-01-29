from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel


class Creator(SQLModel, table=True):
    id: str = Field(primary_key=True)
    platform: str = Field(default="xiaohongshu", index=True)
    nickname: Optional[str] = None
    followers: Optional[int] = Field(default=None, index=True)
    # 博主主页信息
    description: Optional[str] = Field(default=None)  # 自我介绍/Bio
    red_id: Optional[str] = Field(default=None)  # 小红书号
    ip_location: Optional[str] = Field(default=None)  # IP 属地
    avatar_url: Optional[str] = Field(default=None)  # 头像 URL
    following_count: Optional[int] = Field(default=None)  # 关注数
    note_count: Optional[int] = Field(default=None)  # 笔记数
    registration_date: Optional[datetime] = Field(default=None, index=True)  # 账号注册时间
    # 雷达系统扩展字段
    total_likes: Optional[int] = Field(default=None)  # 获赞与收藏总数
    avg_likes: Optional[float] = Field(default=None)  # 平均点赞
    hit_rate: Optional[float] = Field(default=None)   # 爆款率 (0.0-1.0)
    dark_horse_index: Optional[float] = Field(default=None, index=True)  # 黑马指数
    is_dark_horse: bool = Field(default=False, index=True)  # 是否黑马博主
    is_scanned: bool = Field(default=False, index=True)  # 是否已深度扫描
    last_scanned_at: Optional[datetime] = Field(default=None)  # 最后扫描时间
    last_analysis_json: Optional[str] = Field(default=None)  # 最后一次 AI 诊断结果 (JSON)


class Note(SQLModel, table=True):
    id: str = Field(primary_key=True)
    creator_id: str = Field(index=True)
    title: str
    content: str
    cover_url: Optional[str] = None
    likes: int = Field(default=0, index=True)
    comments: int = Field(default=0)  # 评论数
    collects: int = Field(default=0)  # 收藏数
    created_at: Optional[datetime] = Field(default=None, index=True)
    raw_json: Optional[str] = None
    diagnosis_json: Optional[str] = None
    # 来源标识
    source: str = Field(default="manual", index=True)  # manual=粘贴导入, radar=雷达扫描
    xsec_token: Optional[str] = Field(default=None)  # 小红书访问令牌
    # 雷达系统扩展字段
    from_tag: Optional[str] = Field(default=None, index=True)  # 来源标签
    viral_score: Optional[float] = Field(default=None, index=True)  # 爆款指数
    dark_horse_index: Optional[float] = Field(default=None, index=True)  # 黑马指数


class TwinAnalysis(SQLModel, table=True):
    id: str = Field(primary_key=True)
    creator_id: str = Field(index=True)
    topic: str = Field(index=True)
    high_note_id: str = Field(index=True)
    low_note_id: str = Field(index=True)
    similarity: float
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    report_json: Optional[str] = None


class Template(SQLModel, table=True):
    id: str = Field(primary_key=True)
    analysis_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    positive_script: str
    negative_warning: str


class Tag(SQLModel, table=True):
    """标签池：用于雷达系统的关键词裂变扫描"""
    name: str = Field(primary_key=True)  # 标签名，如 #猫咪绝育
    source: str = Field(default="seed", index=True)  # seed=种子词, discovered=衍生发现
    status: str = Field(default="pending", index=True)  # pending, scanning, scanned
    priority: int = Field(default=0, index=True)  # 扫描优先级，越高越先扫
    hot_score: int = Field(default=0, index=True)  # 热度分（该标签下笔记的总赞数）
    note_count: int = Field(default=0)  # 扫到的笔记数
    last_scanned_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RadarTask(SQLModel, table=True):
    """雷达任务队列：管理爬虫异步任务"""
    id: str = Field(primary_key=True)
    task_type: str = Field(index=True)  # SCAN_KEYWORD, FETCH_CREATOR, DEEP_DIVE, TREND_SCOUT
    target: str  # 目标：关键词 或 creator_id
    status: str = Field(default="pending", index=True)  # pending, running, completed, failed
    priority: int = Field(default=0, index=True)
    retry_count: int = Field(default=0)
    max_retries: int = Field(default=3)
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TrendScout(SQLModel, table=True):
    """趋势侦察结果：存储发现的细分赛道（V5.0 AI原生版本）"""
    id: str = Field(primary_key=True)
    keyword: str = Field(index=True)  # 搜索关键词
    niche_name: str  # 细分赛道名称
    heat_score: int = Field(ge=1, le=100)  # 热度分数
    reasoning: str  # 火爆原因分析
    audience_tags: str  # JSON格式的受众标签列表
    representative_creators: str  # JSON格式的代表博主列表
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    raw_data_json: Optional[str] = None  # 原始搜索数据
    # 🔥 V5.0 新增字段：AI可复制性
    ai_replicability_score: int = Field(default=0, ge=0, le=100, index=True)  # AI可复制性评分
    production_method: Optional[str] = None  # 制作方式（如：MJ静态图+GPT文案）


class HunterReport(SQLModel, table=True):
    """Hunter 趋势猎手报告：存储 CSV 报告的结构化数据"""
    id: str = Field(primary_key=True)  # 笔记 ID (从 Note_URL 提取)
    session_id: str = Field(index=True)  # 会话 ID (从文件名提取)
    title: str  # 笔记标题
    category: str = Field(index=True)  # 分类（如：脱口秀）
    efficiency_score: float  # 效率分数
    momentum_score: float  # 动量分数
    likes: int = Field(index=True)  # 点赞数
    comments: int  # 评论数
    collects: int  # 收藏数
    followers: int  # 博主粉丝数
    creator_nickname: str = Field(index=True)  # 博主昵称
    note_url: str  # 笔记 URL
    cover_path: Optional[str] = None  # 封面图路径
    why_it_worked: Optional[str] = None  # 成功原因分析
    days_ago: Optional[int] = None  # 发布天数
    tags: Optional[str] = None  # 标签
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)  # 报告生成时间
    csv_filename: str = Field(index=True)  # 原始 CSV 文件名


class VideoGenerationJob(SQLModel, table=True):
    """视频生成任务表"""
    __tablename__ = "video_generation_jobs"

    # 基础字段
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(index=True, unique=True)  # UUID
    user_id: Optional[str] = None

    # 输入参数
    first_frame_url: str  # 首帧图片URL
    prompt: str           # 生成提示词
    duration: int = 5     # 视频时长(秒) 5-10
    aspect_ratio: str = "9:16"  # 画幅比例
    style: Optional[str] = None  # 风格参数

    # 生成配置
    model: str = "veo3.1"
    api_provider: str = "xianfeiglobal"

    # 状态追踪
    status: str = Field(default="queued", index=True)  # queued, uploading, generating, processing, completed, failed
    progress: int = 0  # 0-100
    error_message: Optional[str] = None

    # 外部任务ID
    external_task_id: Optional[str] = None  # Veo API返回的任务ID

    # 结果数据
    video_url: Optional[str] = None  # 生成视频URL
    video_duration: Optional[float] = None  # 实际时长
    video_size: Optional[int] = None  # 文件大小(bytes)
    video_resolution: Optional[str] = None  # 分辨率

    # 质量评估
    quality_score: Optional[float] = None  # 0-100

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # 元数据
    extra_metadata: Optional[str] = Field(default=None)  # JSON 格式


class BatchTask(SQLModel, table=True):
    """批量工坊的任务表，作为所有项目的元数据中心"""
    __tablename__ = "batch_tasks"

    # 核心ID
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(index=True, unique=True, max_length=50)

    # 关联信息
    user_id: Optional[str] = Field(default=None, index=True)
    feishu_table_id: Optional[str] = Field(default=None, max_length=100)
    feishu_record_id: Optional[str] = Field(default=None, max_length=100)
    template_id: Optional[str] = Field(default=None, index=True, max_length=50)

    # [核心] 物理存储路径
    storage_path: str = Field(description="项目文件在服务器上的完整物理路径")

    # 状态与进度
    status: str = Field(default="pending", index=True, max_length=50)
    progress: Optional[str] = Field(default=None, max_length=50)
    error_message: Optional[str] = Field(default=None)

    # 关键数据 (JSON存储)
    storyboard_json: Optional[str] = Field(default=None)
    segment_urls: Optional[str] = Field(default=None, description='JSON in text format, e.g., {"segment_0": {"video_url": "url1", "last_frame_url": "frame1"}}')
    segment_history: Optional[str] = Field(default=None, description='JSON: 历史记录，e.g., {"segment_0": [{"video_url": "old_url", "archived_at": "2026-01-29T..."}]}')
    final_video_url: Optional[str] = Field(default=None)
    
    # 统计与配置
    total_segments: Optional[int] = Field(default=None)
    current_segment: Optional[int] = Field(default=None)

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})
    
    # 发布日期（来自飞书 release_date 字段，格式：YYYYMMDD）
    publish_date: Optional[str] = Field(default=None, max_length=20)


# ============================================================================
# Epic 1: 工作流引擎数据模型 (BE-1.1)
# ============================================================================

class WorkflowRun(SQLModel, table=True):
    """
    工作流运行记录表 (workflow_runs)

    追踪每次工作流执行的完整生命周期。
    调度器（引擎）必须轻量，执行者（工人）才能健壮。
    """
    __tablename__ = "workflow_runs"

    # 主键
    id: str = Field(primary_key=True, max_length=64)  # run_id: UUID
    project_id: str = Field(index=True, max_length=50)  # 关联 BatchTask.project_id

    # 模板信息
    template_id: Optional[str] = Field(default=None, index=True, max_length=50)
    template_version: Optional[str] = Field(default=None, max_length=20)  # 模板版本

    # 工作流定义
    workflow_type: str = Field(index=True, max_length=50)  # single_video, batch_video, etc.
    workflow_definition: Optional[str] = Field(default=None)  # JSON: 完整工作流定义

    # 状态管理
    status: str = Field(
        default="pending",
        index=True,
        max_length=50,
        description="pending, running, completed, failed, cancelled, paused"
    )

    # 进度追踪
    total_steps: int = Field(default=0)
    completed_steps: int = Field(default=0)
    current_step_id: Optional[str] = Field(default=None, max_length=64)

    # 输入输出
    input_params: Optional[str] = Field(default=None)  # JSON: 输入参数
    output_result: Optional[str] = Field(default=None)  # JSON: 最终结果

    # 错误处理
    error_message: Optional[str] = Field(default=None)
    failed_step_id: Optional[str] = Field(default=None, max_length=64)

    # Celery 任务关联
    celery_task_id: Optional[str] = Field(default=None, max_length=64, index=True)

    # 手动干预相关
    requires_manual_intervention: bool = Field(default=False)
    manual_intervention_step: Optional[str] = Field(default=None, max_length=64)
    intervention_resolved: bool = Field(default=False)

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

    # 执行统计
    total_duration_seconds: Optional[float] = Field(default=None)


class WorkflowStep(SQLModel, table=True):
    """
    工作流步骤执行表 (workflow_steps)

    记录工作流中每个步骤的执行状态。
    """
    __tablename__ = "workflow_steps"

    # 主键
    id: str = Field(primary_key=True, max_length=64)  # step_id: {run_id}_step_{N}
    run_id: str = Field(index=True, max_length=64)  # 关联 WorkflowRun.id

    # 步骤定义
    step_name: str = Field(max_length=100)  # generate_storyboard, generate_video_segment, etc.
    step_type: str = Field(max_length=50, index=True)  # task, group, chord, chain
    step_order: int = Field(index=True)  # 执行顺序

    # 输入输出
    input_params: Optional[str] = Field(default=None)  # JSON: 步骤输入参数
    output_result: Optional[str] = Field(default=None)  # JSON: 步骤输出结果

    # 状态管理
    status: str = Field(
        default="pending",
        index=True,
        max_length=50,
        description="pending, dispatched, running, completed, failed, skipped, retrying"
    )

    # Celery 任务关联
    celery_task_id: Optional[str] = Field(default=None, max_length=64, index=True)
    celery_task_name: Optional[str] = Field(default=None, max_length=200)  # 完整任务名

    # 重试信息
    retry_count: int = Field(default=0)
    max_retries: int = Field(default=3)

    # 错误处理
    error_message: Optional[str] = Field(default=None)
    error_type: Optional[str] = Field(default=None, max_length=100)

    # 进度追踪（用于长时间运行的任务）
    progress: int = Field(default=0)  # 0-100
    progress_message: Optional[str] = Field(default=None)

    # 依赖关系
    depends_on: Optional[str] = Field(default=None)  # JSON: 依赖的 step_id 列表
    is_parallel: bool = Field(default=False)  # 是否并行执行

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    dispatched_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # 执行统计
    duration_seconds: Optional[float] = Field(default=None)
    queue_wait_seconds: Optional[float] = Field(default=None)  # 在队列中等待的时间


# ============================================================================
# Sprint 2: 双质量门数据模型 (BE-2.3, BE-2.13)
# ============================================================================

class BlueprintReview(SQLModel, table=True):
    """
    蓝图审核表 (blueprint_reviews) - 质量门 #1

    存储AI一次性生成的完整7段分镜，运营审核后决定：
    - approve: 批准蓝图，继续生成视频
    - edit_approve: 编辑后批准
    - reject: 驳回重写

    PRD V2.2_FINAL 章节 3.1
    """
    __tablename__ = "blueprint_reviews"

    # 主键
    id: str = Field(primary_key=True, max_length=64)  # UUID
    batch_id: str = Field(index=True, max_length=50)  # 批次 ID
    run_id: Optional[str] = Field(default=None, max_length=64, index=True)  # 关联 WorkflowRun.id

    # 蓝图内容
    full_storyboard: str = Field(description="JSON: 完整7段分镜")  # AI生成的完整分镜
    original_storyboard: Optional[str] = Field(default=None)  # 原始AI生成的分镜（用于追溯编辑差异）

    # 审核状态
    status: str = Field(
        default="pending",
        index=True,
        max_length=20,
        description="pending: 待审核 | approved: 已批准 | rejected: 已驳回 | edited: 编辑后批准"
    )
    reviewed_at: Optional[datetime] = Field(default=None)
    reviewer_id: Optional[str] = Field(default=None, max_length=50)

    # 审核操作
    action: Optional[str] = Field(
        default=None,
        max_length=20,
        description="approve: 批准 | edit_approve: 编辑并批准 | reject: 驳回重写"
    )

    # 编辑内容 (当 action=edit_approve 时)
    edited_storyboard: Optional[str] = Field(default=None)  # 人类编辑后的分镜 JSON
    edit_diff: Optional[str] = Field(default=None)  # 编辑差异记录 JSON

    # 驳回重试记录
    reject_count: int = Field(default=0)
    last_rejected_at: Optional[datetime] = Field(default=None)
    reject_reason: Optional[str] = Field(default=None)  # 驳回原因

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

    def get_effective_storyboard(self) -> str:
        """获取有效的分镜数据（编辑后的优先）"""
        return self.edited_storyboard or self.full_storyboard


class SegmentReview(SQLModel, table=True):
    """
    片段审核表 (segment_reviews) - 质量门 #2

    串行生成模式下，每段视频生成后立即进行AI质检，
    根据置信度决定是否需要人工审核：
    - 高置信度 (>95%): 自动通过
    - 中置信度 (70-95%): 人工复核
    - 低置信度 (<70%): 自动进入人工审核

    人工审核后可选择：
    - pass: 通过，继续下一段
    - retry_ai: AI重试（保持脚本不变）
    - retry_script: 修改脚本后重试

    PRD V2.2_FINAL 章节 3.2
    """
    __tablename__ = "segment_reviews"

    # 主键
    id: str = Field(primary_key=True, max_length=64)  # UUID
    batch_id: str = Field(index=True, max_length=50)  # 批次 ID
    run_id: Optional[str] = Field(default=None, max_length=64, index=True)  # 关联 WorkflowRun.id
    segment_index: int = Field(index=True, ge=0, le=6)  # 片段索引 0-6 (对应7段)

    # 片段信息
    video_url: Optional[str] = Field(default=None, max_length=500)
    first_frame_url: Optional[str] = Field(default=None, max_length=500)  # 首帧
    last_frame_url: Optional[str] = Field(default=None, max_length=500)  # 尾帧（用于下一段的输入）
    storyboard_segment: Optional[str] = Field(default=None)  # JSON: 该段对应的分镜描述

    # AI 质检结果
    qa_result: Optional[str] = Field(default=None)  # JSON: AI质检完整结果
    qa_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)  # 置信度 0-1
    qa_recommendation: Optional[str] = Field(
        default=None,
        max_length=20,
        description="pass: 通过 | reject: 驳回 | manual_review: 需人工复核"
    )
    qa_details: Optional[str] = Field(default=None)  # JSON: 质检详情

    # 人工审核
    status: str = Field(
        default="pending",
        index=True,
        max_length=20,
        description="pending: 待审核 | passed: 已通过 | rejected: 已驳回 | skipped: 跳过(高置信度)"
    )
    reviewed_at: Optional[datetime] = Field(default=None)
    reviewer_id: Optional[str] = Field(default=None, max_length=50)
    reviewer_comment: Optional[str] = Field(default=None)  # 审核意见

    # 审核操作
    action: Optional[str] = Field(
        default=None,
        max_length=20,
        description="pass: 通过 | retry_ai: AI重试 | retry_script: 修改脚本重试"
    )

    # 编辑内容 (当 action=retry_script 时)
    edited_script: Optional[str] = Field(default=None)  # 修改后的当前段脚本
    original_script: Optional[str] = Field(default=None)  # 原始脚本（用于追溯）

    # 重试记录
    retry_count: int = Field(default=0)
    last_retry_action: Optional[str] = Field(default=None, max_length=20)
    last_retry_at: Optional[datetime] = Field(default=None)

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"onupdate": datetime.utcnow})

    class Config:
        # 确保 (batch_id, segment_index) 唯一
        pass

    def needs_manual_review(self) -> bool:
        """判断是否需要人工审核"""
        if self.qa_confidence is None:
            return True
        if self.qa_recommendation == "manual_review":
            return True
        if self.qa_confidence < 0.70:
            return True
        return False

    def can_auto_pass(self) -> bool:
        """判断是否可以自动通过"""
        if self.qa_confidence is None:
            return False
        if self.qa_recommendation == "pass" and self.qa_confidence >= 0.95:
            return True
        return False
