"""
飞书多维表格服务
提供飞书 Bitable API 的封装，支持连接、读取、写入和批量操作
"""
import os
import json
import asyncio
import aiohttp
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path
import logging

from paretoai.retry import retry_async, RetryConfigs

logger = logging.getLogger(__name__)


def feishu_date_now_ms() -> int:
    """返回当前时间毫秒时间戳，用于飞书 日期 字段（格式 2026/01/30 14:00 的底层存储）"""
    return int(datetime.now().timestamp() * 1000)


class FeishuBitableService:
    """飞书多维表格服务"""

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str, app_secret: str, tenant_access_token: Optional[str] = None):
        self.app_id = app_id
        self.app_secret = app_secret
        # 处理 tenant_access_token：如果提供了但没有 t- 前缀，自动添加
        if tenant_access_token:
            tenant_access_token = tenant_access_token.strip()
            if not tenant_access_token.startswith('t-'):
                # 如果用户提供的 token 没有 t- 前缀，自动添加
                tenant_access_token = f"t-{tenant_access_token}"
                logger.info("检测到 tenant_access_token 缺少 't-' 前缀，已自动添加")
        self._tenant_access_token: Optional[str] = tenant_access_token  # 如果提供了，直接使用
        self._token_expires_at: float = 0
        if tenant_access_token:
            # 如果直接提供了 token，设置一个很长的过期时间（实际应该由调用方管理）
            self._token_expires_at = datetime.now().timestamp() + 7200  # 2小时
            logger.info(f"使用提供的 tenant_access_token: {tenant_access_token[:30]}... (长度: {len(tenant_access_token)})")

    async def _get_tenant_access_token(self) -> str:
        """获取 tenant_access_token"""
        # 如果已经提供了 token，检查是否过期
        if self._tenant_access_token:
            if datetime.now().timestamp() < self._token_expires_at:
                logger.debug(f"使用缓存的 tenant_access_token: {self._tenant_access_token[:20]}...")
                return self._tenant_access_token
            else:
                logger.warning(f"提供的 tenant_access_token 已过期，尝试通过 App ID/Secret 获取新 token")
                # Token 过期，清除它，使用 App ID/Secret 获取新 token
                self._tenant_access_token = None
        
        # 如果没有提供 token 或 token 过期，需要通过 App ID/Secret 获取
        logger.info("通过 App ID/Secret 获取 tenant_access_token...")

        url = f"{self.BASE_URL}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()

                if data.get("code") != 0:
                    raise Exception(f"获取 token 失败: {data.get('msg')}")

                self._tenant_access_token = data["tenant_access_token"]
                # token 有效期 2 小时，提前 5 分钟刷新
                self._token_expires_at = datetime.now().timestamp() + data["expire"] - 300
                
                logger.info(f"成功获取 tenant_access_token: {self._tenant_access_token[:20]}... (长度: {len(self._tenant_access_token)})")

                return self._tenant_access_token

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        retry: int = 3
    ) -> Dict:
        """发送 API 请求"""
        token = await self._get_tenant_access_token()
        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        for attempt in range(retry):
            try:
                logger.debug(f"飞书 API 请求: {method} {url}, attempt={attempt+1}/{retry}")
                # 设置超时：连接超时 10 秒，总超时 30 秒
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.request(
                        method,
                        url,
                        params=params,
                        json=json_data,
                        headers=headers
                    ) as resp:
                        # 检查响应状态码
                        if resp.status >= 400:
                            # 尝试解析错误响应
                            content_type = resp.headers.get('Content-Type', '')
                            if 'application/json' in content_type:
                                try:
                                    error_data = await resp.json()
                                    error_msg = error_data.get('msg') or error_data.get('message') or error_data.get('error') or f"HTTP {resp.status}"
                                    error_code = error_data.get('code')
                                    # 打印完整的错误响应，帮助调试
                                    logger.error(f"飞书 API 错误: code={error_code}, msg={error_msg}, url={url}")
                                    logger.error(f"完整错误响应: {json.dumps(error_data, ensure_ascii=False, indent=2)}")
                                except:
                                    error_text = await resp.text()
                                    error_msg = f"HTTP {resp.status}: {error_text[:200]}"
                                    logger.error(f"飞书 API 错误（无法解析JSON）: {error_msg}, url={url}")
                                    logger.error(f"完整错误文本: {error_text}")
                            else:
                                error_text = await resp.text()
                                error_msg = f"HTTP {resp.status}: {error_text[:200]}"
                                logger.error(f"飞书 API 错误（非JSON响应）: {error_msg}, url={url}")
                            
                            # 特殊处理 404 错误
                            if resp.status == 404:
                                raise Exception(f"资源不存在 (404): {error_msg}。请检查 app_token 和 table_id 是否正确，以及应用是否有访问权限")
                            
                            # 特殊处理 token 无效错误（99991663），尝试清除缓存的 token 并重新获取
                            if resp.status == 400 and error_code == 99991663:
                                if self._tenant_access_token and attempt == 0:
                                    # 第一次尝试时，如果使用的是提供的 token，清除它并尝试通过 App ID/Secret 获取新 token
                                    logger.warning(f"提供的 tenant_access_token 无效，清除缓存并尝试通过 App ID/Secret 获取新 token")
                                    self._tenant_access_token = None
                                    self._token_expires_at = 0
                                    # 继续重试（会在下一次循环中重新获取 token）
                                    continue
                            
                            raise Exception(f"API 请求失败 ({resp.status}): {error_msg}")
                        
                        # 解析 JSON 响应
                        try:
                            data = await resp.json()
                        except Exception as e:
                            error_text = await resp.text()
                            raise Exception(f"响应解析失败: {str(e)}, 响应内容: {error_text[:200]}")

                        # 检查限流
                        if data.get("code") == 99991400:
                            wait_time = 2 ** attempt
                            logger.warning(f"飞书 API 限流，等待 {wait_time}s 后重试")
                            await asyncio.sleep(wait_time)
                            continue

                        if data.get("code") != 0:
                            error_msg = data.get('msg') or data.get('message') or '未知错误'
                            error_code = data.get('code')
                            # 打印完整的错误响应，帮助调试
                            logger.error(f"飞书 API 返回错误: code={error_code}, msg={error_msg}")
                            logger.error(f"完整错误响应: {json.dumps(data, ensure_ascii=False, indent=2)}")
                            raise Exception(f"API 请求失败: {error_msg}")

                        return data.get("data", {})
            except Exception as e:
                if attempt == retry - 1:
                    raise
                logger.warning(f"请求失败，重试中: {e}")
                await asyncio.sleep(1)

        raise Exception("请求失败，已达最大重试次数")

    async def get_table_info(self, app_token: str, table_id: str) -> Dict:
        """获取表格信息"""
        endpoint = f"/bitable/v1/apps/{app_token}/tables/{table_id}"
        logger.info(f"获取表格信息: app_token={app_token}, table_id={table_id}, endpoint={endpoint}")
        try:
            result = await self._request("GET", endpoint)
            logger.info(f"表格信息获取成功: {result.get('table', {}).get('name', '未知')}")
            return result
        except Exception as e:
            logger.error(f"获取表格信息失败: {e}")
            raise
    
    @retry_async(RetryConfigs.NETWORK)
    async def get_table_fields(self, app_token: str, table_id: str) -> List[Dict]:
        """获取表格的所有字段定义"""
        endpoint = f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
        logger.warning(f"获取表格字段定义: app_token={app_token}, table_id={table_id}")  # 使用 WARNING 级别确保输出
        try:
            result = await self._request("GET", endpoint)
            # 飞书API返回格式可能是 result.data.items 或 result.items
            fields = result.get("data", {}).get("items", []) or result.get("items", [])
            logger.warning(f"获取到 {len(fields)} 个字段定义")  # 使用 WARNING 级别确保输出
            if fields:
                field_names = [f.get("field_name", f.get("name", "")) for f in fields]
                logger.warning(f"字段名列表: {field_names}")  # 使用 WARNING 级别确保输出
            else:
                logger.warning(f"⚠️ 字段列表为空，API响应: {result}")  # 使用 WARNING 级别确保输出
            return fields
        except Exception as e:
            logger.warning(f"获取表格字段定义失败: {e}")  # 使用 WARNING 级别确保输出
            # 不抛出异常，返回空列表，让调用方继续处理
            return []

    def get_attachment_fields(self, fields: List[Dict]) -> set:
        """
        从字段定义列表中提取附件类型的字段名

        飞书字段类型: 17 = 附件
        """
        attachment_fields = set()
        for field in fields:
            field_name = field.get("field_name", "")
            field_type = field.get("type")
            # 飞书附件字段类型是 17
            if field_type == 17:
                attachment_fields.add(field_name)
                logger.info(f"检测到附件字段: {field_name}")
        return attachment_fields

    @retry_async(RetryConfigs.NETWORK)
    async def list_records(
        self,
        app_token: str,
        table_id: str,
        page_size: int = 100,
        page_token: Optional[str] = None,
        filter_str: Optional[str] = None
    ) -> Dict:
        """列出记录"""
        endpoint = f"/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        params = {
            "page_size": page_size,
            "view_id": ""  # 空字符串表示不使用特定视图
        }

        if page_token:
            params["page_token"] = page_token
        if filter_str:
            params["filter"] = filter_str

        return await self._request("GET", endpoint, params=params)

    @retry_async(RetryConfigs.NETWORK)
    async def get_all_records(
        self,
        app_token: str,
        table_id: str,
        filter_str: Optional[str] = None
    ) -> List[Dict]:
        """获取所有记录（自动分页）"""
        all_records = []
        page_token = None

        while True:
            data = await self.list_records(
                app_token, table_id,
                page_size=500,
                page_token=page_token,
                filter_str=filter_str
            )

            records = data.get("items", [])
            all_records.extend(records)

            if not data.get("has_more"):
                break

            page_token = data.get("page_token")

        return all_records

    @retry_async(RetryConfigs.NETWORK)
    async def update_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        fields: Dict
    ) -> Dict:
        """更新单条记录"""
        endpoint = f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
        logger.warning(f"=== 更新飞书记录 ===")  # 使用 WARNING 级别确保输出
        logger.warning(f"record_id: {record_id}, 字段数: {len(fields)}")
        logger.warning(f"更新字段: {list(fields.keys())}")
        # 打印字段值（前100个字符）
        for field_name, field_value in fields.items():
            if isinstance(field_value, str) and len(field_value) > 100:
                logger.warning(f"  {field_name}: {field_value[:100]}...")
            else:
                logger.warning(f"  {field_name}: {field_value}")
        try:
            result = await self._request("PUT", endpoint, json_data={"fields": fields})
            logger.warning(f"✅ 成功更新记录 {record_id}")
            return result
        except Exception as e:
            logger.error(f"❌ 更新记录 {record_id} 失败: {e}")
            logger.error(f"   字段: {list(fields.keys())}")
            raise

    async def batch_update_records(
        self,
        app_token: str,
        table_id: str,
        records: List[Dict],
        batch_size: int = 500
    ) -> Dict:
        """批量更新记录"""
        endpoint = f"/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"

        results = {"success_count": 0, "failed_count": 0, "errors": []}

        # 分批处理
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            try:
                await self._request("POST", endpoint, json_data={"records": batch})
                results["success_count"] += len(batch)
            except Exception as e:
                results["failed_count"] += len(batch)
                results["errors"].append(str(e))
                logger.error(f"批量更新失败: {e}")

        return results

    @retry_async(RetryConfigs.NETWORK)
    async def download_attachment(
        self,
        file_token: str,
        save_path: str,
        original_url: Optional[str] = None
    ) -> str:
        """
        下载附件
        
        Args:
            file_token: 文件 token
            save_path: 保存路径
            original_url: 原始 URL（如果提供，会尝试从中提取额外参数）
        """
        token = await self._get_tenant_access_token()
        
        # 方法1: 尝试使用 drive/v1/medias/{file_token}/download
        endpoint = f"/drive/v1/medias/{file_token}/download"
        url = f"{self.BASE_URL}{endpoint}"
        headers = {"Authorization": f"Bearer {token}"}
        
        # 如果提供了原始 URL，尝试提取查询参数
        params = None
        if original_url and "?" in original_url:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(original_url)
            query_params = parse_qs(parsed.query)
            # 将查询参数转换为字典（取第一个值）
            params = {k: v[0] if isinstance(v, list) and len(v) > 0 else v for k, v in query_params.items()}
            logger.debug(f"从原始 URL 提取参数: {params}")

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, params=params, allow_redirects=True) as resp:
                    # 如果返回 302 重定向，跟随重定向
                    if resp.status == 302 or resp.status == 301:
                        redirect_url = resp.headers.get('Location')
                        logger.info(f"收到重定向: {redirect_url}")
                        if redirect_url:
                            # 跟随重定向下载（不需要认证）
                            async with session.get(redirect_url) as redirect_resp:
                                if redirect_resp.status != 200:
                                    raise Exception(f"重定向下载失败: {redirect_resp.status}")
                                await self._save_file(redirect_resp, save_path)
                                return save_path
                    
                    if resp.status != 200:
                        # 尝试读取错误信息
                        error_text = await resp.text()
                        logger.error(f"下载附件失败 ({resp.status}): {error_text[:200]}")
                        raise Exception(f"下载附件失败: {resp.status}, {error_text[:200]}")
                    
                    await self._save_file(resp, save_path)
                    return save_path
                    
            except Exception as e:
                # 如果方法1失败，尝试方法2: 直接使用原始 URL（如果提供）
                if original_url:
                    logger.warning(f"方法1失败 ({str(e)}), 尝试使用原始 URL: {original_url[:100]}...")
                    try:
                        # 使用原始 URL，但添加认证头
                        async with session.get(original_url, headers=headers, allow_redirects=True) as resp:
                            if resp.status != 200:
                                raise Exception(f"使用原始 URL 下载失败: {resp.status}")
                            await self._save_file(resp, save_path)
                            logger.info(f"使用原始 URL 成功下载附件")
                            return save_path
                    except Exception as e2:
                        logger.error(f"方法2也失败: {e2}")
                        raise Exception(f"所有下载方法都失败: 方法1={e}, 方法2={e2}")
                else:
                    raise
    
    async def _save_file(self, resp: aiohttp.ClientResponse, save_path: str):
        """保存文件内容"""
        # 确保目录存在
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        with open(save_path, "wb") as f:
            async for chunk in resp.content.iter_chunked(8192):
                f.write(chunk)

        logger.info(f"文件已保存到: {save_path}, 大小: {os.path.getsize(save_path)} bytes")

    @retry_async(RetryConfigs.NETWORK)
    async def upload_attachment_to_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        field_id: str,
        file_path: str,
        file_name: Optional[str] = None
    ) -> Dict:
        """
        上传附件到多维表格记录的指定字段

        使用飞书两步上传方式：
        1. 上传文件到飞书云文档，获取 file_token
        2. 更新记录字段，填入 file_token（数组格式）

        Args:
            app_token: 多维表格 App Token
            table_id: 数据表 ID
            record_id: 记录 ID
            field_id: 附件字段 ID (不是字段名！)
            file_path: 本地文件路径
            file_name: 文件名（可选）

        Returns:
            上传结果
        """
        token = await self._get_tenant_access_token()

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        if file_name is None:
            file_name = os.path.basename(file_path)

        file_size = os.path.getsize(file_path)

        # 根据文件扩展名确定 MIME 类型
        ext = os.path.splitext(file_name)[1].lower()
        mime_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.mp4': 'video/mp4',
            '.mov': 'video/quicktime',
            '.avi': 'video/x-msvideo',
        }
        file_type = mime_types.get(ext, 'application/octet-stream')

        logger.warning(f"=== 开始上传附件 ===")
        logger.warning(f"文件: {file_name}, 大小: {file_size} bytes, 类型: {file_type}")

        async with aiohttp.ClientSession() as session:
            # 第1步：上传文件到飞书云文档
            # API: POST /open-apis/drive/v1/medias/upload_all
            # 使用 multipart/form-data 格式直接上传文件
            upload_url = f"{self.BASE_URL}/drive/v1/medias/upload_all"

            logger.warning(f"第1步：上传文件到云文档")
            logger.warning(f"  API: {upload_url}")
            logger.warning(f"  参数: parent_type=bitable, parent_node={table_id}")

            # 准备 multipart/form-data
            with open(file_path, 'rb') as f:
                file_content = f.read()

            # 构建 multipart/form-data
            # Feishu API 需要 file_name 字段
            data = aiohttp.FormData()
            data.add_field('file',
                          file_content,
                          filename=file_name,
                          content_type=file_type)
            data.add_field('file_name', file_name)
            data.add_field('size', str(file_size))

            headers = {
                "Authorization": f"Bearer {token}",
            }

            logger.warning(f"  发送请求: file={file_name}, size={file_size}, file_name={file_name}")

            async with session.post(upload_url, headers=headers, data=data) as resp:
                response_text = await resp.text()

                if resp.status != 200:
                    logger.error(f"第1步失败 ({resp.status}): {response_text[:500]}")
                    raise Exception(f"上传文件失败: {resp.status}, {response_text[:500]}")

                result = json.loads(response_text)

                if result.get("code") != 0:
                    logger.error(f"第1步失败: {result}")
                    raise Exception(f"上传文件失败: {result.get('msg')}")

                # 获取 file_token
                file_token = result.get("data", {}).get("file_token")

                if not file_token:
                    raise Exception(f"未获取到 file_token: {response_text[:200]}")

                logger.warning(f"第1步完成：获取 file_token={file_token[:30]}...")

            logger.warning(f"第2步：更新记录字段 {field_id}")

            # 第2步：更新记录字段，填入 file_token
            # 注意：附件字段值必须是数组格式 [{file_token: "..."}]
            update_url = f"{self.BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"

            update_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            update_data = {
                "fields": {
                    field_id: [  # 关键：附件字段必须是数组！
                        {
                            "file_token": file_token
                        }
                    ]
                }
            }

            async with session.patch(update_url, headers=update_headers, json=update_data) as resp:
                response_text = await resp.text()

                if resp.status != 200:
                    logger.error(f"第2步失败 ({resp.status}): {response_text[:500]}")
                    raise Exception(f"更新记录失败: {resp.status}, {response_text[:500]}")

                result = json.loads(response_text)

                if result.get("code") != 0:
                    logger.error(f"第2步失败: {result}")
                    raise Exception(f"更新记录失败: {result.get('msg')}")

                logger.warning(f"✅ 附件上传完成: {field_id} -> {file_token[:30]}...")

                return {
                    "file_token": file_token,
                    "file_name": file_name,
                    "size": file_size,
                }


