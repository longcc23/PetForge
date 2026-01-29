"""
批量处理工坊 API 路由
提供飞书多维表格集成的批量视频生成功能
"""
import os
import json
import asyncio
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from sqlmodel import Session, select

from paretoai.services.feishu_bitable import FeishuBitableService, parse_feishu_record_to_task
from paretoai.services.storyboard_service import get_storyboard_service
from paretoai.services.video_segment_service import get_video_segment_service
from paretoai.services.api_job_store import get_api_job_store
from paretoai.services.feishu_drive_service import FeishuDriveService
from paretoai.services.feishu_user_oauth_store import get_feishu_user_oauth_store
from paretoai.models import BatchTask
from paretoai.db import engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/batch", tags=["batch"])

# 存储服务实例（简化实现，生产环境应该用 Redis 或数据库）
_feishu_services: dict = {}

# 连接状态持久化文件路径
FEISHU_CONNECTION_STATE_FILE = Path("./data/feishu_connections.json")


# ========== 请求模型 ==========

class ConnectFeishuRequest(BaseModel):
    app_id: str
    app_secret: str
    table_id: str
    app_token: Optional[str] = None  # 可选，如果 table_id 是完整格式则不需要
    tenant_access_token: Optional[str] = None  # 可选，用于调试，直接使用提供的 token
    drive_folder_token: Optional[str] = None  # 云空间文件夹 token


class GenerateStoryboardsRequest(BaseModel):
    table_id: str
    record_ids: List[str]
    concurrency: int = 10
    overwrite: bool = False  # 是否允许覆盖已有分镜


class GenerateSegmentsRequest(BaseModel):
    table_id: str
    record_ids: List[str]
    segment_index: int
    concurrency: int = 5


class MergeVideosRequest(BaseModel):
    table_id: str
    record_ids: List[str]


class RetryTaskRequest(BaseModel):
    table_id: str
    record_id: str
    action: str  # 'storyboard' | 'segment' | 'merge'
    segment_index: Optional[int] = None


class CascadeRedoRequest(BaseModel):
    """级联重做请求"""
    table_id: str
    record_id: str
    from_segment_index: int  # 从哪一段开始重做
    regenerate_storyboard: bool = False  # 是否重新生成分镜


class EditAndRegenerateRequest(BaseModel):
    """编辑提示词并重新生成请求"""
    table_id: str
    record_id: str
    project_id: str
    segment_index: int
    crucial: str
    action: str
    sound: str
    negative_constraint: str = ""
    crucial_zh: str = ""
    action_zh: str = ""
    sound_zh: str = ""
    negative_constraint_zh: str = ""


class BatchSavePromptsItem(BaseModel):
    """批量保存提示词项"""
    record_id: str
    project_id: str
    segment_index: int
    crucial: str
    action: str
    sound: str
    negative_constraint: str = ""
    crucial_zh: str = ""
    action_zh: str = ""
    sound_zh: str = ""
    negative_constraint_zh: str = ""
    is_modified: bool = True


class BatchSavePromptsRequest(BaseModel):
    """批量保存提示词请求"""
    table_id: str
    items: List[BatchSavePromptsItem]


class SyncToDriveRequest(BaseModel):
    """同步到云空间请求"""
    table_id: str
    project_ids: List[str]
    folder_token: str
    project_publish_dates: Optional[Dict[str, str]] = None  # projectId -> publishDate (YYYYMMDD)
    incremental: bool = True  # 是否启用增量上传（默认 True）


# ========== 辅助函数 ==========

def _load_feishu_connections():
    """从文件加载飞书连接状态"""
    global _feishu_services
    if FEISHU_CONNECTION_STATE_FILE.exists():
        try:
            with open(FEISHU_CONNECTION_STATE_FILE, "r", encoding="utf-8") as f:
                saved_connections = json.load(f)
                logger.warning(f"从文件加载了 {len(saved_connections)} 个飞书连接状态")
                return saved_connections
        except Exception as e:
            logger.warning(f"加载飞书连接状态失败: {e}")
    return {}

