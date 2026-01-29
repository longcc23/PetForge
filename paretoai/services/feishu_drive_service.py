"""
飞书云空间服务
提供飞书 Drive API 的封装，支持创建文件夹和上传文件
"""
import os
import json
import asyncio
import aiohttp
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime
import logging
from pathlib import Path
import zlib

if TYPE_CHECKING:
    from paretoai.services.sync_state_store import SyncStateStore

logger = logging.getLogger(__name__)


class ResourceNotFoundError(Exception):
    """资源不存在异常 - 404 错误，不应重试"""
    pass


class FeishuDriveService:
    """飞书云空间服务 - 用于在云空间创建文件夹并上传文件"""

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        tenant_access_token: Optional[str] = None,
        *,
        table_id: Optional[str] = None,
        user_oauth_store: Optional[object] = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.table_id = table_id
        # 依赖注入：用于“用户身份”token 获取/刷新
        # 期望实现：get_valid_access_token(table_id=..., client_id=..., client_secret=...) -> Optional[str]
        self.user_oauth_store = user_oauth_store
        # 处理 tenant_access_token
        if tenant_access_token:
            tenant_access_token = tenant_access_token.strip()
            if not tenant_access_token.startswith('t-'):
                tenant_access_token = f"t-{tenant_access_token}"
                logger.info("检测到 tenant_access_token 缺少 't-' 前缀，已自动添加")
        self._tenant_access_token: Optional[str] = tenant_access_token
        self._token_expires_at: float = 0
        if tenant_access_token:
            self._token_expires_at = datetime.now().timestamp() + 7200
            logger.info(f"使用提供的 tenant_access_token: {tenant_access_token[:30]}...")

    async def _get_user_access_token_if_available(self) -> Optional[str]:
        if not self.user_oauth_store:
            logger.info("user_oauth_store 未配置，跳过用户 token 获取")
            return None
        if not self.table_id:
            logger.info("table_id 未配置，跳过用户 token 获取")
            return None
        try:
            # duck typing：避免强依赖具体实现
            token = await self.user_oauth_store.get_valid_access_token(
                table_id=self.table_id,
                client_id=self.app_id,
                client_secret=self.app_secret,
            )
            if token:
                logger.info(f"✅ 获取到 user_access_token: {token[:30]}...")
            else:
                logger.info(f"未获取到 user_access_token (table_id={self.table_id})")
            return token
        except Exception as e:
            logger.warning(f"获取/刷新 user_access_token 失败，将回退 tenant token: {e}")
            return None

    async def has_user_auth(self) -> bool:
        token = await self._get_user_access_token_if_available()
        return bool(token)

    async def _get_tenant_access_token(self) -> str:
        """获取 tenant_access_token"""
        if self._tenant_access_token:
            if datetime.now().timestamp() < self._token_expires_at:
                return self._tenant_access_token
            else:
                logger.warning("提供的 tenant_access_token 已过期，获取新 token")
                self._tenant_access_token = None

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
                self._token_expires_at = datetime.now().timestamp() + data["expire"] - 300
                logger.info(f"成功获取 tenant_access_token")
                return self._tenant_access_token

    async def _get_access_token(self) -> str:
        """
        Drive API token 获取策略：
        - 优先 user_access_token（用户授权）
        - 否则回退 tenant_access_token（应用身份）
        """
        user_token = await self._get_user_access_token_if_available()
        if user_token:
            return user_token
        return await self._get_tenant_access_token()

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        retry: int = 3
    ) -> Dict:
        """发送 API 请求"""
        token = await self._get_access_token()
        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        for attempt in range(retry):
            try:
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.request(
                        method,
                        url,
                        params=params,
                        json=json_data,
                        headers=headers
                    ) as resp:
                        if resp.status >= 400:
                            content_type = resp.headers.get('Content-Type', '')
                            if 'application/json' in content_type:
                                try:
                                    error_data = await resp.json()
                                    error_msg = error_data.get('msg', f"HTTP {resp.status}")
                                    error_code = error_data.get('code')
                                except:
                                    error_msg = f"HTTP {resp.status}"
                                    error_code = None
                            else:
                                error_msg = f"HTTP {resp.status}"
                                error_code = None

                            # 特殊处理 404 - 资源不存在是确定性结果，不应重试
                            if resp.status == 404:
                                logger.warning(f"[API 404] url={url}, error_code={error_code}, error_msg={error_msg}")
                                raise ResourceNotFoundError(f"资源不存在 (404): {error_msg}")

                            raise Exception(f"API 请求失败 ({resp.status}): {error_msg}")

                        data = await resp.json()

                        # 检查限流
                        if data.get("code") == 99991400:
                            wait_time = 2 ** attempt
                            logger.warning(f"飞书 API 限流，等待 {wait_time}s 后重试")
                            await asyncio.sleep(wait_time)
                            continue

                        if data.get("code") != 0:
                            error_msg = data.get('msg', '未知错误')
                            error_code = data.get('code')
                            logger.error(f"飞书 API 返回错误: code={error_code}, msg={error_msg}")
                            raise Exception(f"API 请求失败: {error_msg}")

                        return data.get("data", {})
            except ResourceNotFoundError:
                # 404 是确定性结果，直接抛出不重试
                raise
            except Exception as e:
                if attempt == retry - 1:
                    raise
                logger.warning(f"请求失败，重试中: {e}")
                await asyncio.sleep(1)

        raise Exception("请求失败，已达最大重试次数")

    async def create_folder(
        self,
        parent_folder_token: str,
        folder_name: str
    ) -> Dict:
        """
        创建文件夹

        Args:
            parent_folder_token: 父文件夹的 token
            folder_name: 新文件夹名称

        Returns:
            包含 folder_token 的字典

        Raises:
            Exception: 如果文件夹已存在（名称已被占用）则抛出异常
        """
        endpoint = "/drive/v1/files/create_folder"
        logger.info(f"创建文件夹: {folder_name} (父文件夹: {parent_folder_token})")

        payload = {
            "folder_token": parent_folder_token,
            "name": folder_name
        }

        result = await self._request("POST", endpoint, json_data=payload)

        if result.get("token"):
            logger.info(f"✅ 文件夹创建成功: {folder_name}, token={result['token']}")
        else:
            logger.warning(f"文件夹创建响应异常: {result}")

        return result

    async def list_folder(
        self,
        parent_folder_token: str,
        page_token: Optional[str] = None,
        limit: int = 100
    ) -> Dict:
        """
        列出文件夹中的文件和子文件夹

        尝试两种 API：
        1. 新版 Drive API: /drive/v1/files/{token}/children
        2. 旧版 Explorer API: /drive/explorer/v2/folder/{token}/children (备选)

        Args:
            parent_folder_token: 父文件夹的 token
            page_token: 分页 token，用于获取下一页
            limit: 每页数量，默认 100

        Returns:
            {
                "files": [
                    {"name": "...", "token": "...", "type": "folder/file", "size": ...},
                    ...
                ],
                "has_more": bool,
                "next_page_token": "..."
            }
        """
        # 先尝试新版 API
        endpoint = f"/drive/v1/files/{parent_folder_token}/children"
        params = {
            "page_size": limit,
            "order_by": "created_asc"
        }
        if page_token:
            params["page_token"] = page_token

        logger.info(f"[list_folder] 调用新版 API: {endpoint}")
        try:
            result = await self._request("GET", endpoint, params=params)
            logger.info(f"[list_folder] 新版 API 返回: files={len(result.get('files', []))}")

            files = result.get("files", [])
            has_more = result.get("has_more", False)
            next_page_token = result.get("page_token")

            return {
                "files": files,
                "has_more": has_more,
                "next_page_token": next_page_token
            }
        except ResourceNotFoundError:
            # 新版 API 失败，尝试旧版 Explorer API
            logger.info(f"[list_folder] 新版 API 返回 404，尝试旧版 Explorer API...")

            endpoint_v2 = f"/drive/explorer/v2/folder/{parent_folder_token}/children"
            params_v2 = {"pageSize": limit}
            if page_token:
                params_v2["pageToken"] = page_token

            try:
                result = await self._request("GET", endpoint_v2, params=params_v2)
                logger.info(f"[list_folder] 旧版 API 返回成功")

                # 旧版 API 的响应格式：children 是 {token: {name, type, ...}} 的字典
                children = result.get("children", {})
                files = []
                logger.debug(f"[list_folder] 旧版 API children 原始数据: {children}")
                for token, info in children.items():
                    # 旧版 API 可能用不同的字段名
                    file_size = info.get("size") or info.get("fileSize") or info.get("file_size")
                    file_type = info.get("type") or info.get("obj_type") or "file"
                    # 如果是文件夹，type 可能是 "folder" 或 "dir"
                    if file_type in ("dir", "directory"):
                        file_type = "folder"
                    files.append({
                        "token": token,
                        "name": info.get("name") or info.get("title"),
                        "type": file_type,
                        "size": file_size
                    })
                    logger.info(f"[list_folder] 解析文件: name={info.get('name')}, type={file_type}, size={file_size}")

                return {
                    "files": files,
                    "has_more": result.get("hasMore", False),
                    "next_page_token": result.get("pageToken")
                }
            except Exception as e:
                logger.warning(f"[list_folder] 旧版 API 也失败: {e}")
                raise ResourceNotFoundError(f"无法列出文件夹内容: {e}")

    async def search_folder_by_name(
        self,
        folder_name: str,
        parent_folder_token: Optional[str] = None
    ) -> Optional[str]:
        """
        使用搜索 API 查找文件夹（更可靠）

        Args:
            folder_name: 要查找的文件夹名称
            parent_folder_token: 限定在某个父文件夹下搜索（可选）

        Returns:
            文件夹 token，如果不存在则返回 None
        """
        endpoint = "/suite/docs-api/search/object"
        payload = {
            "search_key": folder_name,
            "count": 50,
            "offset": 0,
            "owner_ids": [],
            "chat_ids": [],
            "docs_types": ["folder"]  # 只搜索文件夹
        }

        try:
            logger.info(f"[搜索] 搜索文件夹: {folder_name}")
            result = await self._request("POST", endpoint, json_data=payload)

            docs_entities = result.get("docs_entities", [])
            for entity in docs_entities:
                if entity.get("title") == folder_name:
                    # 检查是否在指定的父文件夹下
                    doc_token = entity.get("docs_token")
                    if parent_folder_token:
                        # 如果指定了父文件夹，需要验证
                        # 由于搜索 API 不返回父文件夹信息，这里只能返回第一个匹配的
                        logger.info(f"[搜索] ✅ 找到文件夹: {folder_name}, token={doc_token}")
                    else:
                        logger.info(f"[搜索] ✅ 找到文件夹: {folder_name}, token={doc_token}")
                    return doc_token

            logger.info(f"[搜索] 未找到文件夹: {folder_name}")
            return None
        except Exception as e:
            logger.warning(f"[搜索] 搜索文件夹失败: {e}")
            return None

    async def find_folder_by_name(
        self,
        parent_folder_token: str,
        folder_name: str
    ) -> Optional[str]:
        """
        在父文件夹中查找指定名称的文件夹

        策略：
        1. 先尝试 list_folder API（标准方式）
        2. 如果失败，尝试搜索 API（备选方式）

        Args:
            parent_folder_token: 父文件夹的 token
            folder_name: 要查找的文件夹名称

        Returns:
            文件夹 token，如果不存在则返回 None
        """
        logger.info(f"查找文件夹: {folder_name} (父文件夹: {parent_folder_token})")

        # 方法1: 尝试 list_folder API
        try:
            page_token = None
            while True:
                result = await self.list_folder(parent_folder_token, page_token)

                for item in result.get("files", []):
                    if item.get("type") == "folder" and item.get("name") == folder_name:
                        folder_token = item.get("token")
                        logger.info(f"✅ 找到已存在的文件夹: {folder_name}, token={folder_token}")
                        return folder_token

                if not result.get("has_more"):
                    break

                page_token = result.get("next_page_token")

            logger.info(f"文件夹不存在（通过 list_folder）: {folder_name}")
            return None
        except ResourceNotFoundError:
            # 404 错误，尝试搜索 API 作为备选
            logger.info(f"list_folder 返回 404，尝试搜索 API...")
            return await self.search_folder_by_name(folder_name, parent_folder_token)

    async def find_file_by_name(
        self,
        parent_folder_token: str,
        file_name: str
    ) -> Optional[Dict]:
        """
        在文件夹中查找指定名称的文件

        Args:
            parent_folder_token: 文件夹的 token
            file_name: 要查找的文件名称

        Returns:
            文件信息字典（包含 token, size 等），如果不存在则返回 None
        """
        logger.info(f"查找文件: {file_name} (文件夹: {parent_folder_token})")

        try:
            page_token = None
            while True:
                result = await self.list_folder(parent_folder_token, page_token)

                for item in result.get("files", []):
                    if item.get("type") == "file" and item.get("name") == file_name:
                        logger.info(f"✅ 找到已存在的文件: {file_name}, size={item.get('size')}")
                        return {
                            "token": item.get("token"),
                            "name": item.get("name"),
                            "size": item.get("size"),
                        }

                if not result.get("has_more"):
                    break

                page_token = result.get("next_page_token")

            logger.info(f"文件不存在: {file_name}")
            return None
        except ResourceNotFoundError:
            # 404 错误（文件夹为空或无权限），返回 None
            logger.info(f"文件夹为空或无访问权限，文件不存在: {file_name}")
            return None

    def _should_upload_file(
        self,
        local_file_path: str,
        remote_file_info: Optional[Dict] = None
    ) -> bool:
        """
        判断文件是否需要上传

        策略：
        - 本地文件不存在 → 跳过
        - 远程文件不存在 → 上传
        - 远程文件存在但 size 未知 → 跳过（飞书不支持覆盖，避免重复）
        - 远程文件存在且 size 相同 → 跳过
        - 远程文件存在但 size 不同 → 上传（会创建新版本）

        Args:
            local_file_path: 本地文件路径
            remote_file_info: 远程文件信息（如果存在）

        Returns:
            True 表示需要上传，False 表示跳过
        """
        if not os.path.exists(local_file_path):
            logger.warning(f"本地文件不存在，跳过: {local_file_path}")
            return False

        if not remote_file_info:
            # 远程文件不存在，需要上传
            return True

        # 远程文件存在，检查 size
        remote_size = remote_file_info.get("size")
        
        if remote_size is None:
            # 远程文件存在但 size 未知，跳过上传（避免重复）
            logger.info(f"远程文件已存在（size 未知），跳过上传: {os.path.basename(local_file_path)}")
            return False

        # 比较文件大小
        local_size = os.path.getsize(local_file_path)

        if local_size != remote_size:
            logger.info(f"文件大小不同，需要上传: 本地={local_size}, 远程={remote_size}")
            return True

        logger.info(f"文件大小相同，跳过上传: {local_size} bytes")
        return False

    async def upload_file(
        self,
        parent_folder_token: str,
        file_path: str,
        file_name: Optional[str] = None,
        overwrite: bool = True
    ) -> Dict:
        """
        上传文件到指定文件夹

        优先使用 upload_all（小文件，<=20MB）。
        备注：当前实现不再走旧的 upload_prepare/upload_part/upload_commit，
        因为飞书接口字段并非 upload_token，而是 upload_id 等，旧实现会导致“看似成功但实际没上传”。

        Args:
            parent_folder_token: 目标文件夹的 token
            file_path: 本地文件路径
            file_name: 文件名（可选，默认使用原文件名）
            overwrite: 是否覆盖已有文件

        Returns:
            包含 file_token 的字典
        """
        token = await self._get_access_token()

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
            '.json': 'application/json',
            '.txt': 'text/plain',
        }
        file_type = mime_types.get(ext, 'application/octet-stream')

        logger.info(f"上传文件: {file_name}, 大小: {file_size} bytes, 类型: {file_type}")

        # 飞书 upload_all 限制：不要上传 > 20MB
        max_upload_all = 20 * 1024 * 1024
        if file_size > max_upload_all:
            raise Exception(f"文件过大（{file_size} bytes > 20MB），当前仅支持 upload_all 小文件上传")

        # checksum：飞书 upload_all 的 checksum 为 adler32（可选）
        # 参考（SDK/文档字段说明）："文件adler32校验和(可选)"
        checksum_adler32 = 1
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                checksum_adler32 = zlib.adler32(chunk, checksum_adler32)
        checksum = str(checksum_adler32 & 0xFFFFFFFF)

        upload_url = f"{self.BASE_URL}/drive/v1/files/upload_all"
        headers = {"Authorization": f"Bearer {token}"}

        form = aiohttp.FormData()
        form.add_field("file_name", file_name)
        form.add_field("parent_type", "explorer")
        form.add_field("parent_node", parent_folder_token)
        form.add_field("size", str(file_size))
        form.add_field("checksum", checksum)
        # overwrite 参数在 upload_all 文档中未明确支持；此处先忽略，由上层通过文件命名避免冲突
        with open(file_path, "rb") as f:
            form.add_field("file", f, filename=file_name, content_type=file_type)

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120, connect=10)) as session:
                async with session.post(upload_url, headers=headers, data=form) as resp:
                    data = await resp.json(content_type=None)
                    if resp.status >= 400:
                        raise Exception(f"上传失败 ({resp.status}): {data}")
                    if data.get("code") != 0:
                        raise Exception(f"上传失败: {data.get('msg')}")
                    file_token = (data.get("data") or {}).get("file_token")
                    if not file_token:
                        raise Exception(f"上传失败：未返回 file_token: {data}")

        logger.info(f"✅ 文件上传成功: {file_name}, token={str(file_token)[:30]}...")
        return {"file_token": file_token, "file_name": file_name, "size": file_size}

    async def sync_project_to_drive(
        self,
        parent_folder_token: str,
        project_id: str,
        project_root_path: str = "/storage/projects",
        publish_date: Optional[str] = None,
        incremental: bool = True,
        sync_state_store: Optional["SyncStateStore"] = None
    ) -> Dict:
        """
        同步项目到飞书云空间（支持增量上传 + 本地状态缓存）

        文件夹结构：
        {publish_date}-{project_id}/
        ├── opening_image.jpg
        ├── storyboard.json
        ├── segments/
        │   ├── segment_0.mp4
        │   ├── segment_1.mp4
        │   └── ...
        └── final_video.mp4

        增量策略（当 sync_state_store 提供时）：
        1. 优先使用本地缓存的 folder_token，避免 API 调用
        2. 通过比较本地文件 mtime 判断是否需要上传，无需查询远端
        3. 上传成功后更新本地缓存

        权限说明：
        - list 操作使用 tenant_access_token（应用身份，权限更高）
        - upload 操作使用 user_access_token（用户身份）

        Args:
            parent_folder_token: 父文件夹的 token（如：LO1jf6cT7lOEuXdHYXScSV8Vnth）
            project_id: 项目ID（12位hex）
            project_root_path: 项目根目录路径
            publish_date: 发送日期（YYYYMMDD），用于文件夹命名
            incremental: 是否启用增量上传（默认 True）
            sync_state_store: 同步状态缓存存储（可选，提供后启用本地缓存优化）

        Returns:
            {
                "folder_url": "https://...",
                "folder_token": "...",
                "files_uploaded": [
                    {"name": "opening_image.jpg", "token": "..."},
                    ...
                ],
                "files_skipped": [
                    {"name": "storyboard.json", "reason": "size_match"},
                    ...
                ]
            }
        """
        # 确定文件夹名称：优先使用发送日期，否则使用当前日期
        if not publish_date:
            publish_date = datetime.now().strftime("%Y%m%d")

        # 项目文件夹名称：{日期}-{project_id}
        folder_name = f"{publish_date}-{project_id}"

        logger.info(f"=== 开始同步项目 {project_id} 到飞书云空间 ===")
        logger.info(f"文件夹名称: {folder_name}")
        logger.info(f"增量上传: {'启用' if incremental else '禁用'}")
        logger.info(f"本地缓存: {'启用' if sync_state_store else '禁用'}")

        results = {
            "folder_name": folder_name,
            "folder_token": None,
            "folder_url": None,
            "files_uploaded": [],
            "files_skipped": [],
            "errors": [],
        }

        # 项目本地路径（V2 兼容：如果 project_root_path 已是完整路径则直接使用）
        if project_root_path.endswith(project_id):
            # V2 结构：project_root_path 已经是完整路径
            project_path = project_root_path
        else:
            # V1 结构：需要拼接 project_id
            project_path = os.path.join(project_root_path, project_id)

        if not os.path.exists(project_path):
            raise FileNotFoundError(f"项目目录不存在: {project_path}")

        # 同步前刷新缓存：检测本地文件变化，获取需要强制查询远端的文件列表
        changed_files: set = set()
        if sync_state_store:
            refresh_stats = sync_state_store.refresh_project_cache(folder_name, project_path)
            if refresh_stats["updated"] > 0 or refresh_stats["removed"] > 0:
                logger.info(f"[缓存刷新] 变化 {refresh_stats['updated']} 个，清理 {refresh_stats['removed']} 个")
            # 记录需要强制查询远端的文件
            changed_files = set(refresh_stats.get("changed_files", []))

        try:
            # 步骤1: 检查或创建项目文件夹（优先使用缓存）
            cached_folder_token = None
            cached_segments_token = None

            if incremental and sync_state_store:
                # 尝试从本地缓存获取 folder_token
                cached_folder_token = sync_state_store.get_folder_token(folder_name)
                cached_segments_token = sync_state_store.get_segments_folder_token(folder_name)

                if cached_folder_token:
                    logger.info(f"✅ [缓存命中] 项目文件夹 token: {cached_folder_token[:20]}...")
                    results["folder_token"] = cached_folder_token

            if not results["folder_token"]:
                # 缓存未命中，查询远端或创建
                if incremental:
                    existing_folder_token = await self.find_folder_by_name(parent_folder_token, folder_name)

                    if existing_folder_token:
                        logger.info(f"✅ 项目文件夹已存在，使用现有文件夹: {folder_name}")
                        results["folder_token"] = existing_folder_token
                    else:
                        logger.info(f"项目文件夹不存在，创建新文件夹: {folder_name}")
                        folder_result = await self.create_folder(parent_folder_token, folder_name)
                        results["folder_token"] = folder_result.get("token")
                else:
                    logger.info(f"创建项目文件夹: {folder_name}")
                    folder_result = await self.create_folder(parent_folder_token, folder_name)
                    results["folder_token"] = folder_result.get("token")

            if not results["folder_token"]:
                raise Exception("创建文件夹失败：未返回 token")

            # 步骤2: 检查或创建 segments 子文件夹（优先使用缓存）
            segments_folder_token = cached_segments_token

            if not segments_folder_token:
                try:
                    if incremental:
                        existing_segments_token = await self.find_folder_by_name(results["folder_token"], "segments")
                        if existing_segments_token:
                            segments_folder_token = existing_segments_token
                            logger.info(f"✅ segments 子文件夹已存在")
                        else:
                            segments_folder_result = await self.create_folder(results["folder_token"], "segments")
                            segments_folder_token = segments_folder_result.get("token")
                            logger.info(f"segments 子文件夹创建成功")
                    else:
                        segments_folder_result = await self.create_folder(results["folder_token"], "segments")
                        segments_folder_token = segments_folder_result.get("token")
                        logger.info(f"segments 子文件夹创建成功")
                except Exception as e:
                    logger.error(f"创建/查找 segments 子文件夹失败: {e}")
                    segments_folder_token = None
            else:
                logger.info(f"✅ [缓存命中] segments 子文件夹 token: {segments_folder_token[:20]}...")

            # 更新缓存中的文件夹 token
            if sync_state_store:
                sync_state_store.update_project_state(
                    folder_name,
                    results["folder_token"],
                    segments_folder_token
                )

            # 辅助函数：上传文件（带增量检查 + 本地缓存）
            async def upload_with_check(
                folder_token: str,
                local_path: str,
                display_name: str,
                file_rel_path: str  # 用于缓存 key，如 "opening_image.jpg" 或 "segments/segment_0.mp4"
            ) -> Optional[Dict]:
                """
                上传文件，支持增量检查（本地缓存 + 远端查询）
                
                策略：
                1. 本地文件检测到变化（在 changed_files 中）→ 强制查询远端
                2. 缓存命中且文件未变化 → 直接跳过（0 API 调用）
                3. 缓存未命中 → 查询远端判断是否需要上传
                """
                if not os.path.exists(local_path):
                    return None

                if incremental:
                    # 策略1: 检查是否在 changed_files 中（本地文件有变化，需强制查询远端）
                    force_check_remote = file_rel_path in changed_files
                    
                    if force_check_remote:
                        logger.info(f"[缓存] 本地文件已变化，强制查询远端: {display_name}")
                    elif sync_state_store:
                        # 策略2: 本地缓存命中且文件未变化 → 直接跳过
                        if not sync_state_store.is_file_changed(folder_name, file_rel_path, local_path):
                            logger.info(f"⏭️ [缓存] 文件未变化，跳过: {display_name}")
                            results["files_skipped"].append({
                                "name": display_name,
                                "reason": "cache_unchanged"
                            })
                            return None
                        else:
                            # 缓存未命中 → 需查询远端确认
                            logger.info(f"[缓存] 缓存未命中，查询远端: {display_name}")
                    
                    # 策略3: 查询远端判断是否需要上传
                    remote_file = await self.find_file_by_name(folder_token, display_name)
                    if not self._should_upload_file(local_path, remote_file):
                        results["files_skipped"].append({
                            "name": display_name,
                            "reason": "size_match"
                        })
                        # 远端已存在且大小匹配，更新缓存
                        if sync_state_store:
                            remote_token = remote_file.get("token") if remote_file else None
                            sync_state_store.mark_file_synced(folder_name, file_rel_path, local_path, remote_token)
                        return None

                # 执行上传
                result = await self.upload_file(folder_token, local_path, display_name)
                file_token = result.get("file_token")

                results["files_uploaded"].append({
                    "name": display_name,
                    "token": file_token
                })

                # 上传成功后更新缓存
                if sync_state_store:
                    sync_state_store.mark_file_synced(folder_name, file_rel_path, local_path, file_token)

                return result

            # 步骤3: 上传首帧图
            opening_image_path = os.path.join(project_path, "opening_image.jpg")
            try:
                await upload_with_check(
                    results["folder_token"],
                    opening_image_path,
                    "opening_image.jpg",
                    "opening_image.jpg"
                )
            except Exception as e:
                logger.error(f"上传首帧图失败: {e}")
                results["errors"].append({"name": "opening_image.jpg", "error": str(e)})

            # 步骤4: 上传分镜脚本
            storyboard_path = os.path.join(project_path, "storyboard.json")
            try:
                await upload_with_check(
                    results["folder_token"],
                    storyboard_path,
                    "storyboard.json",
                    "storyboard.json"
                )
            except Exception as e:
                logger.error(f"上传分镜脚本失败: {e}")
                results["errors"].append({"name": "storyboard.json", "error": str(e)})

            # 步骤5: 上传分段视频
            segments_path = os.path.join(project_path, "segments")
            if os.path.exists(segments_path) and segments_folder_token:
                for filename in sorted(os.listdir(segments_path)):
                    if filename.endswith('.mp4'):
                        file_path = os.path.join(segments_path, filename)
                        try:
                            await upload_with_check(
                                segments_folder_token,
                                file_path,
                                filename,
                                f"segments/{filename}"  # 缓存 key 带路径
                            )
                        except Exception as e:
                            logger.error(f"上传分段视频 {filename} 失败: {e}")
                            results["errors"].append({"name": f"segments/{filename}", "error": str(e)})

            # 步骤6: 上传最终视频
            final_video_path = os.path.join(project_path, "final_video.mp4")
            try:
                await upload_with_check(
                    results["folder_token"],
                    final_video_path,
                    "final_video.mp4",
                    "final_video.mp4"
                )
            except Exception as e:
                logger.error(f"上传最终视频失败: {e}")
                results["errors"].append({"name": "final_video.mp4", "error": str(e)})

            # 生成文件夹URL
            if results["folder_token"]:
                results["folder_url"] = f"https://qcnknpishse7.feishu.cn/drive/folder/{results['folder_token']}"

            logger.info(
                f"=== 项目 {project_id} 同步完成，上传 {len(results['files_uploaded'])} 个文件，跳过 {len(results['files_skipped'])} 个，失败 {len(results['errors'])} 个 ==="
            )

            return results

        except Exception as e:
            logger.error(f"同步项目 {project_id} 失败: {e}")
            raise

    async def batch_sync_projects(
        self,
        parent_folder_token: str,
        project_ids: List[str],
        project_root_path: str = "/storage/projects",
        project_publish_dates: Optional[Dict[str, str]] = None,
        incremental: bool = True,
        sync_state_store: Optional["SyncStateStore"] = None
    ) -> Dict:
        """
        批量同步多个项目到飞书云空间

        Args:
            parent_folder_token: 父文件夹的 token
            project_ids: 项目ID列表
            project_root_path: 项目根目录路径
            project_publish_dates: projectId -> publishDate (YYYYMMDD) 的映射，用于文件夹命名
            incremental: 是否启用增量上传（默认 True）
            sync_state_store: 同步状态缓存存储（可选，提供后启用本地缓存优化）

        Returns:
            {
                "total": 10,
                "success": 8,
                "failed": 2,
                "results": [...]
            }
        """
        # 如果未提供 sync_state_store，自动获取单例实例
        if sync_state_store is None and incremental:
            try:
                from paretoai.services.sync_state_store import get_sync_state_store
                sync_state_store = get_sync_state_store()
                logger.info("[batch_sync] 自动启用本地同步状态缓存")
            except Exception as e:
                logger.warning(f"[batch_sync] 无法加载 sync_state_store: {e}")

        results = {
            "total": len(project_ids),
            "success": 0,
            "failed": 0,
            "details": []
        }

        for project_id in project_ids:
            try:
                # 获取该项目的发送日期
                publish_date = project_publish_dates.get(project_id) if project_publish_dates else None

                result = await self.sync_project_to_drive(
                    parent_folder_token,
                    project_id,
                    project_root_path,
                    publish_date,
                    incremental,
                    sync_state_store
                )
                if result.get("errors"):
                    results["failed"] += 1
                else:
                    results["success"] += 1
                results["details"].append({
                    "project_id": project_id,
                    "status": "failed" if result.get("errors") else "success",
                    "result": result
                })
            except Exception as e:
                results["failed"] += 1
                results["details"].append({
                    "project_id": project_id,
                    "status": "failed",
                    "error": str(e)
                })
                logger.error(f"批量同步项目 {project_id} 失败: {e}")

        return results