def get_project_meta_path(project_id: str) -> Optional[Path]:
    """获取项目 meta.json 的路径（V2 结构：从数据库获取路径）"""
    if not project_id:
        return None

    # 使用 ProjectPathService 获取项目路径
    try:
        from paretoai.services.project_path_service import get_project_path_service
        path_service = get_project_path_service()
        project_storage_path = path_service.get_project_storage_path(project_id)

        if project_storage_path:
            return Path(project_storage_path) / "meta.json"

        # 回退到 V1 结构（兼容旧代码）
        logger.warning(f"项目 {project_id} 不在数据库中，使用 V1 路径结构")
    except Exception as e:
        logger.warning(f"从数据库获取项目路径失败: {e}")

    # V1 结构回退
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent.parent
    storage_path_env = os.getenv("LOCAL_STORAGE_PATH")
    if storage_path_env:
        storage_path = Path(storage_path_env)
        if not storage_path.is_absolute():
            storage_path = (project_root / storage_path).resolve()
    else:
        storage_path = (project_root / "data" / "uploads")
    return storage_path / "projects" / project_id / "meta.json"


def read_project_meta(project_id: str) -> Dict[str, Any]:
    """读取项目的本地 meta.json（状态、错误信息、更新时间）"""
    meta_path = get_project_meta_path(project_id)
    if not meta_path or not meta_path.exists():
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"读取项目 meta.json 失败 (project_id={project_id}): {e}")
        return {}