def _save_feishu_connections():
    """保存飞书连接状态到文件"""
    try:
        # 只保存连接信息，不保存服务实例（服务实例无法序列化）
        connections_to_save = {}
        for table_id, conn_info in _feishu_services.items():
            connections_to_save[table_id] = {
                "app_token": conn_info.get("app_token"),
                "table_id": conn_info.get("table_id"),
                "app_id": conn_info.get("app_id"),
                "app_secret": conn_info.get("app_secret"),
                "tenant_access_token": conn_info.get("tenant_access_token"),
                "drive_folder_token": conn_info.get("drive_folder_token"),
            }
        
        # 确保目录存在
        FEISHU_CONNECTION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        with open(FEISHU_CONNECTION_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(connections_to_save, f, indent=2, ensure_ascii=False)
        logger.warning(f"已保存 {len(connections_to_save)} 个飞书连接状态到文件")
    except Exception as e:
        logger.error(f"保存飞书连接状态失败: {e}")

async def _restore_feishu_connections():
    """恢复飞书连接状态（服务启动时调用）"""
    global _feishu_services
    saved_connections = _load_feishu_connections()

    for table_id, conn_info in saved_connections.items():
        try:
            app_id = conn_info.get("app_id")
            app_secret = conn_info.get("app_secret")
            tenant_access_token = conn_info.get("tenant_access_token")
            app_token = conn_info.get("app_token")
            actual_table_id = conn_info.get("table_id")

            if not all([app_id, app_secret, app_token, actual_table_id]):
                logger.warning(f"连接信息不完整，跳过恢复: {table_id}")
                continue

            # 重新创建服务实例
            service = FeishuBitableService(
                app_id,
                app_secret,
                tenant_access_token=tenant_access_token
            )

            # 如果 token 为 null 或无效，主动刷新
            if not tenant_access_token:
                logger.info(f"Token 为空，尝试刷新: table_id={table_id}")
                try:
                    tenant_access_token = await service._get_tenant_access_token()
                    # 更新服务实例的token
                    service._tenant_access_token = tenant_access_token
                    service._token_expires_at = datetime.now().timestamp() + 7200
                    # 关键修复：直接更新 saved_connections，这样后续保存才会生效
                    saved_connections[table_id]["tenant_access_token"] = tenant_access_token
                    logger.info(f"✅ 成功刷新 token: table_id={table_id}, token={tenant_access_token[:30]}...")
                except Exception as e:
                    logger.warning(f"⚠️ 刷新 token 失败: {e}")
                    continue

            # 验证连接是否有效（通过获取一条记录来验证）
            try:
                await service.list_records(app_token, actual_table_id, page_size=1)
                _feishu_services[table_id] = {
                    "service": service,
                    "app_token": app_token,
                    "table_id": actual_table_id,
                    "app_id": app_id,
                    "app_secret": app_secret,
                    "tenant_access_token": tenant_access_token,
                    "drive_folder_token": conn_info.get("drive_folder_token"),
                }
                logger.warning(f"✅ 成功恢复飞书连接: table_id={table_id}")
            except Exception as e:
                logger.warning(f"⚠️ 连接已失效，跳过恢复: table_id={table_id}, error={e}")
        except Exception as e:
            logger.error(f"恢复连接失败: table_id={table_id}, error={e}")

    # 保存更新后的连接状态（包含刷新的 token）
    if saved_connections:
        try:
            FEISHU_CONNECTION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(FEISHU_CONNECTION_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(saved_connections, f, indent=2, ensure_ascii=False)
            logger.warning(f"已保存 {len(saved_connections)} 个飞书连接状态到文件（包含刷新的 token）")
        except Exception as e:
            logger.error(f"保存飞书连接状态失败: {e}")

def get_feishu_service(table_id: str) -> FeishuBitableService:
    """获取飞书服务实例"""
    if table_id not in _feishu_services:
        raise HTTPException(status_code=400, detail="未连接飞书表格")
    return _feishu_services[table_id]["service"]


def get_app_token(table_id: str) -> str:
    """获取 app_token"""
    if table_id not in _feishu_services:
        raise HTTPException(status_code=400, detail="未连接飞书表格")
    return _feishu_services[table_id]["app_token"]


async def _auto_update_generated_videos(service: FeishuBitableService, app_token: str, table_id: str):
    """连接成功后自动更新已生成的视频信息（V2 结构：从数据库获取项目列表）"""
    try:
        import traceback
        logger.warning("开始自动更新已生成的视频信息...")  # 使用 WARNING 级别确保输出
        logger.warning(f"调用栈:\n{''.join(traceback.format_stack()[-5:-1])}")  # 打印调用栈
        # 从数据库获取所有项目（V2 结构）
        from paretoai.services.project_path_service import get_project_path_service
        from sqlmodel import select
        from paretoai.models import BatchTask
        from paretoai.db import engine

        path_service = get_project_path_service()

        # 获取所有记录
        records = await service.get_all_records(app_token, table_id)
        logger.warning(f"获取到 {len(records)} 条飞书记录")  # 使用 WARNING 级别确保输出

        # 从数据库获取项目列表
        with Session(engine) as session:
            statement = select(BatchTask)
            tasks = session.exec(statement).all()

        if not tasks:
            logger.warning("数据库中没有项目记录")
            return

        logger.warning(f"从数据库获取到 {len(tasks)} 个项目")

        # 遍历数据库中的项目
        project_count = 0
        for task in tasks:
            project_count += 1
            project_id = task.project_id
            project_storage_path = task.storage_path

            if not project_storage_path:
                logger.warning(f"项目 {project_id} 没有存储路径")
                continue

            project_dir = Path(project_storage_path)
            if not project_dir.exists():
                logger.warning(f"项目目录不存在: {project_dir}")
                continue

            logger.info(f"检查项目 {project_count}: {project_id}")

            storyboard_path = project_dir / "storyboard.json"
            
            # 先查找对应的飞书记录（通过 project_id）
            record = None
            record_id = None
            for r in records:
                fields = r.get("fields", {})
                existing_project_id = fields.get("project_id")
                if existing_project_id == project_id:
                    record = r
                    record_id = r.get("record_id")
                    logger.warning(f"  ✅ 通过 project_id 找到对应的飞书记录: record_id={record_id}")
                    break
            
            if not record:
                logger.warning(f"  ❌ 未找到对应的飞书记录 (project_id={project_id})，跳过")
                continue
            
            fields = record.get("fields", {})
            
            # 如果 storyboard.json 不存在，清空飞书相关字段
            if not storyboard_path.exists():
                logger.warning(f"  ⚠️ storyboard.json 不存在，清空飞书相关字段")
                
                # 构建清空字段：将所有 storyboard 相关字段设为空
                final_update_fields = {
                    "project_id": project_id,
                    "storyboard_json": "",  # 清空 storyboard_json
                    "segments_json": "",    # 清空 segments_json
                    "status": "pending",    # 状态设为 pending
                    "error_message": ""
                }
                
                # 清空所有 segment_N_video_url 和 segment_N_last_frame_url 字段
                # 需要先获取表格字段列表，找出所有 segment 相关字段
                try:
                    table_fields = await service.get_table_fields(app_token, table_id)
                    field_name_map = {f.get("field_name"): f.get("field_id") for f in table_fields if f.get("field_name")}
                    existing_fields = set(fields.keys())
                    
                    # 清空所有 segment_N_video_url 字段（假设最多 20 段）
                    for i in range(20):
                        seg_video_field = f"segment_{i}_video_url"
                        seg_frame_field = f"segment_{i}_last_frame_url"
                        if seg_video_field in field_name_map or seg_video_field in existing_fields:
                            final_update_fields[seg_video_field] = ""
                        if seg_frame_field in field_name_map or seg_frame_field in existing_fields:
                            final_update_fields[seg_frame_field] = ""
                    
                    # 只更新存在的字段
                    filtered_fields = {}
                    for field_name, field_value in final_update_fields.items():
                        if field_name in field_name_map or field_name in existing_fields:
                            filtered_fields[field_name] = field_value
                    
                    if filtered_fields:
                        await service.update_record(app_token, table_id, record_id, filtered_fields)
                        logger.warning(f"  ✅ 已清空飞书记录 {record_id} 的 storyboard 相关字段，状态设为 pending")
                    else:
                        logger.warning(f"  ⚠️ 没有可更新的字段")
                except Exception as e:
                    logger.error(f"  ❌ 清空飞书记录失败: {e}", exc_info=True)
                continue
            
            # 读取storyboard获取record_id（用于验证）
            storyboard_data = None
            try:
                with open(storyboard_path, "r", encoding="utf-8") as f:
                    storyboard_data = json.load(f)
                storyboard_record_id = storyboard_data.get("record_id")
                if storyboard_record_id and storyboard_record_id != record_id:
                    logger.warning(f"  ⚠️ storyboard.json 中的 record_id ({storyboard_record_id}) 与飞书记录不匹配 ({record_id})，使用 project_id 匹配的记录")
            except Exception as e:
                logger.warning(f"  跳过：读取 storyboard.json 失败: {e}")
                continue
            
            # ========================================================================
            # 【架构重构】只从数据库 segment_urls 读取 segments 数据
            # storyboard.json 只用于获取分镜脚本内容（同步到飞书 storyboard_json 字段）
            # ========================================================================
            storyboards = storyboard_data.get("storyboards", [])
            segments_data = {}
            
            # 【唯一数据源】从数据库 segment_urls 读取
            if task.segment_urls:
                try:
                    segments_data = json.loads(task.segment_urls)
                    logger.info(f"  从数据库 segment_urls 读取 {len(segments_data)} 个段")
                except json.JSONDecodeError as e:
                    logger.warning(f"  解析 segment_urls 失败: {e}")
                    segments_data = {}
            
            # 构建更新字段：本地有什么就覆盖什么
            # 注意：segments_json 字段在飞书表格中不存在，只存储在本地，不更新到飞书
            final_update_fields = {
                "project_id": project_id,
                "storyboard_json": json.dumps(storyboards, ensure_ascii=False),
                # segments_json 字段在飞书表格中不存在，不更新到飞书
            }
            
            # 更新独立字段
            # 注意：segment_N_last_frame_url 只存储在本地 storyboard.json，不更新到飞书表格
            for seg_key, seg_data in segments_data.items():
                segment_index = seg_key.replace("segment_", "")
                final_update_fields[f"segment_{segment_index}_video_url"] = seg_data.get("video_url", "")
                # last_frame_url 只存储在本地，不更新到飞书表格
            
            # 计算状态：基于 storyboard.json 中的段数
            total_segments = len(storyboards)
            
            # 如果 storyboards 为空，状态设为 pending
            if total_segments == 0:
                final_update_fields["status"] = "pending"
            else:
                completed_count = sum(1 for i in range(total_segments) 
                                    if segments_data.get(f"segment_{i}", {}).get("status") == "completed" 
                                    or (not segments_data.get(f"segment_{i}", {}).get("status") 
                                        and segments_data.get(f"segment_{i}", {}).get("video_url")))
                
                if completed_count == total_segments:
                    final_update_fields["status"] = "all_segments_ready"
                elif completed_count > 0:
                    # 有部分段完成，但不是全部 → 保持 storyboard_ready 状态
                    # generating_segment_X 只在实际生成时由后端设置，不应该在这里设置
                    final_update_fields["status"] = "storyboard_ready"
                else:
                    final_update_fields["status"] = "storyboard_ready"
            
            final_update_fields["error_message"] = ""
            
            logger.warning(f"  从 storyboard.json 收集到 {len(segments_data)} 个视频段，总段数: {total_segments}")
            
            # 直接覆盖飞书（只更新存在的字段）
            try:
                table_fields = await service.get_table_fields(app_token, table_id)
                field_name_map = {f.get("field_name"): f.get("field_id") for f in table_fields if f.get("field_name")}
                existing_fields = set(fields.keys())
                
                # 清空飞书中多余的 segment 字段（本地没有的 segment）
                # 找出本地实际存在的 segment 索引
                local_segment_indices = set()
                for seg_key in segments_data.keys():
                    try:
                        idx = int(seg_key.replace("segment_", ""))
                        local_segment_indices.add(idx)
                    except ValueError:
                        pass
                
                # 清空不在本地 storyboard 中的 segment 字段（假设最多 20 段）
                for i in range(20):
                    if i not in local_segment_indices:
                        seg_video_field = f"segment_{i}_video_url"
                        seg_frame_field = f"segment_{i}_last_frame_url"
                        if seg_video_field in field_name_map or seg_video_field in existing_fields:
                            final_update_fields[seg_video_field] = ""
                        if seg_frame_field in field_name_map or seg_frame_field in existing_fields:
                            final_update_fields[seg_frame_field] = ""
                
                # 同步 updated_at 到飞书（日期字段用毫秒时间戳）
                if "updated_at" in field_name_map or "updated_at" in existing_fields:
                    from paretoai.services.feishu_bitable import feishu_date_now_ms
                    final_update_fields["updated_at"] = feishu_date_now_ms()
                
                # 只更新存在的字段
                filtered_fields = {}
                for field_name, field_value in final_update_fields.items():
                    if field_name in field_name_map or field_name in existing_fields:
                        filtered_fields[field_name] = field_value
                
                if filtered_fields:
                    await service.update_record(app_token, table_id, record_id, filtered_fields)
                    status_msg = final_update_fields.get('status')
                    if total_segments > 0:
                        completed_count = sum(1 for i in range(total_segments) 
                                            if segments_data.get(f"segment_{i}", {}).get("status") == "completed" 
                                            or (not segments_data.get(f"segment_{i}", {}).get("status") 
                                                and segments_data.get(f"segment_{i}", {}).get("video_url")))
                        logger.warning(f"  ✅ 已更新飞书记录 {record_id} (状态: {status_msg}, 已完成 {completed_count}/{total_segments} 段)")
                    else:
                        logger.warning(f"  ✅ 已更新飞书记录 {record_id} (状态: {status_msg}, storyboards 为空)")
                else:
                    logger.warning(f"  ⚠️ 没有可更新的字段")
            except Exception as e:
                logger.error(f"  ❌ 更新飞书记录失败: {e}", exc_info=True)
    
        logger.warning(f"自动更新完成，检查了 {project_count} 个项目")  # 使用 WARNING 级别确保输出
    except Exception as e:
        logger.error(f"自动更新视频信息时出错: {e}", exc_info=True)


# ========== API 路由 ==========

@router.post("/connect-feishu")
async def connect_feishu(req: ConnectFeishuRequest):
    """连接飞书多维表格"""
    try:
        # 解析 app_token 和 table_id
        # 支持两种格式：
        # 1. table_id = "appXXXXX/tblYYYYY" (完整格式)
        # 2. table_id = "tblYYYYY" + app_token 单独提供
        parts = req.table_id.split("/")
        if len(parts) == 2:
            # 完整格式：app_token/table_id
            app_token, table_id = parts
        elif req.app_token:
            # 单独提供 app_token
            app_token = req.app_token
            table_id = req.table_id
        else:
            # 如果都没有，尝试从 table_id 中提取（向后兼容）
            # 但这种情况通常不会成功，因为 table_id 格式是 tblXXXXX
            raise HTTPException(
                status_code=400,
                detail="缺少 app_token。请提供 app_token 字段，或使用 'app_token/table_id' 格式的 table_id"
            )
        
        # 验证格式（基本验证，具体格式由飞书 API 验证）
        if not app_token or len(app_token.strip()) == 0:
            raise HTTPException(status_code=400, detail="app_token 不能为空")
        if not table_id or len(table_id.strip()) == 0:
            raise HTTPException(status_code=400, detail="table_id 不能为空")
        
        # 清理空白字符
        app_token = app_token.strip()
        table_id = table_id.strip()

        # 创建服务实例（如果提供了 tenant_access_token，直接使用）
        logger.info(f"创建飞书服务: app_id={req.app_id}, app_token={app_token}, table_id={table_id}, has_tenant_token={bool(req.tenant_access_token)}")
        service = FeishuBitableService(
            req.app_id, 
            req.app_secret,
            tenant_access_token=req.tenant_access_token
        )

        # 验证连接：通过获取记录列表来验证（get_table_info endpoint 不存在）
        # 获取记录数来验证连接和权限
        records = await service.list_records(app_token, table_id, page_size=1)
        record_count = records.get("total", 0)
        
        # 尝试获取表格名称（如果 records 中有 table 信息）
        table_name = "未知表格"
        # 由于无法直接获取表格信息，我们使用 app_token 作为标识
        # 或者可以从第一条记录中推断（如果有的话）

        # 存储服务实例
        _feishu_services[req.table_id] = {
            "service": service,
            "app_token": app_token,
            "table_id": table_id,
            "app_id": req.app_id,
            "app_secret": req.app_secret,
            "tenant_access_token": req.tenant_access_token,
            "drive_folder_token": req.drive_folder_token,
        }

        # 保存连接状态到文件（持久化）
        _save_feishu_connections()

        # 连接成功后，自动更新已生成的视频信息
        try:
            await _auto_update_generated_videos(service, app_token, table_id)
        except Exception as e:
            logger.warning(f"自动更新视频信息失败: {e}")

        return {
            "success": True,
            "table_name": table_name,
            "record_count": record_count,
            "app_token": app_token,
            "table_id": table_id,
            "drive_folder_token": req.drive_folder_token,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _ensure_opening_image_downloaded(
    service: FeishuBitableService,
    project_id: str,
    opening_image_url: str
) -> Optional[str]:
    """
    确保 opening_image 已下载到项目目录 (V2 结构：从数据库获取路径)

    Returns:
        项目目录中的 opening_image 路径（V2 格式 URL），如果下载失败返回 None
    """
    if not project_id or not opening_image_url:
        return None

    # 使用 ProjectPathService 获取项目路径（V2 结构）
    from paretoai.services.project_path_service import get_project_path_service
    import os
    path_service = get_project_path_service()
    project_storage_path = path_service.get_project_storage_path(project_id)

    if not project_storage_path:
        logger.warning(f"项目 {project_id} 不存在于数据库中")
        return None

    project_dir = Path(project_storage_path)
    opening_image_path = project_dir / "opening_image.jpg"

    # 使用统一的 URL 生成方法（V2 结构）
    v2_url = path_service.get_file_url(project_id, "opening_image.jpg")
    if not v2_url:
        logger.error(f"无法生成 opening_image URL: project_id={project_id}")
        return None

    # 如果已存在，直接返回 V2 URL
    if opening_image_path.exists():
        return v2_url

    # 需要下载：提取原始飞书 URL（如果 opening_image_url 是代理路径）
    original_url = opening_image_url
    if opening_image_url.startswith("/proxy/image?url="):
        from urllib.parse import unquote, parse_qs
        parsed = parse_qs(opening_image_url.split("?")[1])
        original_url = unquote(parsed.get("url", [""])[0])

    # 下载到项目目录
    try:
        if "open.feishu.cn/open-apis/drive/v1/medias" in original_url:
            # 飞书附件，使用 download_attachment
            import re
            match = re.search(r'/medias/([^/]+)/', original_url)
            if match:
                file_token = match.group(1)
                await service.download_attachment(
                    file_token,
                    str(opening_image_path),
                    original_url=original_url
                )
                logger.info(f"✅ 已下载飞书附件到项目目录: {opening_image_path}")
                return v2_url
            else:
                logger.warning(f"无法从飞书 URL 中提取 file_token: {original_url[:100]}")
        else:
            # 普通 HTTP URL，直接下载
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(original_url)
                response.raise_for_status()
                with open(opening_image_path, "wb") as f:
                    f.write(response.content)
                logger.info(f"✅ 已下载图片到项目目录: {opening_image_path}")
                return v2_url
    except Exception as e:
        logger.warning(f"下载 opening_image 失败 (project_id={project_id}): {e}")
        return None


@router.get("/saved-connections")
async def get_saved_connections():
    """获取已保存的飞书连接列表"""
    try:
        connections = []
        for table_id, conn_info in _feishu_services.items():
            connections.append({
                "table_id": table_id,
                "app_token": conn_info.get("app_token"),
                "drive_folder_token": conn_info.get("drive_folder_token"),
            })
        return {"connections": connections}
    except Exception as e:
        logger.error(f"获取已保存连接失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connection/{table_id}")
async def get_connection_detail(table_id: str):
    """获取指定连接的详细信息"""
    try:
        if table_id not in _feishu_services:
            raise HTTPException(status_code=404, detail="连接不存在")

        conn_info = _feishu_services[table_id]
        return {
            "table_id": table_id,
            "app_id": conn_info.get("app_id"),
            "app_token": conn_info.get("app_token"),
            "table_id": conn_info.get("table_id"),
            "drive_folder_token": conn_info.get("drive_folder_token"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取连接详情失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/local")
async def get_tasks_local(table_id: str):
    """
    【优化】从本地数据库获取任务列表（快速，< 100ms）
    
    这是前端日常刷新使用的接口，不调用飞书API
    """
    try:
        import os
        from pathlib import Path
        
        # 从数据库查询所有任务
        with Session(engine) as session:
            statement = select(BatchTask).where(
                BatchTask.feishu_table_id == table_id
            ).order_by(BatchTask.created_at.desc())
            db_tasks = session.exec(statement).all()
        
        tasks = []
        for task in db_tasks:
            # 构建 opening_image URL
            opening_image_url = ""
            if task.storage_path:
                uploads_path_str = os.getenv("LOCAL_STORAGE_PATH", "./data/uploads")
                uploads_path = Path(uploads_path_str).resolve()
                try:
                    relative_path = Path(task.storage_path).relative_to(uploads_path)
                    opening_image_url = f"/storage/{relative_path}/opening_image.jpg"
                except ValueError:
                    # 路径不在 uploads 下，使用绝对路径
                    opening_image_url = f"/storage/projects/{task.project_id}/opening_image.jpg"
            
            # ========================================================================
            # 【架构重构】segments 只从数据库 segment_urls 读取（唯一数据源）
            # ========================================================================
            segments = []
            total_segments = task.total_segments or 7
            storyboard_json_str = task.storyboard_json or ""
            
            if task.segment_urls:
                try:
                    seg_urls = json.loads(task.segment_urls)
                    for i in range(total_segments):
                        key = f"segment_{i}"
                        seg_data = seg_urls.get(key, {})
                        video_url = seg_data.get("video_url", "")
                        first_frame_url = seg_data.get("first_frame_url", "")
                        last_frame_url = seg_data.get("last_frame_url", "")
                        status = seg_data.get("status", "pending")
                        
                        # 状态校验
                        if video_url and status not in ("completed", "generating"):
                            status = "completed"
                        elif not video_url and status == "completed":
                            status = "pending"
                        
                        segments.append({
                            "videoUrl": video_url,
                            "firstFrameUrl": first_frame_url,
                            "lastFrameUrl": last_frame_url,
                            "status": status,
                        })
                except json.JSONDecodeError as e:
                    logger.warning(f"解析 segment_urls 失败: {e}")
                    # 初始化为空
                    for _ in range(total_segments):
                        segments.append({"videoUrl": "", "firstFrameUrl": "", "lastFrameUrl": "", "status": "pending"})
            else:
                # 没有 segment_urls，初始化为 pending
                for _ in range(total_segments):
                    segments.append({"videoUrl": "", "firstFrameUrl": "", "lastFrameUrl": "", "status": "pending"})
            
            # 构建任务对象（与前端 BatchTask 类型对齐）
            task_dict = {
                "id": task.feishu_record_id or task.project_id,  # 优先使用飞书记录ID
                "actorId": "",
                "projectId": task.project_id,
                "openingImageUrl": opening_image_url,
                "sceneDescription": "",
                "templateId": task.template_id,
                "segmentCount": total_segments,
                "storyboardJson": storyboard_json_str,
                "segments": segments,
                "finalVideoUrl": task.final_video_url,
                "status": task.status or "pending",
                "errorMessage": task.error_message,
                "progress": task.progress or "",
                "updatedAt": task.updated_at.isoformat() if task.updated_at else None,
                "publishDate": task.publish_date or "",
            }
            
            # 只返回有 opening_image 的任务
            if opening_image_url:
                tasks.append(task_dict)
        
        logger.info(f"✅ 本地查询任务列表: {len(tasks)} 条 (table_id={table_id})")
        return {"tasks": tasks, "total": len(tasks)}
    
    except Exception as e:
        logger.error(f"本地查询任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks")
async def get_tasks(table_id: str):
    """
    【全量同步】从飞书获取任务列表并同步到本地数据库
    
    注意：此接口会调用飞书API，较慢（2-5秒），建议仅在以下场景使用：
    - 首次连接飞书时
    - 需要同步飞书新增记录时
    
    日常刷新请使用 GET /tasks/local
    """
    try:
        service = get_feishu_service(table_id)
        app_token = get_app_token(table_id)
        actual_table_id = _feishu_services[table_id]["table_id"]

        # 获取所有记录
        records = await service.get_all_records(app_token, actual_table_id)

        # 转换为任务格式
        tasks = [parse_feishu_record_to_task(r) for r in records]
        
        # 在后台异步下载 opening_image（不阻塞返回）
        async def download_opening_images():
            download_tasks = []
            for task in tasks:
                project_id = task.get("projectId")
                opening_image_url = task.get("openingImageUrl")
                if project_id and opening_image_url:
                    # 如果 opening_image_url 不是本地存储路径（/storage/ 开头），需要下载
                    # 无论是 V1 还是 V2 格式，本地存储都应该以 /storage/ 开头
                    if not opening_image_url.startswith("/storage/"):
                        download_tasks.append(
                            _ensure_opening_image_downloaded(service, project_id, opening_image_url)
                        )
            
            # 并发下载（限制并发数避免过载）
            if download_tasks:
                import asyncio
                semaphore = asyncio.Semaphore(5)  # 最多5个并发下载
                async def download_with_limit(task):
                    async with semaphore:
                        return await task
                
                await asyncio.gather(*[download_with_limit(t) for t in download_tasks], return_exceptions=True)
        
        # 异步执行下载（不等待完成，立即返回任务列表）
        asyncio.create_task(download_opening_images())
        
        # 过滤：只返回有首帧图片的任务（避免显示空任务）
        tasks = [t for t in tasks if t.get("openingImageUrl")]

        return {"tasks": tasks, "total": len(tasks)}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-storyboards")
async def generate_storyboards(req: GenerateStoryboardsRequest):
    """批量生成分镜脚本"""
    try:
        service = get_feishu_service(req.table_id)
        app_token = get_app_token(req.table_id)
        actual_table_id = _feishu_services[req.table_id]["table_id"]

        success_count = 0
        failed_count = 0
        results = []

        # 获取记录详情
        records = await service.get_all_records(app_token, actual_table_id)
        record_map = {r["record_id"]: r for r in records}

        # 获取任务队列存储
        job_store = get_api_job_store()

        # 并发控制
        semaphore = asyncio.Semaphore(req.concurrency)

        async def process_record(record_id: str):
            nonlocal success_count, failed_count
            job = None  # 任务队列 job

            async with semaphore:
                try:
                    # 【任务队列】创建任务记录
                    job = job_store.create_job(
                        table_id=req.table_id,
                        kind="generate_storyboard",
                        record_id=record_id,
                        message="正在生成分镜脚本..."
                    )
                    job_store.update_job(job.id, status="running")

                    record = record_map.get(record_id)
                    if not record:
                        if job:
                            job_store.update_job(job.id, status="failed", error="记录不存在")
                        failed_count += 1
                        return {"record_id": record_id, "success": False, "error": "记录不存在"}

                    fields = record.get("fields", {})

                    # 从飞书记录获取发布日期（用于 V2 目录结构的日期分组）
                    release_date_raw = fields.get("release_date", "")
                    created_at = None
                    publish_date_str = ""  # YYYYMMDD 格式，用于前端显示

                    if release_date_raw:
                        try:
                            # release_date 可能是数字（毫秒时间戳）或字符串
                            if isinstance(release_date_raw, (int, float)):
                                # 毫秒时间戳转换
                                created_at = datetime.fromtimestamp(release_date_raw / 1000 if release_date_raw > 1e12 else release_date_raw)
                                publish_date_str = created_at.strftime("%Y%m%d")
                                logger.info(f"从 release_date 毫秒时间戳解析: {release_date_raw} -> {created_at}, publish_date={publish_date_str}")
                            elif isinstance(release_date_raw, str):
                                # 尝试解析日期字符串
                                # 支持格式：YYYY-MM-DD, YYYYMMDD, MM/DD/YYYY 等
                                release_date_normalized = release_date_raw.strip().replace("-", "").replace("/", "")
                                if len(release_date_normalized) == 8 and release_date_normalized.isdigit():
                                    # YYYYMMDD 格式
                                    created_at = datetime.strptime(release_date_normalized, "%Y%m%d")
                                    publish_date_str = release_date_normalized
                                    logger.info(f"从 release_date 字符串解析: {release_date_normalized} -> {created_at}, publish_date={publish_date_str}")
                                else:
                                    raise ValueError(f"无法解析日期格式: {release_date_raw}")
                            else:
                                raise ValueError(f"不支持的日期类型: {type(release_date_raw)}")
                        except Exception as e:
                            logger.warning(f"解析 release_date 失败: {e}，使用当前时间")
                            created_at = datetime.now()
                            publish_date_str = created_at.strftime("%Y%m%d")
                    else:
                        # 回退到当前时间
                        logger.warning(f"record {record_id} 没有 release_date 字段，使用当前时间")
                        created_at = datetime.now()
                        publish_date_str = created_at.strftime("%Y%m%d")

                    # 生成 project_id（如果已有则复用，否则生成新的）
                    # 【根因修复】优先从数据库查找是否已有项目与此飞书记录关联
                    from paretoai.services.task_status_service import get_task_status_service
                    task_service = get_task_status_service()
                    
                    existing_project_id = None
                    existing_task = None
                    
                    # 步骤1：从数据库查找是否有项目关联此飞书记录
                    db_project_id = task_service.get_project_id_by_feishu_record(record_id)
                    if db_project_id:
                        existing_project_id = db_project_id
                        existing_task = task_service.get_task(db_project_id)
                        logger.info(f"✅ 从数据库找到已关联项目: record_id={record_id} -> project_id={db_project_id}")
                    
                    # 步骤2：回退到飞书记录的 project_id 字段
                    if not existing_project_id:
                        feishu_project_id = fields.get("project_id", "")
                        if feishu_project_id and len(feishu_project_id) == 12:
                            existing_project_id = feishu_project_id
                            existing_task = task_service.get_task(feishu_project_id)
                            logger.info(f"✅ 从飞书字段获取 project_id: {feishu_project_id}")
                    
                    if existing_project_id:
                        # 【C-3 防覆盖机制】检查是否已有分镜数据
                        if not req.overwrite and existing_task and existing_task.storyboard_json:
                            # 已有分镜数据，且未设置 overwrite=true，拒绝覆盖
                            failed_count += 1
                            logger.warning(f"⚠️ 拒绝覆盖已有分镜 (project_id={existing_project_id}, overwrite={req.overwrite})")
                            return {
                                "record_id": record_id,
                                "success": False,
                                "error": "该任务已有分镜数据，如需覆盖请设置 overwrite=true",
                                "has_existing_storyboard": True,
                                "project_id": existing_project_id
                            }
                        else:
                            logger.info(f"✅ 允许覆盖 (project_id={existing_project_id}, 原因: 无分镜数据或 overwrite=true)")
                        
                        project_id = existing_project_id
                        logger.info(f"复用已有 project_id: {project_id}")
                    else:
                        project_id = uuid.uuid4().hex[:12]
                        logger.info(f"生成新 project_id: {project_id}")

                    # 使用 ProjectPathService 创建项目目录并注册到数据库（V2 结构）
                    from paretoai.services.project_path_service import get_project_path_service
                    path_service = get_project_path_service()

                    # 获取 template_id
                    template_id = fields.get("template_id", "eating")

                    # 注册或获取项目（会创建目录并写入数据库）
                    # 使用飞书记录的创建时间，而不是当前系统时间
                    # 【修复】在创建时就传入飞书关联信息，确保新项目从一开始就有完整数据
                    storage_path = path_service.get_or_create_storage_path(
                        project_id=project_id,
                        template_id=template_id,
                        created_at=created_at,  # 使用飞书记录的创建时间
                        feishu_table_id=req.table_id,
                        feishu_record_id=record_id
                    )
                    project_dir = Path(storage_path)

                    # 【双重保障】对于已存在的项目，确保飞书关联信息是最新的
                    try:
                        from paretoai.services.task_status_service import get_task_status_service
                        task_service = get_task_status_service()
                        task_service.ensure_feishu_association(
                            project_id=project_id,
                            feishu_table_id=req.table_id,
                            feishu_record_id=record_id,
                            publish_date=publish_date_str
                        )
                        logger.info(f"✅ 已关联飞书记录: project_id={project_id}, record_id={record_id}, publish_date={publish_date_str}")
                    except Exception as db_error:
                        logger.warning(f"飞书关联失败: {db_error}")

                    opening_image_path = project_dir / "opening_image.jpg"

                    # 使用统一的 URL 生成方法（V2 结构）
                    v2_image_url = path_service.get_file_url(project_id, "opening_image.jpg")

                    # 如果项目目录中已有 opening_image，直接使用
                    if opening_image_path.exists():
                        opening_image_url = v2_image_url
                        logger.info(f"✅ 使用项目目录中的 opening_image: {opening_image_url}")
                    else:
                        # 从飞书获取 opening_image_url
                        opening_image = fields.get("opening_image_url", "")
                        if isinstance(opening_image, list) and len(opening_image) > 0:
                            opening_image = opening_image[0].get("url", "")
                        elif isinstance(opening_image, dict):
                            opening_image = opening_image.get("url", "")

                        if not opening_image:
                            failed_count += 1
                            return {"record_id": record_id, "success": False, "error": "缺少首帧图片"}

                        # 下载到项目目录
                        logger.info(f"项目目录中没有 opening_image，开始从飞书下载: {opening_image[:100]}...")
                        try:
                            if "open.feishu.cn/open-apis/drive/v1/medias" in opening_image:
                                # 飞书附件，使用 download_attachment
                                import re
                                match = re.search(r'/medias/([^/]+)/', opening_image)
                                if match:
                                    file_token = match.group(1)
                                    await service.download_attachment(
                                        file_token,
                                        str(opening_image_path),
                                        original_url=opening_image
                                    )
                                    logger.info(f"✅ 已下载飞书附件到项目目录: {opening_image_path}")
                                else:
                                    raise ValueError("无法从飞书 URL 中提取 file_token")
                            else:
                                # 普通 HTTP URL，直接下载
                                import httpx
                                async with httpx.AsyncClient(timeout=30) as client:
                                    response = await client.get(opening_image)
                                    response.raise_for_status()
                                    with open(opening_image_path, "wb") as f:
                                        f.write(response.content)
                                    logger.info(f"✅ 已下载图片到项目目录: {opening_image_path}")

                            # 使用 V2 格式的 URL
                            opening_image_url = v2_image_url
                        except Exception as e:
                            logger.error(f"下载 opening_image 失败: {e}", exc_info=True)
                            failed_count += 1
                            return {"record_id": record_id, "success": False, "error": f"下载首帧图片失败: {str(e)}"}

                    # 调用分镜生成服务
                    scene_desc = fields.get("scene_description", "宠物吃播")
                    # 确保 segment_count 是整数
                    segment_count = fields.get("segment_count", 7)
                    if isinstance(segment_count, str):
                        segment_count = int(segment_count) if segment_count.isdigit() else 7
                    elif not isinstance(segment_count, int):
                        segment_count = 7
                    # 限制范围在 3-8
                    segment_count = max(3, min(8, segment_count))

                    # 获取分镜服务实例并在线程池中运行同步方法
                    storyboard_service = get_storyboard_service()
                    if not storyboard_service:
                        failed_count += 1
                        return {"record_id": record_id, "success": False, "error": "分镜服务不可用"}
                    
                    # 在线程池中运行同步方法
                    loop = asyncio.get_event_loop()
                    try:
                        storyboard = await loop.run_in_executor(
                            None,
                            lambda: storyboard_service.generate_storyboard(
                                opening_image_url=opening_image_url,
                                scene_description=scene_desc,
                                segment_count=segment_count
                            )
                        )
                    except Exception as gen_error:
                        logger.error(f"分镜生成失败 (record_id={record_id}): {gen_error}", exc_info=True)
                        failed_count += 1
                        return {
                            "record_id": record_id,
                            "success": False,
                            "error": f"分镜生成失败: {str(gen_error)}"
                        }

                    # 【V2 核心修复】优先写入数据库（数据库是唯一事实来源）
                    from paretoai.services.task_status_service import get_task_status_service
                    task_service = get_task_status_service()
                    
                    # 保存分镜到数据库和本地文件
                    save_success = task_service.save_storyboard(
                        project_id=project_id,
                        storyboards=storyboard,
                        storage_path=storage_path,
                        status="storyboard_ready"
                    )
                    
                    if save_success:
                        logger.info(f"✅ 分镜已保存到数据库: project_id={project_id}")
                    else:
                        logger.warning(f"⚠️ 分镜保存到数据库失败，尝试本地文件回退")
                    
                    # 保存分镜脚本到本地项目目录（作为缓存/备份）
                    try:
                        # 保存时包含 record_id 和 opening_image_url，以便后续同步时能匹配
                        storyboard_with_meta = {
                            "project_id": project_id,
                            "record_id": record_id,
                            "timestamp": datetime.now().isoformat(),
                            "opening_image_url": opening_image_url,  # 保存项目目录的路径
                            "scene_description": scene_desc,
                            "segment_count": segment_count,
                            "storyboards": storyboard
                        }
                        storyboard_file = project_dir / "storyboard.json"
                        with open(storyboard_file, "w", encoding="utf-8") as f:
                            json.dump(storyboard_with_meta, f, ensure_ascii=False, indent=2)
                        logger.info(f"✅ 分镜脚本已保存到本地: {storyboard_file}")
                        
                        # 更新本地 meta.json：状态、错误信息、更新时间
                        from paretoai.services.feishu_bitable import write_project_meta
                        write_project_meta(
                            project_id=project_id,
                            status="storyboard_ready",
                            error_message="",  # 清空错误信息
                            updated_at=None,  # 自动设为当前时间
                            record_id=record_id  # 保存 record_id 以便关联
                        )
                    except Exception as save_error:
                        logger.warning(f"保存分镜脚本到本地失败: {save_error}")
                        # 继续执行，不影响飞书回写
                    
                    # 回写到飞书（次要操作：通知，失败不阻断）
                    try:
                        from paretoai.services.feishu_bitable import feishu_date_now_ms
                        update_fields = {
                            "project_id": project_id,
                            "storyboard_json": json.dumps(storyboard),
                            "status": "storyboard_ready",
                            "updated_at": feishu_date_now_ms(),
                        }
                        
                        await service.update_record(
                            app_token,
                            actual_table_id,
                            record_id,
                            update_fields
                        )
                        logger.debug(f"✅ 飞书同步成功: record_id={record_id}")
                    except Exception as feishu_error:
                        logger.warning(f"⚠️ 飞书同步失败（不影响主流程）: {feishu_error}")

                    # 【任务队列】更新为成功
                    if job:
                        job_store.update_job(job.id, status="succeeded", message="分镜生成完成")

                    success_count += 1
                    return {"record_id": record_id, "success": True, "project_id": project_id}

                except Exception as e:
                    failed_count += 1
                    error_msg = str(e)

                    # 【任务队列】更新为失败
                    if job:
                        job_store.update_job(job.id, status="failed", error=error_msg)
                    
                    # 【V2 核心修复】优先更新数据库状态
                    if 'project_id' in locals() and project_id:
                        try:
                            from paretoai.services.task_status_service import get_task_status_service
                            task_service = get_task_status_service()
                            task_service.update_task_status(
                                project_id=project_id,
                                status="failed",
                                error_message=error_msg
                            )
                        except:
                            pass
                    
                    # 更新本地 meta.json：记录失败状态和错误信息
                    try:
                        from paretoai.services.feishu_bitable import write_project_meta
                        write_project_meta(
                            project_id=project_id if 'project_id' in locals() else "",
                            status="failed",
                            error_message=error_msg,
                            updated_at=None  # 自动设为当前时间
                        )
                    except:
                        pass
                    
                    # 回写到飞书（次要操作：通知）
                    try:
                        from paretoai.services.feishu_bitable import feishu_date_now_ms
                        await service.update_record(
                            app_token,
                            actual_table_id,
                            record_id,
                            {
                                "status": "failed",
                                "error_message": error_msg,
                                "updated_at": feishu_date_now_ms(),
                            }
                        )
                    except:
                        pass
                    return {"record_id": record_id, "success": False, "error": error_msg}

        # 并发执行
        tasks = [process_record(rid) for rid in req.record_ids]
        results = await asyncio.gather(*tasks)

        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-segments")
async def generate_segments(req: GenerateSegmentsRequest):
    """批量生成分段视频"""
    try:
        service = get_feishu_service(req.table_id)
        app_token = get_app_token(req.table_id)
        actual_table_id = _feishu_services[req.table_id]["table_id"]

        success_count = 0
        failed_count = 0
        results = []

        # 获取记录详情
        records = await service.get_all_records(app_token, actual_table_id)
        record_map = {r["record_id"]: r for r in records}

        # 获取任务队列存储
        job_store = get_api_job_store()

        # 并发控制
        semaphore = asyncio.Semaphore(req.concurrency)

        async def process_record(record_id: str):
            nonlocal success_count, failed_count
            job = None  # 任务队列 job

            async with semaphore:
                try:
                    # 【任务队列】创建任务记录
                    job = job_store.create_job(
                        table_id=req.table_id,
                        kind="generate_segment",
                        record_id=record_id,
                        segment_index=req.segment_index,
                        message=f"正在生成段{req.segment_index}视频..."
                    )
                    job_store.update_job(job.id, status="running")

                    record = record_map.get(record_id)
                    if not record:
                        if job:
                            job_store.update_job(job.id, status="failed", error="记录不存在")
                        failed_count += 1
                        return {"record_id": record_id, "success": False, "error": "记录不存在"}

                    fields = record.get("fields", {})
                    project_id = fields.get("project_id")

                    if not project_id:
                        failed_count += 1
                        return {"record_id": record_id, "success": False, "error": "缺少 project_id"}

                    # 【并发控制】获取项目锁，防止同一项目并发生成导致数据错乱
                    from paretoai.services.project_lock_service import get_project_lock_service
                    lock_service = get_project_lock_service()
                    
                    # 尝试获取锁（非阻塞，超时 0 秒）
                    success, error_msg = await lock_service.try_lock(
                        project_id=project_id,
                        operation=f"generate_segment_{req.segment_index}",
                        timeout=0  # 不等待，如果锁定则立即返回
                    )
                    
                    if not success:
                        failed_count += 1
                        return {
                            "record_id": record_id,
                            "success": False,
                            "error": f"项目正在处理中: {error_msg}"
                        }

                    # 【V2 核心修复】从数据库/本地文件读取 storyboard_json（严格模式：不回退到飞书）
                    from paretoai.services.task_status_service import get_task_status_service
                    from paretoai.services.project_path_service import get_project_path_service

                    task_service = get_task_status_service()
                    path_service = get_project_path_service()
                    project_storage_path = path_service.get_project_storage_path(project_id)

                    # 严格模式：只从数据库和本地文件读取，不回退到飞书
                    # 飞书的数据可能是用户编辑之前的旧数据，使用它会导致编辑功能失效
                    storyboards = task_service.get_storyboard_with_fallback(
                        project_id=project_id,
                        storage_path=project_storage_path
                        )

                    if not storyboards:
                        # 不再回退到飞书！直接报错，提示用户先生成分镜
                        failed_count += 1
                        return {
                            "record_id": record_id,
                            "success": False,
                            "error": f"分镜数据不存在（project_id={project_id}）。请先执行「生成分镜」操作，或执行数据迁移脚本将旧数据同步到数据库。"
                        }

                    # 验证分镜数据
                    if not isinstance(storyboards, list) or len(storyboards) == 0:
                        failed_count += 1
                        return {"record_id": record_id, "success": False, "error": "分镜数据无效或为空"}

                    if req.segment_index < 0 or req.segment_index >= len(storyboards):
                        failed_count += 1
                        return {"record_id": record_id, "success": False, "error": f"分镜索引超出范围 (索引: {req.segment_index}, 总数: {len(storyboards)})"}

                    segment_config = storyboards[req.segment_index]
                    if not isinstance(segment_config, dict):
                        failed_count += 1
                        return {"record_id": record_id, "success": False, "error": "分镜配置格式错误"}

                    # 获取输入帧
                    if req.segment_index == 0:
                        # 优先从项目目录读取 opening_image（V2 结构：从数据库获取路径）
                        from paretoai.services.project_path_service import get_project_path_service
                        path_service = get_project_path_service()
                        project_storage_path = path_service.get_project_storage_path(project_id)

                        if not project_storage_path:
                            failed_count += 1
                            return {"record_id": record_id, "success": False, "error": "项目不存在于数据库中"}

                        project_dir = Path(project_storage_path)
                        opening_image_path = project_dir / "opening_image.jpg"

                        # 使用统一的 URL 生成方法（V2 结构）
                        v2_opening_url = path_service.get_file_url(project_id, "opening_image.jpg")

                        # 如果项目目录中已有 opening_image，直接使用
                        if opening_image_path.exists():
                            first_frame_url = v2_opening_url
                            logger.info(f"✅ 使用项目目录中的 opening_image: {first_frame_url}")
                        else:
                            # 从飞书获取 opening_image_url
                            opening_image = fields.get("opening_image_url", "")
                            if isinstance(opening_image, list) and len(opening_image) > 0:
                                opening_image = opening_image[0].get("url", "")
                            elif isinstance(opening_image, dict):
                                opening_image = opening_image.get("url", "")

                            if not opening_image:
                                failed_count += 1
                                return {"record_id": record_id, "success": False, "error": "缺少首帧图片"}

                            # 下载到项目目录
                            logger.info(f"项目目录中没有 opening_image，开始从飞书下载: {opening_image[:100]}...")
                            try:
                                if "open.feishu.cn/open-apis/drive/v1/medias" in opening_image:
                                    # 飞书附件，使用 download_attachment
                                    import re
                                    match = re.search(r'/medias/([^/]+)/', opening_image)
                                    if match:
                                        file_token = match.group(1)
                                        await service.download_attachment(
                                            file_token,
                                            str(opening_image_path),
                                            original_url=opening_image
                                        )
                                        logger.info(f"✅ 已下载飞书附件到项目目录: {opening_image_path}")
                                    else:
                                        raise ValueError("无法从飞书 URL 中提取 file_token")
                                else:
                                    # 普通 HTTP URL，直接下载
                                    import httpx
                                    async with httpx.AsyncClient(timeout=30) as client:
                                        response = await client.get(opening_image)
                                        response.raise_for_status()
                                        with open(opening_image_path, "wb") as f:
                                            f.write(response.content)
                                        logger.info(f"✅ 已下载图片到项目目录: {opening_image_path}")
                            except Exception as e:
                                logger.error(f"下载首帧图片失败: {e}", exc_info=True)
                                failed_count += 1
                                return {"record_id": record_id, "success": False, "error": f"下载首帧图片失败: {str(e)}"}

                            # 使用 V2 格式的 URL
                            first_frame_url = v2_opening_url

                        previous_last_frame = None
                    else:
                        # 使用上一段的尾帧
                        first_frame_url = None
                        previous_last_frame = None
                        prev_segment_index = req.segment_index - 1

                        # 【V2 核心修复】优先从数据库获取上一段尾帧
                        task = task_service.get_task(project_id)
                        if task and task.segment_urls:
                            try:
                                segment_data = json.loads(task.segment_urls)
                                prev_seg = segment_data.get(f"segment_{prev_segment_index}", {})
                                previous_last_frame = prev_seg.get("last_frame_url")
                                if previous_last_frame:
                                    logger.info(f"✅ 从数据库获取上一段尾帧: {previous_last_frame}")
                            except json.JSONDecodeError:
                                logger.warning(f"⚠️ 解析 segment_urls 失败")

                        # 回退1：从分镜数据获取
                        if not previous_last_frame and storyboards and prev_segment_index < len(storyboards):
                            prev_storyboard = storyboards[prev_segment_index]
                            previous_last_frame = prev_storyboard.get("last_frame_url")
                            if previous_last_frame:
                                logger.info(f"✅ 从分镜数据获取上一段尾帧: {previous_last_frame}")

                        # 回退2：从本地文件系统查找（V2 结构）
                        if not previous_last_frame and project_storage_path:
                            frames_dir = Path(project_storage_path) / "frames"
                            last_frame_file = frames_dir / f"segment_{prev_segment_index}_last.jpg"

                            if last_frame_file.exists():
                                previous_last_frame = path_service.get_segment_frame_url(
                                    project_id, prev_segment_index, "last"
                                )
                                logger.info(f"✅ 从本地文件获取上一段尾帧: {previous_last_frame}")
                            else:
                                logger.warning(f"⚠️ 本地尾帧文件不存在: {last_frame_file}")
                                if frames_dir.exists():
                                    existing_files = list(frames_dir.glob("*.jpg"))
                                    logger.warning(f"   frames目录中的文件: {[f.name for f in existing_files]}")

                        # 【严格模式】不再从飞书回退获取尾帧
                        # 如果数据库、分镜数据、本地文件都没有，说明上一段没有正确生成
                        if not previous_last_frame:
                            failed_count += 1
                            error_msg = f"缺少上一段尾帧 (段{prev_segment_index})，请确保上一段已成功生成"
                            logger.error(f"❌ {error_msg} (record_id={record_id}, project_id={project_id}, segment_index={req.segment_index})")
                            return {"record_id": record_id, "success": False, "error": error_msg}

                    # 【状态更新】生成开始前设置 generating_segment_X 状态
                    try:
                        generating_status = f"generating_segment_{req.segment_index}"
                        task_service.update_task_status(
                            project_id=project_id,
                            status=generating_status,
                            progress=f"{req.segment_index}/7段生成中"
                        )
                        logger.info(f"✅ 状态已更新为: {generating_status}")
                    except Exception as status_error:
                        logger.warning(f"更新状态失败（不影响生成）: {status_error}")

                    # 调用视频生成服务
                    video_service = get_video_segment_service()
                    if not video_service:
                        failed_count += 1
                        return {"record_id": record_id, "success": False, "error": "视频服务不可用"}

                    result = await video_service.generate_video_segment(
                        segment_index=req.segment_index,
                        prompt=segment_config.get("prompt", ""),
                        first_frame_url=first_frame_url,
                        previous_last_frame=previous_last_frame,
                        duration_sec=segment_config.get("durationSec", 5),
                        project_id=project_id
                    )

                    # 【V2 核心修复】优先更新数据库 segment_urls（数据库是唯一事实来源）
                    task_service.update_segment_result(
                        project_id=project_id,
                        segment_index=req.segment_index,
                        video_url=result.get("video_url"),
                        first_frame_url=result.get("first_frame_url"),
                        last_frame_url=result.get("last_frame_url"),
                        status="completed"
                    )

                    # 从数据库重新获取 segment_urls（确保一致性）
                    task = task_service.get_task(project_id)
                    if task and task.segment_urls:
                        segments_data = json.loads(task.segment_urls)
                    else:
                        segments_data = {}
                        segments_data[f"segment_{req.segment_index}"] = {
                            "video_url": result["video_url"],
                            "last_frame_url": result["last_frame_url"]
                        }

                    # 判断是否所有段完成
                    segment_count = task.total_segments if task and task.total_segments else fields.get("segment_count", 7)
                    if isinstance(segment_count, str):
                        segment_count = int(segment_count) if segment_count.isdigit() else 7
                    elif not isinstance(segment_count, int):
                        segment_count = 7
                    all_complete = all(
                        segments_data.get(f"segment_{i}", {}).get("video_url")
                        for i in range(segment_count)
                    )

                    logger.warning(f"=== 段{req.segment_index}视频生成成功 ===")
                    logger.warning(f"video_url: {result.get('video_url', 'N/A')[:100]}...")
                    logger.warning(f"last_frame_url: {result.get('last_frame_url', 'N/A')[:100]}...")
                    logger.warning(f"segments_data 长度: {len(segments_data)}")
                    logger.warning(f"segment_count: {segment_count}, all_complete: {all_complete}")

                    # 回写到飞书
                    # 获取表格的字段定义，确认实际字段名（与 _auto_update_generated_videos 使用相同的逻辑）
                    try:
                        table_fields = await service.get_table_fields(app_token, actual_table_id)
                        field_name_map = {f.get("field_name"): f.get("field_id") for f in table_fields if f.get("field_name")}
                        # 创建 field_id 到 field_name 的反向映射（用于附件上传）
                        field_id_to_name = {f.get("field_id"): f.get("field_name") for f in table_fields if f.get("field_name") and f.get("field_id")}
                        # 获取附件类型的字段（关键修复！）
                        attachment_fields = service.get_attachment_fields(table_fields)
                        logger.info(f"表格字段定义: {len(table_fields)} 个字段")
                        logger.info(f"附件类型字段: {attachment_fields}")
                    except Exception as e:
                        logger.warning(f"⚠️ 获取字段定义失败: {e}，将使用记录中的字段")
                        table_fields = []
                        field_name_map = {}
                        attachment_fields = set()

                    # 获取记录的实际字段，只更新存在的字段（避免 FieldNameNotFound 错误）
                    existing_fields = set(fields.keys())
                    logger.warning(f"=== 记录 {record_id} 字段检测 ===")
                    logger.warning(f"存在的字段 ({len(existing_fields)}): {sorted(existing_fields)}")
                    logger.warning(f"附件字段: {attachment_fields}")
                    logger.warning(f"段索引: {req.segment_index}, 需要查找的字段: segment_{req.segment_index}_video_url")

                    # 准备附件上传（需要在检测字段类型之前）（V2 结构：从数据库获取路径）
                    attachment_updates = {}
                    from paretoai.services.project_path_service import get_project_path_service
                    path_service = get_project_path_service()
                    project_storage_path = path_service.get_project_storage_path(project_id)

                    if not project_storage_path:
                        logger.warning(f"项目 {project_id} 不存在于数据库中，无法上传视频")
                        failed_count += 1
                        return {"record_id": record_id, "success": False, "error": "项目不存在于数据库中"}

                    project_dir = Path(project_storage_path)
                    segments_dir = project_dir / "segments"
                    logger.warning(f"本地segments目录: {segments_dir}")

                    # 构建最终更新字段，只包含存在的字段
                    final_update_fields = {}

                    # 更新 segments_json（仅当表格有此字段时；当前多数表格使用 segment_N_video_url，无此字段）
                    segments_json_value = json.dumps(segments_data, ensure_ascii=False)
                    if "segments_json" in existing_fields:
                        final_update_fields["segments_json"] = segments_json_value
                    elif "segments_json" in field_name_map:
                        final_update_fields["segments_json"] = segments_json_value
                        logger.info(f"表格有 segments_json 字段，将更新")
                    else:
                        # 尝试大小写不敏感匹配
                        matched = False
                        for existing_field in existing_fields:
                            if existing_field.lower().replace(" ", "_") == "segments_json".lower():
                                final_update_fields[existing_field] = segments_json_value
                                logger.info(f"字段名匹配: segments_json -> {existing_field}")
                                matched = True
                                break
                        if not matched:
                            logger.debug("segments_json 字段不存在于表格，跳过（当前表格使用 segment_N_video_url）")

                    # 更新状态字段
                    # 【修复】段生成完成后，状态应该是 storyboard_ready（等待用户推进）
                    # 而不是 generating_segment_{N+1}（表示正在生成）
                    # generating_segment_X 状态只在用户开始生成时设置
                    status_value = "all_segments_ready" if all_complete else "storyboard_ready"
                    if "status" in existing_fields:
                        final_update_fields["status"] = status_value
                    elif "status" in field_name_map:
                        final_update_fields["status"] = status_value

                    # 更新错误信息字段
                    if "error_message" in existing_fields:
                        final_update_fields["error_message"] = ""
                    elif "error_message" in field_name_map:
                        final_update_fields["error_message"] = ""

                    # 同步 updated_at 到飞书（日期字段用毫秒时间戳）
                    if "updated_at" in existing_fields or "updated_at" in field_name_map:
                        from paretoai.services.feishu_bitable import feishu_date_now_ms
                        final_update_fields["updated_at"] = feishu_date_now_ms()

                    # 更新本地 meta.json：状态、错误信息、更新时间
                    try:
                        from paretoai.services.feishu_bitable import write_project_meta
                        write_project_meta(
                            project_id=project_id,
                            status=status_value,
                            error_message="",  # 清空错误信息
                            updated_at=None,  # 自动设为当前时间
                            record_id=record_id  # 保存 record_id 以便关联
                        )
                    except Exception as meta_error:
                        logger.warning(f"更新本地 meta.json 失败: {meta_error}")

                    # 尝试更新独立字段（使用与 _auto_update_generated_videos 相同的逻辑）
                    segment_index_str = str(req.segment_index)
                    possible_video_fields = [
                        f"segment_{segment_index_str}_video_url",  # 标准格式
                        f"segment_{segment_index_str}_video_url".upper(),  # 全大写
                        f"segment_{segment_index_str}_video_url".lower(),  # 全小写
                        f"segment_{segment_index_str}_video_url".replace("_", " "),  # 空格代替下划线
                    ]

                    possible_frame_fields = [
                        f"segment_{segment_index_str}_last_frame_url",
                        f"segment_{segment_index_str}_last_frame_url".upper(),
                        f"segment_{segment_index_str}_last_frame_url".lower(),
                        f"segment_{segment_index_str}_last_frame_url".replace("_", " "),
                    ]

                    # 查找匹配的字段名（大小写不敏感，支持下划线和空格）
                    video_url_field = None
                    for possible_field in possible_video_fields:
                        # 精确匹配
                        if possible_field in existing_fields:
                            video_url_field = possible_field
                            break
                        # 大小写不敏感匹配
                        for existing_field in existing_fields:
                            if existing_field.lower().replace(" ", "_") == possible_field.lower().replace(" ", "_"):
                                video_url_field = existing_field
                                break
                        if video_url_field:
                            break

                    # 如果找到匹配的字段，检查是否为附件类型
                    if video_url_field:
                        if video_url_field in attachment_fields:
                            # 附件类型字段：需要上传本地文件
                            local_video_path = segments_dir / f"segment_{req.segment_index}_segment.mp4"
                            if local_video_path.exists():
                                attachment_updates[video_url_field] = {
                                    "local_path": str(local_video_path),
                                    "file_name": f"segment_{req.segment_index}.mp4"
                                }
                                logger.warning(f"  - 检测到 {video_url_field} 是附件字段，准备上传: {local_video_path}")
                            else:
                                logger.warning(f"  - ⚠️ 本地视频文件不存在: {local_video_path}，无法上传附件")
                                # 回退到文本URL
                                final_update_fields[video_url_field] = result["video_url"]
                        else:
                            # 文本类型字段：直接更新 URL
                            final_update_fields[video_url_field] = result["video_url"]
                            logger.info(f"  - 找到字段 {video_url_field}（文本类型），将更新 segment_{segment_index_str}_video_url")
                    else:
                        # 检查表格字段定义中是否存在
                        standard_field_name = f"segment_{segment_index_str}_video_url"
                        if standard_field_name in field_name_map:
                            if standard_field_name in attachment_fields:
                                # 附件类型字段
                                local_video_path = segments_dir / f"segment_{req.segment_index}_segment.mp4"
                                if local_video_path.exists():
                                    attachment_updates[standard_field_name] = {
                                        "local_path": str(local_video_path),
                                        "file_name": f"segment_{req.segment_index}.mp4"
                                    }
                                    logger.warning(f"  - 检测到 {standard_field_name} 是附件字段，准备上传: {local_video_path}")
                                else:
                                    logger.warning(f"  - ⚠️ 本地视频文件不存在: {local_video_path}")
                                    final_update_fields[standard_field_name] = result["video_url"]
                            else:
                                final_update_fields[standard_field_name] = result["video_url"]
                                logger.warning(f"  - ✅ 字段在表格定义中存在，将更新 {standard_field_name}")
                        else:
                            logger.warning(f"  - ❌ 字段 {standard_field_name} 在表格中不存在，跳过更新")

                    # last_frame_url 只存储在本地 storyboard.json，不更新到飞书表格
                    # 根据设计文档，segment_N_last_frame_url 字段不应该存在于飞书表格中
                    if result.get("last_frame_url"):
                        logger.debug(f"  - last_frame_url 已保存到本地 storyboard.json，不更新到飞书表格")

                    logger.info(f"  - 实际更新的字段: {list(final_update_fields.keys())}")

                    try:
                        # 先处理附件上传（如果有）
                        if attachment_updates:
                            logger.warning(f"  - 开始上传 {len(attachment_updates)} 个附件")
                            for field_name, file_info in attachment_updates.items():
                                try:
                                    local_path = file_info["local_path"]
                                    file_name = file_info["file_name"]

                                    # 关键修复：飞书 API 需要 field_id 而不是 field_name
                                    field_id_for_upload = field_name_map.get(field_name, field_name)
                                    logger.warning(f"  - 上传附件: {field_name} (field_id={field_id_for_upload})")

                                    # 上传附件到飞书（使用 field_id）
                                    upload_result = await service.upload_attachment_to_record(
                                        app_token,
                                        actual_table_id,
                                        record_id,
                                        field_id_for_upload,  # 使用 field_id 而不是 field_name
                                        local_path,
                                        file_name
                                    )
                                    logger.warning(f"  - ✅ 附件上传成功: {field_name} -> {upload_result.get('file_token')}")
                                except Exception as upload_err:
                                    logger.error(f"  - ❌ 附件上传失败: {field_name}, error={upload_err}")
                                    # 附件上传失败不影响文本字段更新

                        # 再更新文本字段
                        if not final_update_fields:
                            logger.warning(f"⚠️ 没有可更新的文本字段，跳过更新")
                        else:
                            await service.update_record(app_token, actual_table_id, record_id, final_update_fields)
                            logger.warning(f"✅ 成功更新记录 {record_id} 的段{req.segment_index}视频信息")
                    except Exception as update_error:
                        # 即使更新失败，也不应该标记为失败（因为视频已经生成了）
                        logger.error(f"⚠️ 更新飞书记录失败，但视频已生成: {update_error}")
                        logger.error(f"   尝试更新的字段: {list(final_update_fields.keys())}")
                        # 不抛出异常，让任务标记为成功

                    # 【任务队列】更新为成功
                    if job:
                        job_store.update_job(job.id, status="succeeded", message=f"段{req.segment_index}生成完成")

                    success_count += 1
                    return {"record_id": record_id, "success": True}

                except Exception as e:
                    failed_count += 1
                    error_msg = str(e)
                    logger.error(f"❌ 生成段{req.segment_index}失败 (record_id={record_id}): {error_msg}", exc_info=True)

                    # 【任务队列】更新为失败
                    if job:
                        job_store.update_job(job.id, status="failed", error=error_msg)
                    
                    # 【关键修复】更新数据库状态：失败后回退到 storyboard_ready，允许用户重试
                    try:
                        task_service.update_task_status(
                            project_id=project_id if 'project_id' in locals() else "",
                            status="storyboard_ready",  # 回退到等待状态，而不是 failed
                            error_message=error_msg
                        )
                        logger.info(f"✅ 已回退数据库状态为 storyboard_ready (project_id={project_id})")
                    except Exception as db_error:
                        logger.warning(f"更新数据库状态失败: {db_error}")
                    
                    # 更新本地 meta.json：记录失败状态和错误信息
                    try:
                        from paretoai.services.feishu_bitable import write_project_meta
                        write_project_meta(
                            project_id=project_id if 'project_id' in locals() else "",
                            status="storyboard_ready",  # 与数据库保持一致
                            error_message=error_msg,
                            updated_at=None  # 自动设为当前时间
                        )
                    except Exception as meta_error:
                        logger.warning(f"更新本地 meta.json 失败: {meta_error}")
                    # 记录错误到飞书（含 updated_at 同步）
                    try:
                        from paretoai.services.feishu_bitable import feishu_date_now_ms
                        await service.update_record(
                            app_token,
                            actual_table_id,
                            record_id,
                            {
                                "status": "storyboard_ready",  # 与数据库保持一致
                                "error_message": error_msg,
                                "updated_at": feishu_date_now_ms(),
                            }
                        )
                    except Exception as update_err:
                        logger.error(f"⚠️ 更新失败状态时出错: {update_err}")
                    return {"record_id": record_id, "success": False, "error": error_msg}

                finally:
                        # 【并发控制】释放项目锁
                        await lock_service.release_lock(project_id)
                        logger.debug(f"🔓 已释放项目锁: {project_id}")

        # 并发执行
        tasks = [process_record(rid) for rid in req.record_ids]
        results = await asyncio.gather(*tasks)

        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/merge-videos")
async def merge_videos(req: MergeVideosRequest):
    """批量合并视频"""
    try:
        service = get_feishu_service(req.table_id)
        app_token = get_app_token(req.table_id)
        actual_table_id = _feishu_services[req.table_id]["table_id"]

        success_count = 0
        failed_count = 0
        results = []

        # 获取记录详情
        records = await service.get_all_records(app_token, actual_table_id)
        record_map = {r["record_id"]: r for r in records}

        for record_id in req.record_ids:
            try:
                record = record_map.get(record_id)
                if not record:
                    failed_count += 1
                    results.append({"record_id": record_id, "success": False, "error": "记录不存在"})
                    continue

                fields = record.get("fields", {})
                project_id = fields.get("project_id")
                segment_count = fields.get("segment_count", 7)
                if isinstance(segment_count, str):
                    segment_count = int(segment_count) if segment_count.isdigit() else 7
                elif not isinstance(segment_count, int):
                    segment_count = 7

                # 收集所有段的视频 URL
                segment_urls = []
                segments_json = fields.get("segments_json", "{}")
                if isinstance(segments_json, str):
                    segments_data = json.loads(segments_json) if segments_json else {}
                else:
                    segments_data = segments_json

                for i in range(segment_count):
                    url = fields.get(f"segment_{i}_video_url") or segments_data.get(f"segment_{i}", {}).get("video_url")
                    if url:
                        segment_urls.append(url)

                if len(segment_urls) != segment_count:
                    failed_count += 1
                    results.append({"record_id": record_id, "success": False, "error": "分段视频不完整"})
                    continue

                # 调用合并服务
                video_service = get_video_segment_service()
                if not video_service:
                    failed_count += 1
                    results.append({"record_id": record_id, "success": False, "error": "视频服务不可用"})
                    continue
                
                merge_result = await video_service.merge_videos(segment_urls, project_id=project_id)
                final_url = merge_result.get("final_video_url")

                # 更新本地 meta.json：状态、错误信息、更新时间
                try:
                    from paretoai.services.feishu_bitable import write_project_meta
                    write_project_meta(
                        project_id=project_id,
                        status="completed",
                        error_message="",  # 清空错误信息
                        updated_at=None,  # 自动设为当前时间
                        record_id=record_id  # 保存 record_id 以便关联
                    )
                except Exception as meta_error:
                    logger.warning(f"更新本地 meta.json 失败: {meta_error}")

                # 回写到飞书（含 updated_at 同步）
                from paretoai.services.feishu_bitable import feishu_date_now_ms
                await service.update_record(
                    app_token,
                    actual_table_id,
                    record_id,
                    {
                        "final_video_url": final_url,
                        "status": "completed",
                        "updated_at": feishu_date_now_ms(),
                    }
                )

                success_count += 1
                results.append({"record_id": record_id, "success": True, "final_url": final_url})

            except Exception as e:
                failed_count += 1
                # 更新本地 meta.json：记录失败状态和错误信息
                try:
                    from paretoai.services.feishu_bitable import write_project_meta
                    write_project_meta(
                        project_id=project_id if 'project_id' in locals() else "",
                        status="failed",
                        error_message=str(e),
                        updated_at=None  # 自动设为当前时间
                    )
                except Exception as meta_error:
                    logger.warning(f"更新本地 meta.json 失败: {meta_error}")
                # 记录错误到飞书（含 updated_at 同步）
                try:
                    from paretoai.services.feishu_bitable import feishu_date_now_ms
                    await service.update_record(
                        app_token,
                        actual_table_id,
                        record_id,
                        {
                            "status": "failed",
                            "error_message": str(e),
                            "updated_at": feishu_date_now_ms(),
                        }
                    )
                except Exception as update_err:
                    logger.warning(f"更新失败状态时出错: {update_err}")
                results.append({"record_id": record_id, "success": False, "error": str(e)})

        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retry-task")
async def retry_task(req: RetryTaskRequest):
    """重试单个任务"""
    try:
        if req.action == "storyboard":
            result = await generate_storyboards(GenerateStoryboardsRequest(
                table_id=req.table_id,
                record_ids=[req.record_id],
                concurrency=1
            ))
        elif req.action == "segment":
            if req.segment_index is None:
                raise HTTPException(status_code=400, detail="segment_index 不能为空")
            result = await generate_segments(GenerateSegmentsRequest(
                table_id=req.table_id,
                record_ids=[req.record_id],
                segment_index=req.segment_index,
                concurrency=1
            ))
        elif req.action == "merge":
            result = await merge_videos(MergeVideosRequest(
                table_id=req.table_id,
                record_ids=[req.record_id]
            ))
        else:
            raise HTTPException(status_code=400, detail="无效的 action")

        return {"success": result["success_count"] > 0, "result": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    table_id: str = Form(...),
    record_id: str = Form(...)
):
    """上传首帧图片"""
    try:
        service = get_feishu_service(table_id)
        app_token = get_app_token(table_id)
        actual_table_id = _feishu_services[table_id]["table_id"]

        # 验证文件类型
        if file.content_type not in ["image/jpeg", "image/png", "image/webp"]:
            raise HTTPException(status_code=400, detail="不支持的图片格式")

        # 保存文件
        project_id = uuid.uuid4().hex[:12]
        save_dir = f"data/uploads/batch/{project_id}"
        os.makedirs(save_dir, exist_ok=True)

        ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
        save_path = f"{save_dir}/opening_image.{ext}"

        with open(save_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # 生成可访问的 URL（这里简化处理，实际应该用云存储）
        image_url = f"/data/uploads/batch/{project_id}/opening_image.{ext}"

        # 更新飞书记录（含 updated_at 同步）
        from paretoai.services.feishu_bitable import feishu_date_now_ms
        await service.update_record(
            app_token,
            actual_table_id,
            record_id,
            {
                "opening_image_url": image_url,
                "project_id": project_id,
                "status": "pending",
                "error_message": "",
                "updated_at": feishu_date_now_ms(),
            }
        )

        return {"success": True, "image_url": image_url, "project_id": project_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class UpdateRecordRequest(BaseModel):
    """更新记录请求"""
    table_id: str
    record_id: str
    fields: dict


@router.post("/update-record")
async def update_record(req: UpdateRecordRequest):
    """更新单个飞书记录的字段"""
    try:
        service = get_feishu_service(req.table_id)
        app_token = get_app_token(req.table_id)
        actual_table_id = _feishu_services[req.table_id]["table_id"]
        
        await service.update_record(
            app_token,
            actual_table_id,
            req.record_id,
            req.fields
        )
        
        logger.info(f"✅ 手动更新记录 {req.record_id} 成功: {list(req.fields.keys())}")
        return {"success": True, "message": "记录已更新"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 更新记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-videos")
async def sync_videos(table_id: str):
    """手动同步已生成的视频到飞书（用于修复或重新同步）"""
    try:
        service = get_feishu_service(table_id)
        app_token = get_app_token(table_id)
        actual_table_id = _feishu_services[table_id]["table_id"]
        
        logger.warning(f"开始手动同步视频到飞书: table_id={table_id}")  # 使用 WARNING 级别确保输出
        await _auto_update_generated_videos(service, app_token, actual_table_id)
        
        return {"success": True, "message": "视频同步完成"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"同步视频失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/progress")
async def get_progress(table_id: str):
    """获取批量任务进度"""
    try:
        result = await get_tasks(table_id)
        tasks = result["tasks"]

        total = len(tasks)
        completed = sum(1 for t in tasks if t["status"] == "completed")
        in_progress = sum(1 for t in tasks if "generating" in t["status"] or t["status"] == "merging")
        failed = sum(1 for t in tasks if t["status"] in ["failed", "image_failed"])

        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "failed": failed
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cascade-redo")
async def cascade_redo(req: CascadeRedoRequest):
    """
    级联重做功能

    从指定分段开始清空该段及所有后续分段，准备重新生成。
    旧视频文件会备份到 history/ 目录。
    """
    try:
        service = get_feishu_service(req.table_id)
        app_token = get_app_token(req.table_id)
        actual_table_id = _feishu_services[req.table_id]["table_id"]

        # 获取记录详情
        records = await service.get_all_records(app_token, actual_table_id)
        record = next((r for r in records if r.get("record_id") == req.record_id), None)

        if not record:
            raise HTTPException(status_code=404, detail="记录不存在")

        fields = record.get("fields", {})
        project_id = fields.get("project_id")

        if not project_id:
            raise HTTPException(status_code=400, detail="该记录没有关联的项目ID")

        # 【并发控制】获取项目锁，防止并发操作导致数据错乱
        from paretoai.services.project_lock_service import get_project_lock_service, ProjectLockError
        lock_service = get_project_lock_service()
        
        success, error_msg = await lock_service.try_lock(project_id, operation="cascade_redo")
        if not success:
            raise HTTPException(status_code=409, detail=error_msg)

        # 获取分段数
        segment_count = fields.get("segment_count", 7)
        if isinstance(segment_count, str):
            segment_count = int(segment_count) if segment_count.isdigit() else 7
        elif not isinstance(segment_count, int):
            segment_count = 7

        # 验证 from_segment_index
        if req.from_segment_index < 0 or req.from_segment_index >= segment_count:
            raise HTTPException(
                status_code=400,
                detail=f"无效的分段索引 (from_segment_index={req.from_segment_index}, 总段数={segment_count})"
            )

        # 项目目录路径（V2 结构：从数据库获取路径）
        from paretoai.services.project_path_service import get_project_path_service
        path_service = get_project_path_service()
        project_storage_path = path_service.get_project_storage_path(project_id)

        if not project_storage_path:
            raise HTTPException(status_code=404, detail="项目不存在于数据库中")

        project_dir = Path(project_storage_path)
        segments_dir = project_dir / "segments"
        frames_dir = project_dir / "frames"
        history_dir = project_dir / "history"

        # 创建 history 目录
        history_dir.mkdir(parents=True, exist_ok=True)

        cleared_segments = []
        backup_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 备份并清除从 from_segment_index 开始的所有分段
        for i in range(req.from_segment_index, segment_count):
            # 备份视频文件
            segment_video = segments_dir / f"segment_{i}_segment.mp4"
            if segment_video.exists():
                backup_name = f"segment_{i}_{timestamp}.mp4"
                backup_path = history_dir / backup_name
                try:
                    import shutil
                    shutil.move(str(segment_video), str(backup_path))
                    backup_paths.append(str(backup_path.relative_to(project_storage_path)))
                    logger.warning(f"✅ 已备份视频: {segment_video.name} -> {backup_name}")
                except Exception as e:
                    logger.warning(f"⚠️ 备份视频失败: {segment_video.name}, error={e}")

            # 备份首帧
            first_frame = frames_dir / f"segment_{i}_first.jpg"
            if first_frame.exists():
                backup_name = f"segment_{i}_first_{timestamp}.jpg"
                backup_path = history_dir / backup_name
                try:
                    import shutil
                    shutil.move(str(first_frame), str(backup_path))
                    logger.info(f"已备份首帧: {first_frame.name}")
                except Exception as e:
                    logger.warning(f"⚠️ 备份首帧失败: {first_frame.name}, error={e}")

            # 备份尾帧
            last_frame = frames_dir / f"segment_{i}_last.jpg"
            if last_frame.exists():
                backup_name = f"segment_{i}_last_{timestamp}.jpg"
                backup_path = history_dir / backup_name
                try:
                    import shutil
                    shutil.move(str(last_frame), str(backup_path))
                    logger.info(f"已备份尾帧: {last_frame.name}")
                except Exception as e:
                    logger.warning(f"⚠️ 备份尾帧失败: {last_frame.name}, error={e}")

            cleared_segments.append(i)

        # 备份并清除合并视频（如果有）
        final_video = project_dir / "final.mp4"
        if final_video.exists():
            backup_name = f"final_{timestamp}.mp4"
            backup_path = history_dir / backup_name
            try:
                import shutil
                shutil.move(str(final_video), str(backup_path))
                backup_paths.append(str(backup_path.relative_to(project_storage_path)))
                logger.warning(f"✅ 已备份合并视频: final.mp4 -> {backup_name}")
            except Exception as e:
                logger.warning(f"⚠️ 备份合并视频失败: error={e}")

        # 更新飞书记录：清空被重做分段的数据
        update_fields = {}

        # 注意：segments_json 字段在飞书表格中不存在，只存储在本地，不更新到飞书
        # 如果表格中有此字段（历史遗留），才更新它
        if "segments_json" in fields:
            # 解析现有的 segments_json
            segments_json = fields.get("segments_json", "{}")
            if isinstance(segments_json, str):
                segments_data = json.loads(segments_json) if segments_json else {}
            else:
                segments_data = segments_json if segments_json else {}

            # 清空从 from_segment_index 开始的分段数据
            for i in cleared_segments:
                seg_key = f"segment_{i}"
                if seg_key in segments_data:
                    del segments_data[seg_key]

            update_fields["segments_json"] = json.dumps(segments_data, ensure_ascii=False)

        # 清空独立字段（如果存在）
        for i in cleared_segments:
            # 清空视频 URL
            video_field = f"segment_{i}_video_url"
            if video_field in fields:
                update_fields[video_field] = ""

            # 清空尾帧 URL
            frame_field = f"segment_{i}_last_frame_url"
            if frame_field in fields:
                update_fields[frame_field] = ""

        # 清空合并视频 URL
        if "final_video_url" in fields and fields.get("final_video_url"):
            update_fields["final_video_url"] = ""

        # 更新状态
        # 【修复】级联重做后，状态应该是 storyboard_ready（等待用户推进）
        # 而不是 generating_segment_X（表示正在生成）
        update_fields["status"] = "storyboard_ready"

        # 清除错误信息
        update_fields["error_message"] = ""

        # 同步 updated_at 到飞书
        from paretoai.services.feishu_bitable import feishu_date_now_ms
        update_fields["updated_at"] = feishu_date_now_ms()

        # 如果需要重新生成分镜
        if req.regenerate_storyboard:
            # 清空分镜数据（让用户重新生成）
            storyboard_json = fields.get("storyboard_json", "")
            if storyboard_json:
                try:
                    if isinstance(storyboard_json, str):
                        storyboards = json.loads(storyboard_json)
                    else:
                        storyboards = storyboard_json

                    # 只清空从 from_segment_index 开始的分镜
                    if isinstance(storyboards, list) and len(storyboards) > req.from_segment_index:
                        # 保留前面的分镜，清空后面的
                        storyboards = storyboards[:req.from_segment_index]
                        update_fields["storyboard_json"] = json.dumps(storyboards, ensure_ascii=False)
                        logger.warning(f"✅ 已清空从段{req.from_segment_index}开始的分镜")
                except Exception as e:
                    logger.warning(f"⚠️ 清空分镜失败: {e}")

        # 更新飞书记录
        try:
            await service.update_record(app_token, actual_table_id, req.record_id, update_fields)
            logger.warning(f"✅ 已更新飞书记录: record_id={req.record_id}, 清空了分段 {cleared_segments}")
        except Exception as e:
            logger.error(f"❌ 更新飞书记录失败: {e}")
            raise HTTPException(status_code=500, detail=f"更新飞书记录失败: {str(e)}")

        # 【并发控制】释放项目锁
        await lock_service.release_lock(project_id)
        
        return {
            "success": True,
            "cleared_segments": cleared_segments,
            "backup_paths": backup_paths,
            "new_status": update_fields.get("status"),
            "regenerate_storyboard": req.regenerate_storyboard
        }

    except HTTPException:
        # 释放锁（如果已获取）
        if 'project_id' in locals() and project_id and 'lock_service' in locals():
            await lock_service.release_lock(project_id)
        raise
    except Exception as e:
        # 释放锁（如果已获取）
        if 'project_id' in locals() and project_id and 'lock_service' in locals():
            await lock_service.release_lock(project_id)
        logger.error(f"级联重做失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _construct_full_prompt(segment: dict) -> str:
    """构建完整的视频生成提示词（包含 Veo 模型一致性约束和负向约束）"""
    crucial = segment.get('crucial', '')
    action = segment.get('action', '')
    sound = segment.get('sound', '')
    negative_constraint = segment.get('negative_constraint', '')

    # 添加 Veo 模型的一致性约束（专家建议，通用版本，不限定猫咪颜色）
    veo_consistency_constraint = (
        "STAY CONSISTENT: The warm, bright studio lighting must remain unchanging throughout the entire video, "
        "do not shift to cold or dark tones. The pet's identity, fur color (as shown in the opening image), and facial structure "
        "must be perfectly stable, with no morphing or darkening over time. High fidelity preservation of the initial state."
    )

    # 构建基础 prompt
    prompt_parts = [
        f"[关键] {crucial}",
        f"[动作] {action}",
        f"[音效] {sound}",
    ]

    # 如果有负向约束，添加到 prompt 中
    if negative_constraint:
        prompt_parts.append(f"[禁止] {negative_constraint}")

    prompt_parts.append(f"[一致性约束] {veo_consistency_constraint}")

    return "\n".join(prompt_parts)


@router.post("/edit-and-regenerate")
async def edit_and_regenerate(req: EditAndRegenerateRequest):
    """
    编辑提示词并重新生成（V2 结构：从数据库获取路径）

    1. 读取本地 storyboard.json（数据源）
    2. 更新指定段的字段
    3. 重新构建 prompt
    4. 保存到本地文件（数据源）
    5. 验证保存成功
    6. 调用 LLM/视频 API 重新生成视频
    7. 回写飞书（可选，不阻断流程）
    """
    print(f"[edit-and-regenerate] 收到请求: project_id={req.project_id}, record_id={req.record_id}, segment_index={req.segment_index}", flush=True)
    
    # 【任务队列】创建任务记录
    job_store = get_api_job_store()
    job = job_store.create_job(
        table_id=req.table_id,
        kind="edit_and_regenerate",
        record_id=req.record_id,
        project_id=req.project_id,
        segment_index=req.segment_index,
        message=f"正在编辑并重新生成段{req.segment_index}..."
    )
    job_store.update_job(job.id, status="running")
    
    try:
        # 【并发控制】获取项目锁，防止并发操作导致数据错乱
        from paretoai.services.project_lock_service import get_project_lock_service, ProjectLockError
        lock_service = get_project_lock_service()
        
        success, error_msg = await lock_service.try_lock(req.project_id, operation="edit_regenerate")
        if not success:
            raise HTTPException(status_code=409, detail=error_msg)
        
        # 1. 读取本地 storyboard.json（V2 结构：从数据库获取路径）
        from paretoai.services.project_path_service import get_project_path_service
        path_service = get_project_path_service()
        project_storage_path = path_service.get_project_storage_path(req.project_id)

        if not project_storage_path:
            await lock_service.release_lock(req.project_id)
            raise HTTPException(status_code=404, detail=f"项目 {req.project_id} 不存在于数据库中")

        project_dir = Path(project_storage_path)
        storyboard_path = project_dir / "storyboard.json"

        if not storyboard_path.exists():
            raise HTTPException(status_code=404, detail=f"storyboard.json 不存在: {storyboard_path}")
        
        # 读取 storyboard 数据
        with open(storyboard_path, "r", encoding="utf-8") as f:
            storyboard_data = json.load(f)
        
        storyboards = storyboard_data.get("storyboards", [])
        
        # 验证 segment_index
        if req.segment_index < 0 or req.segment_index >= len(storyboards):
            raise HTTPException(
                status_code=400,
                detail=f"无效的分段索引 (segment_index={req.segment_index}, 总段数={len(storyboards)})"
            )
        
        # 2. 更新指定段的字段
        segment = storyboards[req.segment_index]
        segment["crucial"] = req.crucial
        segment["action"] = req.action
        segment["sound"] = req.sound
        segment["negative_constraint"] = req.negative_constraint
        
        # 更新中文字段（如果提供）
        if req.crucial_zh:
            segment["crucial_zh"] = req.crucial_zh
        if req.action_zh:
            segment["action_zh"] = req.action_zh
        if req.sound_zh:
            segment["sound_zh"] = req.sound_zh
        if req.negative_constraint_zh:
            segment["negative_constraint_zh"] = req.negative_constraint_zh
        
        # 3. 重新构建 prompt
        new_prompt = _construct_full_prompt(segment)
        segment["prompt"] = new_prompt
        
        # 4. 【V2 核心修复】优先保存到数据库（数据库是唯一事实来源）
        from paretoai.services.task_status_service import get_task_status_service
        task_service = get_task_status_service()
        
        storyboard_data["storyboards"] = storyboards
        storyboard_data["timestamp"] = datetime.now().isoformat()
        
        # 保存到数据库
        db_save_success = task_service.save_storyboard(
            project_id=req.project_id,
            storyboards=storyboards,
            storage_path=project_storage_path,
            status="editing"  # 标记为编辑中状态
        )
        
        if db_save_success:
            logger.info(f"✅ 分镜已保存到数据库: project_id={req.project_id}")
        else:
            logger.warning(f"⚠️ 分镜保存到数据库失败")
        
        # 同时保存到本地文件（作为缓存/备份）
        # 确保目录存在
        project_dir.mkdir(parents=True, exist_ok=True)
        
        # 写入文件并强制刷新
        with open(storyboard_path, "w", encoding="utf-8") as f:
            json.dump(storyboard_data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())  # 强制刷新到磁盘
        
        # 5. 验证保存成功
        with open(storyboard_path, "r", encoding="utf-8") as f:
            verify_data = json.load(f)
        verify_segment = verify_data.get("storyboards", [])[req.segment_index]
        if verify_segment.get("prompt") != new_prompt:
            logger.error(f"⚠️ 验证失败：保存的 prompt 与预期不符")
            raise HTTPException(status_code=500, detail="保存验证失败")
        
        logger.warning(f"✅ 已更新段{req.segment_index}的提示词并保存到本地和数据库: {storyboard_path}")
        print(f"[edit-and-regenerate] ✅ 步骤1-5完成，prompt 已保存。即将调用视频生成服务（LLM/API）重新生成段{req.segment_index}...", flush=True)
        
        # 6. 调用视频生成服务（重新生成视频）
        try:
            video_service = get_video_segment_service()
            if not video_service:
                print("[edit-and-regenerate] ❌ 视频服务不可用 (get_video_segment_service 返回 None)", flush=True)
                raise HTTPException(status_code=500, detail="视频服务不可用")
            mock_mode = getattr(video_service, "mock_mode", None)
            has_key = bool(getattr(video_service, "api_key", None))
            logger.warning(f"[edit-and-regenerate] 视频服务: mock_mode={mock_mode}, api_key={'***' if has_key else 'NOT SET'}")
            print(f"[edit-and-regenerate] 视频服务: mock_mode={mock_mode}, has_api_key={has_key}", flush=True)
            
            # 获取输入帧
            first_frame_url = None
            previous_last_frame = None
            
            if req.segment_index == 0:
                # 段0：使用 opening_image
                first_frame_url = storyboard_data.get("opening_image_url")
                if not first_frame_url:
                    # 尝试从项目目录读取（V2 结构，使用统一的 URL 生成方法）
                    opening_image_path = project_dir / "opening_image.jpg"
                    if opening_image_path.exists():
                        first_frame_url = path_service.get_file_url(req.project_id, "opening_image.jpg")
                    else:
                        raise HTTPException(status_code=400, detail="缺少首帧图片")
            else:
                # 其他段：使用上一段的尾帧
                prev_segment = storyboards[req.segment_index - 1]
                previous_last_frame = prev_segment.get("last_frame_url")
                
                # 如果从 storyboard 找不到，尝试从本地项目目录读取（V2 结构，使用统一的 URL 生成方法）
                if not previous_last_frame:
                    prev_segment_index = req.segment_index - 1
                    frames_dir = project_dir / "frames"
                    last_frame_file = frames_dir / f"segment_{prev_segment_index}_last.jpg"
                    if last_frame_file.exists():
                        previous_last_frame = path_service.get_segment_frame_url(
                            req.project_id, prev_segment_index, "last"
                        )
                
                if not previous_last_frame:
                    raise HTTPException(
                        status_code=400,
                        detail=f"缺少上一段尾帧 (段{req.segment_index - 1})，请确保上一段已成功生成"
                    )
            
            # 【归档旧数据】重新生成前先归档旧视频和帧
            try:
                from paretoai.services.archive_service import get_archive_service
                archive_service = get_archive_service()
                
                # 获取项目存储路径
                from paretoai.services.project_path_service import get_project_path_service
                path_service = get_project_path_service()
                project_storage_path = path_service.get_project_storage_path(req.project_id)
                
                if project_storage_path:
                    archive_service.archive_and_prepare_for_regenerate(
                        project_id=req.project_id,
                        segment_index=req.segment_index,
                        project_storage_path=project_storage_path,
                        current_segment_data=segment
                    )
                    logger.info(f"✅ 已归档段{req.segment_index}的旧数据")
                else:
                    logger.warning(f"⚠️ 无法获取项目存储路径，跳过归档")
            except Exception as archive_error:
                logger.warning(f"⚠️ 归档失败（不影响生成）: {archive_error}")
            
            # 【状态更新】生成开始前设置 generating_segment_X 状态
            try:
                from paretoai.services.task_status_service import get_task_status_service
                task_service = get_task_status_service()
                generating_status = f"generating_segment_{req.segment_index}"
                task_service.update_task_status(
                    project_id=req.project_id,
                    status=generating_status,
                    progress=f"{req.segment_index}/7段生成中"
                )
                logger.info(f"✅ 状态已更新为: {generating_status}")
            except Exception as status_error:
                logger.warning(f"更新状态失败（不影响生成）: {status_error}")

            # 调用视频生成服务（真正请求 LLM/视频 API）
            logger.warning(f"🎬 [edit-and-regenerate] 开始调用 LLM/视频 API 重新生成段{req.segment_index}...")
            print(f"[edit-and-regenerate] 🎬 调用 generate_video_segment: segment={req.segment_index}, first_frame={bool(first_frame_url)}, prev_last_frame={bool(previous_last_frame)}, prompt 前120字={repr(new_prompt[:120])}...", flush=True)
            result = await video_service.generate_video_segment(
                segment_index=req.segment_index,
                prompt=new_prompt,  # 使用新构建的 prompt
                first_frame_url=first_frame_url,
                previous_last_frame=previous_last_frame,
                duration_sec=segment.get("durationSec", segment.get("duration_sec", 8)),
                project_id=req.project_id,
                segment_type=segment.get("segment_type")
            )
            
            video_url = result.get("video_url", "")
            first_frame_url_result = result.get("first_frame_url", "")
            last_frame_url_result = result.get("last_frame_url", "")
            
            logger.warning(f"✅ [edit-and-regenerate] 段{req.segment_index}视频重新生成成功: {video_url[:100] if video_url else 'N/A'}...")
            print(f"[edit-and-regenerate] ✅ 视频生成成功 video_url={video_url[:80] if video_url else 'N/A'}...", flush=True)
            
            # ========================================================================
            # 【架构原则】数据库是唯一事实来源，必须第一时间更新
            # 写入顺序：1. 数据库 → 2. 本地文件（备份）→ 3. 飞书（同步）
            # ========================================================================
            
            # 【第一落点】更新数据库 segment_urls
            try:
                task_service.update_segment_result(
                    project_id=req.project_id,
                    segment_index=req.segment_index,
                    video_url=video_url,
                    first_frame_url=first_frame_url_result,
                    last_frame_url=last_frame_url_result,
                    status="completed"
                )
                logger.warning(f"✅ [edit-and-regenerate] 【第一落点】已更新数据库 segment_urls")
            except Exception as seg_err:
                logger.error(f"❌ [edit-and-regenerate] 更新数据库失败: {seg_err}")
                # 数据库更新失败是严重错误，抛出异常
                raise HTTPException(status_code=500, detail=f"数据库更新失败: {str(seg_err)}")
            
            # 【第二步】更新本地 storyboard.json（作为备份）
            try:
                segment["video_url"] = video_url
                segment["first_frame_url"] = first_frame_url_result
                segment["last_frame_url"] = last_frame_url_result
                segment["status"] = "completed"
                
                storyboard_data["storyboards"] = storyboards
                storyboard_data["timestamp"] = datetime.now().isoformat()
                
                with open(storyboard_path, "w", encoding="utf-8") as f:
                    json.dump(storyboard_data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                logger.info(f"✅ [edit-and-regenerate] 【备份】已更新本地 storyboard.json")
            except Exception as file_err:
                logger.warning(f"⚠️ [edit-and-regenerate] 更新本地文件失败（不影响流程）: {file_err}")
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ [edit-and-regenerate] 重新生成视频失败: {e}", exc_info=True)
            print(f"[edit-and-regenerate] ❌ 视频生成异常: {type(e).__name__}: {e}", flush=True)
            # 标记状态为失败并回写 storyboard，再向上抛出
            segment["status"] = "failed"
            storyboard_data["storyboards"] = storyboards
            with open(storyboard_path, "w", encoding="utf-8") as f:
                json.dump(storyboard_data, f, ensure_ascii=False, indent=2)
            raise HTTPException(status_code=500, detail=f"视频生成失败: {str(e)}")
        
        # 7. 回写飞书（可选，不阻断流程）
        try:
            service = get_feishu_service(req.table_id)
            app_token = get_app_token(req.table_id)
            actual_table_id = _feishu_services[req.table_id]["table_id"]
            
            # 获取记录详情以更新字段
            records = await service.get_all_records(app_token, actual_table_id)
            record = next((r for r in records if r.get("record_id") == req.record_id), None)
            if record:
                fields = record.get("fields", {})
                
                # 更新 segments_json
                segments_json = fields.get("segments_json", "{}")
                if isinstance(segments_json, str):
                    segments_data = json.loads(segments_json) if segments_json else {}
                else:
                    segments_data = segments_json if segments_json else {}
                
                segments_data[f"segment_{req.segment_index}"] = {
                    "video_url": segment.get("video_url", ""),
                    "last_frame_url": segment.get("last_frame_url", ""),
                    "status": segment.get("status", "completed")
                }
                
                # 获取表格字段定义
                try:
                    table_fields = await service.get_table_fields(app_token, actual_table_id)
                    field_name_map = {f.get("field_name"): f.get("field_id") for f in table_fields if f.get("field_name")}
                    existing_fields = set(fields.keys())
                except Exception:
                    field_name_map = {}
                    existing_fields = set(fields.keys())
                
                # 构建更新字段
                # 注意：segments_json 字段在飞书表格中不存在，只存储在本地，不更新到飞书
                from paretoai.services.feishu_bitable import feishu_date_now_ms
                update_fields = {
                    "storyboard_json": json.dumps(storyboards, ensure_ascii=False),
                    # segments_json 字段在飞书表格中不存在，不更新到飞书
                    "updated_at": feishu_date_now_ms(),
                }
                
                # 更新独立字段（如果存在）
                # 注意：segment_N_last_frame_url 只存储在本地 storyboard.json，不更新到飞书表格
                segment_index_str = str(req.segment_index)
                video_field = f"segment_{segment_index_str}_video_url"
                
                if video_field in existing_fields or video_field in field_name_map:
                    update_fields[video_field] = segment.get("video_url", "")
                # last_frame_url 只存储在本地，不更新到飞书表格
                
                # 更新状态
                if "status" in existing_fields or "status" in field_name_map:
                    # 检查是否所有段都完成
                    segment_count = fields.get("segment_count", 7)
                    if isinstance(segment_count, str):
                        segment_count = int(segment_count) if segment_count.isdigit() else 7
                    elif not isinstance(segment_count, int):
                        segment_count = 7
                    
                    all_complete = all(
                        segments_data.get(f"segment_{i}", {}).get("status") == "completed" or
                        segments_data.get(f"segment_{i}", {}).get("video_url")
                        for i in range(segment_count)
                    )
                    # 【修复】段生成完成后，状态应该是 storyboard_ready（等待用户推进）
                    update_fields["status"] = "all_segments_ready" if all_complete else "storyboard_ready"
                
                await service.update_record(
                    app_token,
                    actual_table_id,
                    req.record_id,
                    update_fields
                )
                logger.warning(f"✅ 已回写飞书记录: record_id={req.record_id}")
        except Exception as e:
            logger.warning(f"⚠️ 回写飞书失败（不影响流程）: {e}")
        
        print(f"[edit-and-regenerate] ✅ 全流程完成：已保存 prompt、已调用 LLM 重新生成视频、已回写。video_url={segment.get('video_url', '')[:80] or 'N/A'}...", flush=True)
        
        # 【并发控制】释放项目锁
        await lock_service.release_lock(req.project_id)
        
        # 【任务队列】更新为成功
        job_store.update_job(job.id, status="succeeded", message=f"段{req.segment_index}重新生成完成")
        
        return {
            "success": True,
            "message": "提示词已更新并重新生成视频",
            "prompt_sent": new_prompt,  # 返回实际发送给模型的 prompt，用于前端展示与排障
            "segment_index": req.segment_index,
            "video_url": segment.get("video_url"),
            "first_frame_url": segment.get("first_frame_url"),
            "last_frame_url": segment.get("last_frame_url")
        }
    
    except HTTPException as http_ex:
        # 【任务队列】更新为失败
        job_store.update_job(job.id, status="failed", error=str(http_ex.detail))
        # 释放锁（如果已获取）
        if 'lock_service' in locals():
            await lock_service.release_lock(req.project_id)
        raise
    except Exception as e:
        # 【任务队列】更新为失败
        job_store.update_job(job.id, status="failed", error=str(e))
        # 释放锁（如果已获取）
        if 'lock_service' in locals():
            await lock_service.release_lock(req.project_id)
        logger.error(f"编辑提示词失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch-save-prompts")
async def batch_save_prompts(req: BatchSavePromptsRequest):
    """
    批量保存提示词编辑（V2 结构：从数据库获取路径）

    1. 读取本地 storyboard.json（数据源）
    2. 更新指定段的字段
    3. 重新构建 prompt
    4. 保存到本地文件（数据源）
    5. 验证保存成功
    6. 可选：回写飞书（不阻断流程）

    返回成功和失败的数量
    """
    logger.info(f"[batch-save-prompts] 收到请求: {len(req.items)} 个项目")

    success_count = 0
    failed_count = 0
    results = []

    from paretoai.services.project_path_service import get_project_path_service
    path_service = get_project_path_service()

    for item in req.items:
        try:
            # 1. 读取本地 storyboard.json（V2 结构：从数据库获取路径）
            project_storage_path = path_service.get_project_storage_path(item.project_id)

            if not project_storage_path:
                raise Exception(f"项目 {item.project_id} 不存在于数据库中")

            project_dir = Path(project_storage_path)
            storyboard_path = project_dir / "storyboard.json"
            
            if not storyboard_path.exists():
                raise Exception(f"storyboard.json 不存在: {storyboard_path}")
            
            # 读取 storyboard 数据
            with open(storyboard_path, "r", encoding="utf-8") as f:
                storyboard_data = json.load(f)
            
            storyboards = storyboard_data.get("storyboards", [])
            
            # 验证 segment_index
            if item.segment_index < 0 or item.segment_index >= len(storyboards):
                raise Exception(f"无效的分段索引 (segment_index={item.segment_index}, 总段数={len(storyboards)})")
            
            # 2. 更新指定段的字段
            segment = storyboards[item.segment_index]
            segment["crucial"] = item.crucial
            segment["action"] = item.action
            segment["sound"] = item.sound
            segment["negative_constraint"] = item.negative_constraint
            
            # 更新中文字段（如果提供）
            if item.crucial_zh:
                segment["crucial_zh"] = item.crucial_zh
            if item.action_zh:
                segment["action_zh"] = item.action_zh
            if item.sound_zh:
                segment["sound_zh"] = item.sound_zh
            if item.negative_constraint_zh:
                segment["negative_constraint_zh"] = item.negative_constraint_zh
            
            # 3. 重新构建 prompt
            new_prompt = _construct_full_prompt(segment)
            segment["prompt"] = new_prompt
            
            # 4. 保存到本地文件（数据源）
            storyboard_data["storyboards"] = storyboards
            storyboard_data["timestamp"] = datetime.now().isoformat()
            
            # 确保目录存在
            project_dir.mkdir(parents=True, exist_ok=True)
            
            # 写入文件并强制刷新
            with open(storyboard_path, "w", encoding="utf-8") as f:
                json.dump(storyboard_data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())  # 强制刷新到磁盘
            
            # 5. 验证保存成功
            with open(storyboard_path, "r", encoding="utf-8") as f:
                verify_data = json.load(f)
            verify_segment = verify_data.get("storyboards", [])[item.segment_index]
            if verify_segment.get("prompt") != new_prompt:
                raise Exception("保存验证失败：保存的 prompt 与预期不符")
            
            logger.info(f"✅ 已更新段{item.segment_index}的提示词并保存到本地: {storyboard_path}")
            
            # 6. 可选：回写飞书（不阻断流程）
            try:
                service = get_feishu_service(req.table_id)
                app_token = get_app_token(req.table_id)
                actual_table_id = _feishu_services[req.table_id]["table_id"]
                
                # 更新飞书表格的 storyboard_json（可选，不阻断流程）
                await service.update_record(
                    app_token,
                    actual_table_id,
                    item.record_id,
                    {"storyboard_json": json.dumps(storyboards, ensure_ascii=False)}
                )
                logger.debug(f"✅ 已回写飞书: record_id={item.record_id}")
            except Exception as e:
                logger.warning(f"⚠️ 回写飞书失败（不影响流程）: {e}")
            
            success_count += 1
            results.append({
                "success": True,
                "record_id": item.record_id,
                "project_id": item.project_id,
                "segment_index": item.segment_index
            })
        
        except Exception as e:
            failed_count += 1
            error_msg = str(e)
            logger.error(f"❌ 保存提示词失败 (record_id={item.record_id}, project_id={item.project_id}, segment_index={item.segment_index}): {error_msg}")
            results.append({
                "success": False,
                "record_id": item.record_id,
                "project_id": item.project_id,
                "segment_index": item.segment_index,
                "error": error_msg
            })
    
    logger.info(f"[batch-save-prompts] 完成: 成功 {success_count}, 失败 {failed_count}")
    
    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "results": results
    }


@router.get("/jobs")
async def list_jobs(table_id: str, limit: int = 50):
    """
    获取 API 任务列表
    
    用于展示后台异步提交的 API 任务状态（例如 edit-and-regenerate）
    """
    try:
        job_store = get_api_job_store()
        jobs = job_store.list_jobs(table_id=table_id, limit=limit)
        return {
            "jobs": jobs,
            "total": len(jobs)
        }
    except Exception as e:
        logger.error(f"获取任务列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-to-drive")
async def sync_to_drive(req: SyncToDriveRequest):
    """
    批量同步项目到飞书云空间

    将本地生成的项目文件上传到飞书云空间文件夹，
    运营人员可直接在飞书预览视频，无需下载。

    请求参数：
    - table_id: 飞书表格 ID
    - project_ids: 项目 ID 列表
    - folder_token: 飞书云空间文件夹 Token
    - date_prefix: 日期前缀（可选，默认 YYYYMMDD）

    返回：
    - total: 总数
    - success: 成功数
    - failed: 失败数
    - details: 详细结果
    """
    try:
        logger.info(f"[sync-to-drive] 开始同步 {len(req.project_ids)} 个项目到云空间")

        # 获取飞书连接信息
        if req.table_id not in _feishu_services:
            raise HTTPException(
                status_code=400,
                detail="飞书未连接，请先连接飞书表格"
            )

        conn_info = _feishu_services[req.table_id]
        app_id = conn_info["app_id"]
        app_secret = conn_info["app_secret"]
        tenant_token = conn_info.get("tenant_access_token")

        # 创建 FeishuDriveService 实例，传入 user_oauth_store 以使用用户 access token
        user_oauth_store = get_feishu_user_oauth_store()
        drive_service = FeishuDriveService(
            app_id=app_id,
            app_secret=app_secret,
            tenant_access_token=tenant_token,
            table_id=req.table_id,
            user_oauth_store=user_oauth_store,
        )

        # V2 结构：从数据库获取每个项目的完整路径
        from paretoai.services.project_path_service import get_project_path_service
        from sqlmodel import select
        from paretoai.models import BatchTask
        from paretoai.db import engine

        path_service = get_project_path_service()

        # 获取项目路径映射
        project_paths = {}
        with Session(engine) as session:
            for project_id in req.project_ids:
                storage_path = path_service.get_project_storage_path(project_id)
                if storage_path:
                    project_paths[project_id] = storage_path
                else:
                    logger.warning(f"项目 {project_id} 不存在于数据库中")

        # 逐个同步项目（V2 结构：直接使用完整路径）
        results = {
            "total": len(req.project_ids),
            "success": 0,
            "failed": 0,
            "details": []
        }

        for project_id in req.project_ids:
            if project_id not in project_paths:
                results["failed"] += 1
                results["details"].append({
                    "project_id": project_id,
                    "success": False,
                    "error": "项目不存在于数据库中"
                })
                continue

            try:
                publish_date = req.project_publish_dates.get(project_id) if req.project_publish_dates else None
                project_path = project_paths[project_id]

                result = await drive_service.sync_project_to_drive(
                    parent_folder_token=req.folder_token,
                    project_id=project_id,
                    project_root_path=project_path,  # V2: 直接传递完整路径
                    publish_date=publish_date,
                    incremental=req.incremental
                )

                if result.get("folder_token"):
                    results["success"] += 1
                    results["details"].append({
                        "project_id": project_id,
                        "success": True,
                        "folder_url": result.get("folder_url"),
                        "folder_token": result.get("folder_token")
                    })
                else:
                    results["failed"] += 1
                    results["details"].append({
                        "project_id": project_id,
                        "success": False,
                        "error": "同步失败"
                    })

            except Exception as e:
                results["failed"] += 1
                results["details"].append({
                    "project_id": project_id,
                    "success": False,
                    "error": str(e)
                })
                logger.error(f"同步项目 {project_id} 失败: {e}")

        logger.info(f"[sync-to-drive] 同步完成: 成功 {results['success']}/{results['total']}, 失败 {results['failed']}")

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[sync-to-drive] 同步失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========== 飞书云空间 OAuth 用户授权 ==========

@router.get("/drive/oauth/status")
async def get_drive_oauth_status(table_id: str):
    """
    获取云空间用户授权状态

    返回当前 table_id 对应的用户 access token 是否有效
    """
    try:
        user_oauth_store = get_feishu_user_oauth_store()
        token = user_oauth_store.get_token(table_id)

        if not token:
            return {"authorized": False, "reason": "no_token"}

        # 检查 token 是否过期
        import time
        now = time.time()
        if now >= token.expires_at:
            return {"authorized": False, "reason": "expired"}

        return {"authorized": True, "expires_at": token.expires_at}

    except Exception as e:
        logger.error(f"[drive/oauth/status] 检查授权状态失败: {e}", exc_info=True)
        return {"authorized": False, "reason": "error"}


@router.get("/drive/oauth/start")
async def start_drive_oauth(table_id: str):
    """
    启动云空间用户授权流程

    直接重定向到飞书授权页面（支持前端一键授权按钮）
    """
    try:
        if table_id not in _feishu_services:
            raise HTTPException(status_code=400, detail="飞书未连接")

        conn_info = _feishu_services[table_id]
        app_id = conn_info["app_id"]

        # OAuth 配置
        # 注意：redirect_uri 需要在飞书开放平台配置
        # 这里使用本地回调地址
        redirect_uri = "http://localhost:8000/api/batch/drive/oauth/callback"

        # 构建飞书 OAuth 授权 URL
        # 文档: https://open.feishu.cn/document/server-docs/authentication-management/authentication-in-authentication-mode
        auth_url = (
            f"https://open.feishu.cn/open-apis/authen/v1/authorize"
            f"?app_id={app_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope=drive:drive"
            f"&state={table_id}"  # 使用 table_id 作为 state，回调时验证
        )

        # 直接重定向到飞书授权页面
        from fastapi.responses import RedirectResponse
        logger.info(f"[drive/oauth/start] 重定向到飞书授权页面: table_id={table_id}")
        return RedirectResponse(url=auth_url, status_code=302)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[drive/oauth/start] 启动授权失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drive/oauth/callback")
async def handle_drive_oauth_callback(
    code: str,
    state: str,  # state 就是 table_id
):
    """
    处理飞书 OAuth 回调

    飞书授权完成后会重定向到这个端点，携带授权码
    """
    try:
        table_id = state

        if table_id not in _feishu_services:
            raise HTTPException(status_code=400, detail="无效的 state 参数")

        conn_info = _feishu_services[table_id]
        app_id = conn_info["app_id"]
        app_secret = conn_info["app_secret"]

        # 获取 user_oauth_store
        user_oauth_store = get_feishu_user_oauth_store()

        # 用授权码换取 access_token
        redirect_uri = "http://localhost:8000/api/batch/drive/oauth/callback"
        token = await user_oauth_store.exchange_code_for_token(
            code=code,
            client_id=app_id,
            client_secret=app_secret,
            redirect_uri=redirect_uri,
        )

        # 保存 token
        user_oauth_store.set_token(table_id, token)

        logger.info(f"[drive/oauth/callback] 用户授权成功: table_id={table_id}, scope={token.scope}")

        # 返回简单的 HTML 页面，提示用户授权成功
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>授权成功</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: #1a1a1a;
                    color: #fff;
                }}
                .container {{
                    text-align: center;
                    padding: 40px;
                }}
                h1 {{ color: #10b981; }}
                p {{ color: #9ca3af; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>✅ 授权成功！</h1>
                <p>云空间用户授权已完成，现在可以使用同步到云空间功能了。</p>
                <p>您可以关闭此窗口返回批量处理工坊。</p>
            </div>
        </body>
        </html>
        """

        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html_content)

    except Exception as e:
        logger.error(f"[drive/oauth/callback] 处理回调失败: {e}", exc_info=True)
        from fastapi.responses import HTMLResponse
        error_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>授权失败</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: #1a1a1a;
                    color: #fff;
                }}
                .container {{
                    text-align: center;
                    padding: 40px;
                }}
                h1 {{ color: #ef4444; }}
                p {{ color: #9ca3af; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>❌ 授权失败</h1>
                <p>错误信息: {str(e)}</p>
                <p>请关闭此窗口重试。</p>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=error_html)


@router.post("/drive/oauth/submit-code")
async def submit_drive_oauth_code(
    code: str,
    state: str,  # state 就是 table_id
):
    """
    手动提交飞书授权码

    当自动跳转失败时，用户可以复制授权码手动提交
    """
    try:
        table_id = state

        if table_id not in _feishu_services:
            raise HTTPException(status_code=400, detail="无效的 state 参数")

        conn_info = _feishu_services[table_id]
        app_id = conn_info["app_id"]
        app_secret = conn_info["app_secret"]

        # 获取 user_oauth_store
        user_oauth_store = get_feishu_user_oauth_store()

        # 用授权码换取 access_token
        redirect_uri = "http://localhost:8000/api/batch/drive/oauth/callback"
        token = await user_oauth_store.exchange_code_for_token(
            code=code,
            client_id=app_id,
            client_secret=app_secret,
            redirect_uri=redirect_uri,
        )

        # 保存 token
        user_oauth_store.set_token(table_id, token)

        logger.info(f"[drive/oauth/submit-code] 用户授权成功: table_id={table_id}, scope={token.scope}")

        return {
            "success": True,
            "message": "授权成功！",
            "table_id": table_id,
            "scope": token.scope,
            "expires_at": token.expires_at
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[drive/oauth/submit-code] 提交授权码失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drive/oauth/submit-form")
async def drive_oauth_submit_form():
    """
    返回一个 HTML 表单页面，用于手动提交授权码
    """
    from fastapi.responses import HTMLResponse
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>手动提交飞书授权码</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                background: #1a1a1a;
                color: #fff;
            }
            .container {
                width: 100%;
                max-width: 500px;
                padding: 40px;
                background: #2a2a2a;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            }
            h1 {
                color: #10b981;
                margin-bottom: 10px;
                font-size: 24px;
            }
            .subtitle {
                color: #9ca3af;
                margin-bottom: 30px;
                font-size: 14px;
            }
            .form-group {
                margin-bottom: 20px;
            }
            label {
                display: block;
                margin-bottom: 8px;
                color: #d1d5db;
                font-size: 14px;
            }
            input, textarea {
                width: 100%;
                padding: 12px;
                background: #1a1a1a;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                color: #fff;
                font-size: 14px;
                box-sizing: border-box;
            }
            input:focus, textarea:focus {
                outline: none;
                border-color: #10b981;
            }
            textarea {
                min-height: 80px;
                font-family: monospace;
            }
            button {
                width: 100%;
                padding: 12px;
                background: #10b981;
                color: #fff;
                border: none;
                border-radius: 6px;
                font-size: 16px;
                font-weight: 500;
                cursor: pointer;
                transition: background 0.2s;
            }
            button:hover {
                background: #059669;
            }
            .result {
                margin-top: 20px;
                padding: 12px;
                border-radius: 6px;
                display: none;
            }
            .result.success {
                background: #10b98120;
                border: 1px solid #10b981;
            }
            .result.error {
                background: #ef444420;
                border: 1px solid #ef4444;
            }
            .hint {
                font-size: 12px;
                color: #6b7280;
                margin-top: 6px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>✍️ 手动提交飞书授权码</h1>
            <p class="subtitle">从飞书授权页面复制 code 和 state 填入下方</p>

            <form id="oauthForm">
                <div class="form-group">
                    <label for="code">授权码 (code)</label>
                    <textarea id="code" name="code" placeholder="粘贴飞书页面显示的 code 值" required></textarea>
                    <p class="hint">从飞书授权页面复制</p>
                </div>

                <div class="form-group">
                    <label for="state">状态 (state)</label>
                    <input type="text" id="state" name="state" placeholder="tblnj7Q3VrwLauKb" required>
                    <p class="hint">通常是 table_id，例如: tblnj7Q3VrwLauKb</p>
                </div>

                <button type="submit">提交授权</button>
            </form>

            <div id="result" class="result"></div>
        </div>

        <script>
            document.getElementById('oauthForm').addEventListener('submit', async (e) => {
                e.preventDefault();

                const code = document.getElementById('code').value.trim();
                const state = document.getElementById('state').value.trim();
                const resultDiv = document.getElementById('result');

                if (!code || !state) {
                    resultDiv.className = 'result error';
                    resultDiv.style.display = 'block';
                    resultDiv.textContent = '❌ 请填写所有字段';
                    return;
                }

                try {
                    const response = await fetch('/api/batch/drive/oauth/submit-code', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ code, state })
                    });

                    const data = await response.json();

                    if (data.success) {
                        resultDiv.className = 'result success';
                        resultDiv.style.display = 'block';
                        resultDiv.innerHTML = `
                            <strong>✅ 授权成功！</strong><br>
                            表格ID: ${data.table_id}<br>
                            权限范围: ${data.scope}<br>
                            过期时间: ${new Date(data.expires_at * 1000).toLocaleString()}<br><br>
                            <small>现在可以关闭此窗口，返回批量处理工坊使用"同步到云空间"功能了。</small>
                        `;
                    } else {
                        throw new Error(data.message || '授权失败');
                    }
                } catch (error) {
                    resultDiv.className = 'result error';
                    resultDiv.style.display = 'block';
                    resultDiv.textContent = '❌ ' + error.message;
                }
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# ============================================================================
# 历史记录归档 API
# ============================================================================

@router.get("/segment-history/{project_id}")
async def get_segment_history(
    project_id: str,
    segment_index: Optional[int] = None
):
    """
    获取项目的段视频历史记录
    
    Args:
        project_id: 项目ID
        segment_index: 段索引（可选，不指定则返回所有段的历史）
    
    Returns:
        历史记录列表
    """
    try:
        from paretoai.services.archive_service import get_archive_service
        archive_service = get_archive_service()
        
        history = archive_service.get_segment_history(project_id, segment_index)
        
        return {
            "success": True,
            "project_id": project_id,
            "segment_index": segment_index,
            "history": history
        }
    except Exception as e:
        logger.error(f"获取历史记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/archive-files/{project_id}")
async def list_archive_files(project_id: str):
    """
    列出项目的归档文件目录结构
    
    Args:
        project_id: 项目ID
    
    Returns:
        归档文件列表
    """
    try:
        from paretoai.services.project_path_service import get_project_path_service
        path_service = get_project_path_service()
        project_storage_path = path_service.get_project_storage_path(project_id)
        
        if not project_storage_path:
            return {
                "success": False,
                "message": "项目不存在或无存储路径"
            }
        
        from pathlib import Path
        archive_dir = Path(project_storage_path) / "archive"
        
        if not archive_dir.exists():
            return {
                "success": True,
                "project_id": project_id,
                "archives": [],
                "message": "暂无归档文件"
            }
        
        archives = []
        for segment_dir in sorted(archive_dir.iterdir()):
            if segment_dir.is_dir() and segment_dir.name.startswith("segment_"):
                segment_archives = []
                for timestamp_dir in sorted(segment_dir.iterdir(), reverse=True):
                    if timestamp_dir.is_dir():
                        files = [f.name for f in timestamp_dir.iterdir() if f.is_file()]
                        segment_archives.append({
                            "timestamp": timestamp_dir.name,
                            "files": files
                        })
                archives.append({
                    "segment": segment_dir.name,
                    "versions": segment_archives
                })
        
        return {
            "success": True,
            "project_id": project_id,
            "archives": archives
        }
    except Exception as e:
        logger.error(f"列出归档文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