def write_project_meta(project_id: str, status: Optional[str] = None, error_message: Optional[str] = None, updated_at: Optional[str] = None, record_id: Optional[str] = None) -> bool:
    """
    更新项目的本地 meta.json
    
    Args:
        project_id: 项目ID
        status: 状态（可选，不传则保持原值）
        error_message: 错误信息（可选，不传则保持原值；传空字符串则清空）
        updated_at: 更新时间（可选，不传则自动设为当前时间）
        record_id: 飞书记录ID（可选，用于关联）
    
    Returns:
        是否成功
    """
    meta_path = get_project_meta_path(project_id)
    if not meta_path:
        return False
    
    # 确保项目目录存在
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 读取现有 meta（如果有）
    existing_meta = read_project_meta(project_id)
    
    # 构建新的 meta
    new_meta = existing_meta.copy()
    
    # 更新字段（只更新传入的参数）
    if status is not None:
        new_meta["status"] = status
    if error_message is not None:
        new_meta["error_message"] = error_message
    if updated_at is not None:
        new_meta["updated_at"] = updated_at
    else:
        # 如果没有传入 updated_at，自动设为当前时间（ISO 格式）
        new_meta["updated_at"] = datetime.now().isoformat()
    
    # 更新 record_id（如果传入）
    if record_id is not None:
        new_meta["record_id"] = record_id
    # 如果没传入但现有 meta 有，保留它
    elif "record_id" not in new_meta and existing_meta.get("record_id"):
        new_meta["record_id"] = existing_meta["record_id"]
    
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(new_meta, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"写入项目 meta.json 失败 (project_id={project_id}): {e}")
        return False


def parse_feishu_record_to_task(record: Dict) -> Dict:
    """将飞书记录转换为批量任务格式"""
    fields = record.get("fields", {})
    record_id = record.get("record_id", "")

    # 演员ID（飞书输入字段，可能为空）
    # 兼容多种字段名：历史上有人用 `actor ID`（带空格）而不是 `actor_id`
    actor_id = (
        fields.get("actor_id")
        or fields.get("actor ID")
        or fields.get("actorId")
        or ""
    )
    if actor_id is None:
        actor_id = ""
    if not isinstance(actor_id, str):
        actor_id = str(actor_id)

    # 解析 project_id（后续多处使用）
    project_id = fields.get("project_id", "")

    # ======== 数据源原则：优先本地，飞书只做索引/同步 ========
    # 1) 首帧：优先本地 opening_image.jpg（V2 结构：从数据库获取路径）
    opening_image = ""
    if project_id:
        from pathlib import Path
        import os
        # 使用 ProjectPathService 获取项目路径
        try:
            from paretoai.services.project_path_service import get_project_path_service
            path_service = get_project_path_service()
            project_storage_path = path_service.get_project_storage_path(project_id)

            if project_storage_path:
                local_opening = Path(project_storage_path) / "opening_image.jpg"
                if local_opening.exists():
                    # V2 结构：使用完整的相对路径生成 URL
                    # project_storage_path = /Users/.../data/uploads/projects/2026-01-24/eating-template/13748642fd3a
                    # 需要转换成 /storage/projects/2026-01-24/eating-template/13748642fd3a/opening_image.jpg
                    uploads_path_str = os.getenv("LOCAL_STORAGE_PATH", "./data/uploads")
                    uploads_path = Path(uploads_path_str).resolve()  # 转换为绝对路径
                    relative_path = Path(project_storage_path).relative_to(uploads_path)
                    opening_image = f"/storage/{relative_path}/opening_image.jpg"
        except Exception as e:
            logger.warning(f"从数据库获取项目路径失败: {e}")

    # fallback：飞书字段（可能是附件或文本URL）
    if not opening_image:
        opening_image = fields.get("opening_image_url", "")
        if isinstance(opening_image, list) and len(opening_image) > 0:
            opening_image = opening_image[0].get("url", "")
        elif isinstance(opening_image, dict):
            opening_image = opening_image.get("url", "")

        # 飞书附件URL -> 后端代理
        if opening_image and ("open.feishu.cn" in opening_image or "feishu.cn/open-apis/drive" in opening_image):
            from urllib.parse import quote
            opening_image = f"/proxy/image?url={quote(opening_image)}"

    # 解析分段数
    segment_count = fields.get("segment_count", 7)
    if isinstance(segment_count, str):
        segment_count = int(segment_count) if segment_count.isdigit() else 7

    # ========================================================================
    # 【架构重构】数据库是唯一事实来源
    # - segment_urls: 存储视频URL和状态（唯一数据源）
    # - storyboard_json: 存储分镜脚本内容（prompt等配置）
    # - 飞书/本地文件：仅作为备份和同步目标，不作为读取来源
    # ========================================================================
    
    storyboard_json = ""
    db_segment_urls = None
    db_task = None
    
    if project_id:
        try:
            from sqlmodel import Session, select
            from paretoai.models import BatchTask
            from paretoai.db import engine
            
            with Session(engine) as session:
                statement = select(BatchTask).where(BatchTask.project_id == project_id)
                db_task = session.exec(statement).first()
                
                if db_task:
                    # 【唯一数据源】从数据库获取 segment_urls
                    if db_task.segment_urls:
                        try:
                            db_segment_urls = json.loads(db_task.segment_urls)
                        except json.JSONDecodeError as e:
                            logger.warning(f"解析 segment_urls 失败: {e}")
                            db_segment_urls = {}
                    
                    # 分镜脚本内容（用于显示 prompt 等）
                    if db_task.storyboard_json:
                        storyboard_json = db_task.storyboard_json
                    
                    logger.debug(f"从数据库读取任务数据: {project_id}")
                else:
                    logger.debug(f"数据库中未找到项目: {project_id}")
                    
        except Exception as e:
            logger.warning(f"读取数据库失败: {e}")
    
    # 如果数据库没有 storyboard_json，fallback 到飞书（仅用于初始导入）
    if not storyboard_json:
        storyboard_json = fields.get("storyboard_json", "")
        if isinstance(storyboard_json, dict):
            storyboard_json = json.dumps(storyboard_json)

    # ========================================================================
    # 【简化】segments 只从数据库 segment_urls 读取
    # ========================================================================
    segments = []
    
    if db_segment_urls:
        # 数据库有数据，直接使用
        for i in range(segment_count):
            seg_key = f"segment_{i}"
            db_seg = db_segment_urls.get(seg_key, {})
            video_url = db_seg.get("video_url", "")
            first_frame_url = db_seg.get("first_frame_url", "")
            last_frame_url = db_seg.get("last_frame_url", "")
            seg_status = db_seg.get("status", "pending")
            
            # 状态校验：如果有视频URL但状态不是completed，修正状态
            if video_url and seg_status not in ("completed", "generating"):
                seg_status = "completed"
            elif not video_url and seg_status == "completed":
                seg_status = "pending"
            
            segments.append({
                "videoUrl": video_url,
                "firstFrameUrl": first_frame_url,
                "lastFrameUrl": last_frame_url,
                "status": seg_status
            })
    else:
        # 数据库没有 segment_urls，初始化为 pending 状态
        # 注意：这种情况只应该出现在新项目或数据迁移时
        for i in range(segment_count):
            segments.append({
                "videoUrl": "",
                "firstFrameUrl": "",
                "lastFrameUrl": "",
                "status": "pending"
            })
        logger.debug(f"项目 {project_id} 无 segment_urls，初始化为 pending")

    # 计算进度
    completed_segments = sum(1 for s in segments if s.get("status") == "completed")
    progress = f"{completed_segments}/{segment_count}段已完成"

    # 确定状态（注意：飞书的 generating_* 可能是历史遗留，需要做“新鲜度”判断）
    # ======== 优先读取本地 meta.json（数据源：本地优先） ========
    local_meta = read_project_meta(project_id) if project_id else {}
    
    # 确定状态：优先本地 meta.json，fallback 到飞书
    status = local_meta.get("status") or fields.get("status", "pending")
    error_message = local_meta.get("error_message") or fields.get("error_message")
    # updated_at：优先本地 meta.json（ISO 格式），fallback 到飞书
    updated_at_raw = local_meta.get("updated_at") or fields.get("updated_at")

    def _parse_updated_at_epoch_seconds(v):
        """尽量将 updated_at 转为 epoch 秒；失败返回 None。"""
        if v is None:
            return None
        try:
            # 数值（秒或毫秒）
            if isinstance(v, (int, float)):
                vv = float(v)
                return vv / 1000.0 if vv > 1e12 else vv
            if isinstance(v, str):
                s = v.strip()
                if not s:
                    return None
                # 纯数字字符串（秒或毫秒）
                if s.isdigit():
                    vv = float(s)
                    return vv / 1000.0 if vv > 1e12 else vv
                # ISO 8601
                from datetime import datetime, timezone
                # 兼容 Z
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
        except Exception:
            return None
        return None

    # generating 状态“过期阈值”（秒）。超过阈值则不再展示为 generating，改为按数据推断，避免“假转圈”。
    try:
        stale_sec = int(os.getenv("BATCH_GENERATING_STALE_SEC", "900"))  # 默认 15 分钟
    except Exception:
        stale_sec = 900
    import time as _time
    updated_at_epoch = _parse_updated_at_epoch_seconds(updated_at_raw)
    generating_fresh = (
        updated_at_epoch is not None and (_time.time() - updated_at_epoch) <= stale_sec
    )

    # 根据实际数据推断状态（覆盖飞书存储的可能过时的状态）
    # 优先级：completed > all_segments_ready > storyboard_ready > pending
    def infer_status_from_data():
        if fields.get("final_video_url"):
            return "completed"
        elif all(s.get("status") == "completed" for s in segments) and len(segments) > 0:
            return "all_segments_ready"
        elif storyboard_json:
            # 有分镜就绪，可以生成下一段（不使用 generating_segment_X，那只在实际生成时由后端设置）
            return "storyboard_ready"
        else:
            return "pending"

    # 防御性修复：如果飞书里写了 all_segments_ready，但实际段并未全部 completed，则按数据重新推断
    if status == "all_segments_ready":
        if not (fields.get("final_video_url") or (len(segments) > 0 and all(s.get("status") == "completed" for s in segments))):
            status = infer_status_from_data()

    # 如果状态是 "failed" 但实际有视频数据，重新判断
    if status == "failed":
        has_video_data = (
            fields.get("final_video_url") or
            any(s.get("status") == "completed" for s in segments) or
            any(fields.get(f"segment_{i}_video_url") for i in range(segment_count))
        )
        if has_video_data:
            status = infer_status_from_data()

    # generating_segment_X / storyboard_generating / merging：
    # 只有当状态“足够新鲜”时才展示 generating；否则视为过期，按数据推断，避免误导。
    if status.startswith("generating_segment_") and generating_fresh:
        try:
            seg_idx = int(status.split("_")[-1])
        except Exception:
            seg_idx = None

        # 关键修复：不再提前标记段为 generating，先检查段是否有视频

        # 若该段已有视频或已合成，则认为生成不再“进行中”
        seg_has_video = (
            seg_idx is not None and 0 <= seg_idx < len(segments) and bool(segments[seg_idx].get("videoUrl"))
        )
        # 关键修复：即使 generating_fresh 为 true，如果该段没有视频，也应该推断状态
        # 避免"假转圈"：状态显示正在生成，但实际没有视频在生成
        if fields.get("final_video_url") or seg_has_video:
            # 该段已有视频或已合成，推断状态
            status = infer_status_from_data()
        elif seg_idx is not None and 0 <= seg_idx < len(segments):
            # 该段没有视频，即使状态"新鲜"也应该推断（可能是之前生成失败或取消）
            status = infer_status_from_data()
            # 同时将该段的状态重置为 pending（避免显示转圈图标）
            if segments[seg_idx].get("status") != "completed":
                segments[seg_idx]["status"] = "pending"
        else:
            # 无法确定段索引，推断状态
            status = infer_status_from_data()

    elif status in ("storyboard_generating", "merging") and generating_fresh:
        # 若已经有最终/所有段产出，则覆盖；否则保留“进行中”
        if fields.get("final_video_url") or all(s.get("status") == "completed" for s in segments):
            status = infer_status_from_data()
    else:
        # generating 状态过期或无法判断新鲜度 → 统一按数据推断
        if status.startswith("generating_segment_") or status in ("storyboard_generating", "merging"):
            status = infer_status_from_data()

    # 如果状态不在预定义列表中，根据数据推断
    valid_statuses = [
        "pending", "storyboard_generating", "storyboard_ready",
        "generating_segment_0", "generating_segment_1", "generating_segment_2",
        "generating_segment_3", "generating_segment_4", "generating_segment_5",
        "generating_segment_6", "generating_segment_7", "all_segments_ready",
        "merging", "completed", "failed", "image_failed"
    ]
    if status not in valid_statuses:
        status = infer_status_from_data()

    # 最终视频 URL：优先飞书字段，其次本地项目目录（V2 结构：从数据库获取路径）
    final_video_url = fields.get("final_video_url", "") or ""
    if not final_video_url and project_id:
        try:
            from pathlib import Path
            import os
            # 使用 ProjectPathService 获取项目路径
            from paretoai.services.project_path_service import get_project_path_service
            path_service = get_project_path_service()
            project_storage_path = path_service.get_project_storage_path(project_id)

            if project_storage_path:
                local_final = Path(project_storage_path) / "final_video.mp4"
                if local_final.exists():
                    # V2 结构：使用完整的相对路径生成 URL
                    uploads_path = Path(os.getenv("LOCAL_STORAGE_PATH", "./data/uploads")).resolve()
                    relative_path = Path(project_storage_path).relative_to(uploads_path)
                    final_video_url = f"/storage/{relative_path}/final_video.mp4"
        except Exception:
            pass

    # 修复 final_video_url 中的 project_id（如果存在）
    # 向后兼容：处理飞书中存储的 V1 格式 URL
    if final_video_url and project_id and "/storage/projects/" in final_video_url:
        import re
        match = re.search(r'/storage/projects/([^/]+)/', final_video_url)
        if match:
            url_project_id = match.group(1)
            if url_project_id != project_id:
                logger.warning(f"检测到 V1 格式 URL，尝试重新生成 V2 格式: project_id={url_project_id} -> {project_id} (record_id={record_id})")
                # 尝试从本地项目重新生成 V2 格式 URL
                try:
                    from pathlib import Path
                    import os
                    from paretoai.services.project_path_service import get_project_path_service
                    path_service = get_project_path_service()
                    project_storage_path = path_service.get_project_storage_path(project_id)

                    if project_storage_path:
                        local_final = Path(project_storage_path) / "final_video.mp4"
                        if local_final.exists():
                            uploads_path = Path(os.getenv("LOCAL_STORAGE_PATH", "./data/uploads")).resolve()
                            relative_path = Path(project_storage_path).relative_to(uploads_path)
                            final_video_url = f"/storage/{relative_path}/final_video.mp4"
                            logger.info(f"✅ 已重新生成 V2 格式 URL: {final_video_url}")
                except Exception as e:
                    logger.warning(f"重新生成 V2 URL 失败，保留原 URL: {e}")

    # 关键：只要最终视频存在，就视为已完成（避免飞书 status 仍停留在 all_segments_ready）
    if final_video_url:
        status = "completed"

    # 解析发布日期字段（release_date 是飞书标准字段）
    # 支持多种字段名：release_date（优先）, publish_date, publishDate, 发送日期, 日期
    publish_date = (
        fields.get("release_date")  # 优先使用 release_date（飞书标准字段）
        or fields.get("publish_date")
        or fields.get("publishDate")
        or fields.get("发送日期")
        or fields.get("日期")
        or ""
    )
    # 处理日期格式：飞书日期字段可能是数字（毫秒时间戳）或字符串
    if publish_date:
        if isinstance(publish_date, (int, float)):
            # 数字格式，转换为日期字符串 YYYYMMDD
            try:
                from datetime import datetime
                dt = datetime.fromtimestamp(publish_date / 1000 if publish_date > 1e12 else publish_date)
                publish_date = dt.strftime("%Y%m%d")
            except Exception:
                publish_date = ""
        elif isinstance(publish_date, str):
            # 字符串格式，直接使用或清理
            publish_date = publish_date.strip().replace("-", "").replace("/", "")

    return {
        "id": record_id,
        "actorId": actor_id,
        "projectId": project_id,
        "openingImageUrl": opening_image,
        "sceneDescription": fields.get("scene_description", ""),
        "templateId": fields.get("template_id", "pet-mukbang"),
        "segmentCount": segment_count,
        "storyboardJson": storyboard_json,
        "segments": segments,
        "finalVideoUrl": final_video_url,
        "status": status,
        "errorMessage": error_message,
        "progress": progress,
        "updatedAt": updated_at_raw,
        "publishDate": publish_date,  # 新增：发送日期字段
    }
