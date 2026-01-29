"""
视频片段生成服务
使用 Veo 3.1 API 或 VectorEngine API 生成视频
支持 Image-to-Video 和帧提取
"""
import os
import asyncio
import logging
import subprocess
import uuid
import tempfile
import base64
import json
from io import BytesIO
from typing import Optional, Dict, List, Tuple, Any
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


class VideoSegmentService:
    """视频片段生成服务"""
    
    def get_project_dir(self, project_id: Optional[str]) -> Optional[Path]:
        """
        获取项目目录路径（V2 结构 - 从数据库读取）

        如果 project_id 为 None 或数据库中不存在，返回 None（使用旧结构）
        """
        if not project_id:
            return None
        from .project_path_service import get_project_path_service
        path_service = get_project_path_service()
        storage_path = path_service.get_project_storage_path(project_id)
        if storage_path:
            return Path(storage_path)
        return None
    
    def get_segment_filename(self, segment_index: int, segment_type: Optional[str] = None) -> str:
        """生成视频片段文件名"""
        type_map = {
            'intro': 'intro',
            'eating': 'eating',  # 可以根据 food_position 进一步细化
            'outro': 'outro'
        }
        type_suffix = type_map.get(segment_type, 'segment') if segment_type else 'segment'
        return f"segment_{segment_index}_{type_suffix}.mp4"
    
    def get_frame_filename(self, segment_index: int, frame_type: str) -> str:
        """生成帧文件名（first 或 last）"""
        return f"segment_{segment_index}_{frame_type}.jpg"
    
    def __init__(self):
        """初始化服务"""
        # 导入 config 确保 .env 已加载
        from ..config import settings
        
        # 临时文件目录
        self.temp_dir = Path(tempfile.gettempdir()) / "paretoai_frames"
        self.temp_dir.mkdir(exist_ok=True)
        
        # 存储目录
        self.storage_dir = Path(os.getenv("LOCAL_STORAGE_PATH", "./data/uploads"))
        self.projects_dir = self.storage_dir / "projects"
        
        # 旧目录（向后兼容）
        self.videos_dir = self.storage_dir / "videos"
        self.frames_dir = self.storage_dir / "frames"
        self.opening_images_dir = self.storage_dir / "opening_images"
        self.storyboards_dir = self.storage_dir / "storyboards"
        
        # 创建所有必需的目录
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.opening_images_dir.mkdir(parents=True, exist_ok=True)
        self.storyboards_dir.mkdir(parents=True, exist_ok=True)
        
        # 测试视频目录（用于 Mock 模式）
        project_root = Path(__file__).parent.parent.parent
        self.test_videos_dir = project_root / "视频test2"
        
        # Video API 配置 - 支持多个提供商
        self.provider = os.getenv("VIDEO_PROVIDER", "vectorengine").lower()  # vectorengine / zhipu
        self.timeout = int(os.getenv("VIDEO_TIMEOUT", "180"))
        self.mock_mode = os.getenv("VIDEO_MOCK_MODE", "false").lower() == "true"
        
        # VectorEngine 配置
        self.vectorengine_api_key = os.getenv("VIDEO_API_KEY")
        self.vectorengine_base_url = os.getenv("VIDEO_BASE_URL", "https://api.vectorengine.ai/v1")
        self.vectorengine_model = os.getenv("VIDEO_MODEL", "veo_3_1-fast")
        
        # ZhipuAI 配置
        self.zhipu_api_key = os.getenv("ZHIPU_VIDEO_API_KEY")
        self.zhipu_base_url = "https://open.bigmodel.cn/api/paas/v4"
        self.zhipu_model = os.getenv("ZHIPU_VIDEO_MODEL", "vidu2-image")
        self.zhipu_with_audio = os.getenv("ZHIPU_VIDEO_WITH_AUDIO", "true").lower() == "true"
        
        # 根据提供商选择配置
        if self.provider == "zhipu":
            self.api_key = self.zhipu_api_key
            self.base_url = self.zhipu_base_url
            self.model = self.zhipu_model
            logger.info(f"VideoSegmentService initialized: ZhipuAI (智谱) API")
        else:
            self.api_key = self.vectorengine_api_key
            self.base_url = self.vectorengine_base_url
            self.model = self.vectorengine_model
            logger.info(f"VideoSegmentService initialized: VectorEngine API")
        
        logger.info(f"  - provider: {self.provider}")
        logger.info(f"  - base_url: {self.base_url}")
        logger.info(f"  - model: {self.model}")
        logger.info(f"  - mock_mode: {self.mock_mode}")
        logger.info(f"  - api_key: {'***' + self.api_key[-4:] if self.api_key else 'NOT SET'}")
        if self.provider == "zhipu":
            logger.info(f"  - with_audio: {self.zhipu_with_audio}")
        logger.info(f"Storage paths: videos={self.videos_dir}, frames={self.frames_dir}")
        logger.info(f"Test videos dir: {self.test_videos_dir} (exists: {self.test_videos_dir.exists()})")
    
    async def generate_video_segment(
        self,
        segment_index: int,
        prompt: str,
        first_frame_url: Optional[str] = None,
        previous_last_frame: Optional[str] = None,
        duration_sec: Optional[int] = None,
        project_id: Optional[str] = None,
        segment_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        生成单个视频片段
        
        Args:
            segment_index: 片段索引 (0-6)
            prompt: 视频生成提示词
            first_frame_url: 首帧图片 URL (用于第0段)
            previous_last_frame: 上一段的最后一帧 (用于衔接)
        
        Returns:
            Dict with video_url, first_frame_url, last_frame_url
        """
        # 确定输入帧
        input_frame = None
        if segment_index == 0:
            input_frame = first_frame_url
            if not input_frame:
                logger.warning("Segment 0: No opening image provided, using text-to-video mode")
        else:
            input_frame = previous_last_frame
            if not input_frame:
                raise ValueError(f"Segment {segment_index} requires previous_last_frame for daisy-chaining")
        
        # Mock 模式
        if self.mock_mode or not self.api_key:
            logger.info(f"Using mock mode for segment {segment_index}")
            return await self._generate_mock_segment(segment_index, input_frame, project_id, segment_type)
        
        # 真实 API 模式
        return await self._call_video_api(segment_index, prompt, input_frame, duration_sec, project_id, segment_type)
    
    async def _generate_mock_segment(self, segment_index: int, input_frame: Optional[str], project_id: Optional[str] = None, segment_type: Optional[str] = None) -> Dict[str, Any]:
        """生成 Mock 视频片段（使用视频test2文件夹中的真实视频）"""
        logger.info(f"使用 Mock 模式生成视频片段 {segment_index}, project_id={project_id}")
        await asyncio.sleep(2)  # 模拟 API 延迟
        
        # 确定存储目录（项目目录或旧目录）
        project_dir = self.get_project_dir(project_id)
        if project_dir:
            segments_dir = project_dir / "segments"
            frames_dir = project_dir / "frames"
            segments_dir.mkdir(parents=True, exist_ok=True)
            frames_dir.mkdir(parents=True, exist_ok=True)
            video_filename = self.get_segment_filename(segment_index, segment_type)
            video_path = segments_dir / video_filename
            video_url = f"/storage/projects/{project_id}/segments/{video_filename}"
            first_frame_filename = self.get_frame_filename(segment_index, "first")
            last_frame_filename = self.get_frame_filename(segment_index, "last")
            first_frame_url = f"/storage/projects/{project_id}/frames/{first_frame_filename}"
            last_frame_url = f"/storage/projects/{project_id}/frames/{last_frame_filename}"
        else:
            # 向后兼容：使用旧目录结构
            video_id = uuid.uuid4().hex[:8]
            video_path = self.videos_dir / f"segment_{segment_index}_{video_id}.mp4"
            video_url = f"/storage/videos/segment_{segment_index}_{video_id}.mp4"
            first_frame_url = f"/storage/frames/first_{segment_index}_{video_id}.jpg"
            last_frame_url = f"/storage/frames/last_{segment_index}_{video_id}.jpg"
            first_frame_filename = f"first_{segment_index}_{video_id}.jpg"
            last_frame_filename = f"last_{segment_index}_{video_id}.jpg"
            frames_dir = self.frames_dir
        
        # 使用视频test2文件夹中的视频 (2-01.mp4 到 2-07.mp4)
        if self.test_videos_dir.exists():
            # segment_index 0-6 对应 2-01.mp4 到 2-07.mp4
            test_video_name = f"2-0{segment_index + 1}.mp4"
            test_video_path = self.test_videos_dir / test_video_name
            
            if test_video_path.exists():
                logger.info(f"使用测试视频: {test_video_name}")
                
                # 复制到目标目录
                try:
                    import shutil
                    shutil.copy(test_video_path, video_path)
                    logger.info(f"✓ 测试视频已复制: {video_path.name}")
                    
                    # 从真实视频中提取首尾帧
                    try:
                        first_frame_path = frames_dir / first_frame_filename
                        last_frame_path = frames_dir / last_frame_filename
                        await self._extract_first_frame_from_video(str(video_path), first_frame_path)
                        await self._extract_last_frame_from_video(str(video_path), last_frame_path)
                        logger.info(f"✓ 首尾帧已提取")
                        
                        return {
                            "success": True,
                            "segment_index": segment_index,
                            "video_url": video_url,
                            "first_frame_url": first_frame_url,
                            "last_frame_url": last_frame_url,
                            "message": f"第 {segment_index + 1} 段视频生成完成（使用测试视频 {test_video_name}）"
                        }
                    except Exception as extract_error:
                        logger.warning(f"帧提取失败: {extract_error}，使用输入帧作为后备")
                        # Fallback to input frame
                        
                except Exception as e:
                    logger.warning(f"复制测试视频失败: {e}")
            else:
                logger.warning(f"测试视频不存在: {test_video_path}")
        else:
            logger.warning(f"测试视频目录不存在: {self.test_videos_dir}")
        
        # Fallback: 使用输入帧
        if input_frame:
            try:
                first_frame_path = frames_dir / first_frame_filename
                last_frame_path = frames_dir / last_frame_filename
                await self._save_frame_from_input(input_frame, first_frame_path)
                await self._save_frame_from_input(input_frame, last_frame_path)
                logger.info(f"使用输入帧作为首尾帧")
            except Exception as e:
                logger.warning(f"保存帧失败: {e}")
        
        return {
            "success": True,
            "segment_index": segment_index,
            "video_url": video_url,
            "first_frame_url": first_frame_url,
            "last_frame_url": last_frame_url,
            "message": f"第 {segment_index + 1} 段视频生成完成（Mock 模式）"
        }
    
    async def _extract_first_frame_from_video(self, video_path: str, output_path: Path) -> None:
        """从视频中提取首帧"""
        try:
            subprocess.run([
                'ffmpeg', '-i', video_path,
                '-vf', 'select=eq(n\\,0)',
                '-vframes', '1',
                '-y',
                str(output_path)
            ], check=True, capture_output=True, timeout=10)
        except Exception as e:
            logger.warning(f"FFmpeg首帧提取失败: {e}")
            raise
    
    async def _extract_last_frame_from_video(self, video_path: str, output_path: Path) -> None:
        """从视频中提取尾帧"""
        try:
            subprocess.run([
                'ffmpeg', '-sseof', '-1', '-i', video_path,
                '-update', '1', '-q:v', '1',
                '-y',
                str(output_path)
            ], check=True, capture_output=True, timeout=10)
        except Exception as e:
            logger.warning(f"FFmpeg尾帧提取失败: {e}")
            raise
    
    async def _call_video_api(
        self,
        segment_index: int,
        prompt: str,
        input_frame: Optional[str],
        duration_sec: Optional[int] = None,
        project_id: Optional[str] = None,
        segment_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """调用视频生成 API - 根据provider选择不同的API"""
        if self.provider == "zhipu":
            return await self._call_zhipu_api(segment_index, prompt, input_frame, duration_sec, project_id, segment_type)
        else:
            return await self._call_vectorengine_api(segment_index, prompt, input_frame, duration_sec, project_id, segment_type)
    
    async def _call_zhipu_api(
        self,
        segment_index: int,
        prompt: str,
        input_frame: Optional[str],
        duration_sec: Optional[int] = None,
        project_id: Optional[str] = None,
        segment_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """调用智谱视频生成 API"""
        import requests
        
        # 准备图片为base64或URL
        image_url = None
        if input_frame:
            try:
                image_data = await self._load_image(input_frame)
                if image_data:
                    # 智谱支持 base64
                    compressed = await self._compress_image(image_data)
                    base64_image = base64.b64encode(compressed).decode('utf-8')
                    image_url = f"data:image/jpeg;base64,{base64_image}"
                    logger.info(f"Image prepared for ZhipuAI, size: {len(compressed)} bytes")
            except Exception as e:
                logger.warning(f"Image processing failed: {e}")
        
        # 准备请求
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        # 固定使用 8 秒
        duration = 8

        payload = {
            "model": self.model,
            "prompt": prompt,
            "with_audio": self.zhipu_with_audio,  # 默认生成音效
            "duration": duration,
            "size": "1280x720",
            "movement_amplitude": "auto",
            "quality": "speed"
        }
        
        if image_url:
            payload["image_url"] = image_url
            logger.info("Using Image-to-Video mode with ZhipuAI")
        else:
            logger.info("Using Text-to-Video mode with ZhipuAI")
        
        try:
            logger.info(f"开始调用 ZhipuAI API: model={self.model}, segment={segment_index}")
            logger.info(f"Prompt (preview): {prompt[:100]}..., with_audio={self.zhipu_with_audio}")
            logger.debug(f"完整 Prompt (segment {segment_index}):\n{prompt}")
            
            # 创建视频生成任务
            response = requests.post(
                f"{self.base_url}/videos/generations",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            logger.info(f"API 响应状态: {response.status_code}")
            logger.debug(f"API 响应内容: {response.text[:500]}")
            
            response.raise_for_status()
            result = response.json()
            
            # 检查错误
            if 'error' in result:
                error_info = result['error']
                error_msg = error_info.get('message', 'Unknown error')
                logger.error(f"ZhipuAI API 错误: {error_msg}")
                raise Exception(f"智谱视频生成失败: {error_msg}")
            
            task_id = result.get('id')
            if not task_id:
                logger.error(f"API 响应中未找到任务ID: {result}")
                raise Exception(f"未返回任务ID: {result}")
            
            logger.info(f"✓ 视频任务已创建: task_id={task_id}")
            
            # 轮询任务状态（智谱使用不同的状态查询接口）
            cloud_video_url = await self._poll_zhipu_task(task_id, headers)
            
            # 步骤1: 获得在线URL后，立即写入storyboard.json（如果project_id存在）
            if project_id:
                self._update_storyboard_with_online_url(project_id, segment_index, cloud_video_url, None, None)
            
            # 步骤2: 下载视频并提取帧（返回本地路径）
            first_frame, last_frame, local_video_url = await self._download_and_extract_frames(cloud_video_url, segment_index, project_id, segment_type)
            
            # 步骤3: 更新storyboard.json中的first_frame_url和last_frame_url（本地路径）
            if project_id:
                self._update_storyboard_with_local_frames(project_id, segment_index, first_frame, last_frame)
            
            # 【关键】返回本地视频URL，而不是云端URL
            logger.info(f"✅ 视频生成完成，本地路径: {local_video_url}")
            return {
                "success": True,
                "segment_index": segment_index,
                "video_url": local_video_url,  # 使用本地路径
                "cloud_video_url": cloud_video_url,  # 保留云端URL供参考
                "first_frame_url": first_frame,
                "last_frame_url": last_frame,
                "message": f"第 {segment_index + 1} 段视频生成完成（智谱API，含音效）"
            }
            
        except requests.Timeout:
            raise Exception("视频生成超时，请稍后重试")
        except requests.HTTPError as e:
            error_msg = e.response.text if e.response else 'unknown'
            logger.error(f"HTTP error: {error_msg[:500]}")
            raise Exception(f"视频生成失败: HTTP {e.response.status_code if e.response else 'error'}")
        except Exception as e:
            logger.error(f"ZhipuAI API error: {e}")
            raise Exception(f"视频生成失败: {str(e)}")
    
    async def _call_vectorengine_api(
        self,
        segment_index: int,
        prompt: str,
        input_frame: Optional[str],
        duration_sec: Optional[int] = None,
        project_id: Optional[str] = None,
        segment_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """调用 VectorEngine 视频生成 API"""
        import requests
        
        # 准备图片文件
        image_file = None
        if input_frame:
            try:
                image_data = await self._load_image(input_frame)
                if image_data:
                    # 压缩图片
                    compressed = await self._compress_image(image_data)
                    image_file = ('image.jpg', BytesIO(compressed), 'image/jpeg')
                    logger.info(f"Image prepared, size: {len(compressed)} bytes")
            except Exception as e:
                logger.warning(f"Image processing failed: {e}")
                image_file = None
        
        # 准备请求
        # 添加 User-Agent 以避免被识别为机器人请求，减少 reCAPTCHA 验证失败
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        files: Dict[str, Any] = {}
        if image_file:
            files['input_reference'] = image_file
            logger.info("Using Image-to-Video mode")
        else:
            logger.info("Using Text-to-Video mode")
        
        # 固定使用 8 秒
        seconds = 8

        # 确保 model 字段不为空
        if not self.model:
            logger.error(f"Model is not set! provider={self.provider}, vectorengine_model={self.vectorengine_model}, zhipu_model={self.zhipu_model}")
            raise ValueError("Video model is not configured")

        # 准备表单数据（multipart/form-data）
        # 确保 model 字段不为空且是字符串
        if not self.model or not isinstance(self.model, str):
            logger.error(f"Model 无效! self.model={self.model}, type={type(self.model)}")
            raise ValueError("Video model is not configured or invalid")
        
        data = {
            'model': str(self.model).strip(),  # 确保是字符串且去除空格
            'prompt': str(prompt).strip(),
            'seconds': str(seconds),
            'size': '1280x720',
            'watermark': 'false'
        }
        
        # 再次验证 model 字段
        if not data.get('model'):
            logger.error(f"Model 字段为空! data={data}, self.model={self.model}")
            raise ValueError("Model field is required for VectorEngine API")
        
        logger.warning(f"准备发送请求: model='{data['model']}', prompt长度={len(prompt)}, seconds={seconds}, has_image={bool(files)}")
        logger.warning(f"请求数据字段: {list(data.keys())}, model值='{data.get('model')}'")
        logger.warning(f"self.model={self.model}, type={type(self.model)}")
        
        try:
            logger.warning(f"开始调用 Video API: model='{self.model}', segment={segment_index}")
            logger.warning(f"API 配置: base_url={self.base_url}, has_image={bool(files)}, model='{self.model}'")
            logger.warning(f"请求数据: model='{data.get('model')}', prompt长度={len(data.get('prompt', ''))}, seconds={data.get('seconds')}")
            
            # 创建视频生成任务
            # VectorEngine base_url 已经包含 /v1，所以直接拼接 /videos
            api_url = f"{self.base_url}/videos" if "/v1" in self.base_url else f"{self.base_url}/v1/videos"
            logger.warning(f"发送请求到: {api_url}, model='{data['model']}'")
            logger.warning(f"完整 data 字典: {data}")
            
            response = requests.post(
                api_url,
                headers=headers,
                data=data,
                files=files,
                timeout=30,
                proxies={"http": "", "https": ""}
            )
            
            logger.info(f"API 响应状态: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"VectorEngine API 错误响应 (status {response.status_code}): {response.text[:1000]}")
            logger.debug(f"API 响应内容: {response.text[:500]}")
            
            response.raise_for_status()
            result = response.json()
            
            task_id = result.get('id')
            if not task_id:
                logger.error(f"API 响应中未找到任务ID: {result}")
                raise Exception(f"未返回任务ID: {result}")
            
            logger.info(f"✓ 视频任务已创建: task_id={task_id}")
            
            # 轮询任务状态
            cloud_video_url = await self._poll_video_task(task_id, headers)
            
            # 步骤1: 获得在线URL后，立即写入storyboard.json（如果project_id存在）
            if project_id:
                self._update_storyboard_with_online_url(project_id, segment_index, cloud_video_url, None, None)
            
            # 步骤2: 下载视频并提取帧（返回本地路径）
            first_frame, last_frame, local_video_url = await self._download_and_extract_frames(cloud_video_url, segment_index, project_id, segment_type)
            
            # 步骤3: 更新storyboard.json中的first_frame_url和last_frame_url（本地路径）
            if project_id:
                self._update_storyboard_with_local_frames(project_id, segment_index, first_frame, last_frame)
            
            # 【关键】返回本地视频URL，而不是云端URL
            logger.info(f"✅ 视频生成完成，本地路径: {local_video_url}")
            return {
                "success": True,
                "segment_index": segment_index,
                "video_url": local_video_url,  # 使用本地路径
                "cloud_video_url": cloud_video_url,  # 保留云端URL供参考
                "first_frame_url": first_frame,
                "last_frame_url": last_frame,
                "message": f"第 {segment_index + 1} 段视频生成完成（API）"
            }
            
        except requests.Timeout:
            raise Exception("视频生成超时，请稍后重试")
        except requests.HTTPError as e:
            error_msg = e.response.text if e.response else 'unknown'
            logger.error(f"HTTP error: {error_msg[:500]}")
            raise Exception(f"视频生成失败: HTTP {e.response.status_code if e.response else 'error'}")
        except Exception as e:
            logger.error(f"Video API error: {e}")
            raise Exception(f"视频生成失败: {str(e)}")
    
    async def _load_image(self, image_input: str) -> Optional[bytes]:
        """加载图片数据"""
        if image_input.startswith('data:image'):
            # Base64
            base64_str = image_input.split(',')[1] if ',' in image_input else image_input
            return base64.b64decode(base64_str)
        
        elif image_input.startswith('http://') or image_input.startswith('https://'):
            # HTTP URL
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(image_input)
                response.raise_for_status()
                return response.content
        
        elif image_input.startswith('/storage/') or image_input.startswith('/test-'):
            # 本地存储路径
            if image_input.startswith('/storage/'):
                relative_path = image_input[len('/storage/'):]
                local_path = self.storage_dir / relative_path
                
                # 如果文件存在，直接返回
                if local_path.exists():
                    return local_path.read_bytes()
                
                # 如果文件不存在，尝试通过 project_id 查找实际路径
                if relative_path.startswith('projects/'):
                    # 解析路径，提取 project_id
                    # 旧格式: projects/{project_id}/frames/...
                    # 新格式: projects/{date}/{template}/{project_id}/frames/...
                    import re
                    path_parts = relative_path.split('/')
                    
                    # 尝试提取 project_id（12位十六进制）
                    project_id = None
                    file_suffix = None  # 如 "frames/segment_0_last.jpg"
                    
                    for i, part in enumerate(path_parts):
                        if len(part) == 12 and all(c in '0123456789abcdef' for c in part.lower()):
                            project_id = part
                            file_suffix = '/'.join(path_parts[i+1:])
                            break
                    
                    if project_id and file_suffix:
                        # 使用 ProjectPathService 获取实际存储路径
                        from paretoai.services.project_path_service import get_project_path_service
                        path_service = get_project_path_service()
                        actual_storage_path = path_service.get_project_storage_path(project_id)
                        
                        if actual_storage_path:
                            actual_file_path = Path(actual_storage_path) / file_suffix
                            if actual_file_path.exists():
                                logger.info(f"✅ 通过 ProjectPathService 找到文件: {actual_file_path}")
                                return actual_file_path.read_bytes()
                            else:
                                logger.warning(f"文件不存在: {actual_file_path}")
                        else:
                            logger.warning(f"项目不存在于数据库: {project_id}")
                    else:
                        logger.warning(f"无法从路径中提取 project_id: {relative_path}")
                    
                    return None
                else:
                    # 旧路径格式（如 frames/last_0_xxx.jpg），尝试在项目目录中查找
                    filename = Path(relative_path).name
                    logger.info(f"文件不存在于旧路径 {local_path}，尝试在项目目录中查找: {filename}")
                    
                    # 这里的遍历逻辑保留作为最后的回退
                    projects_dir = self.storage_dir / "projects"
                    if projects_dir.exists():
                        # 遍历所有日期目录
                        for date_dir in projects_dir.iterdir():
                            if not date_dir.is_dir():
                                continue
                            # 遍历所有模板目录
                            for template_dir in date_dir.iterdir():
                                if not template_dir.is_dir():
                                    continue
                                # 遍历所有项目目录
                                for project_dir in template_dir.iterdir():
                                    if not project_dir.is_dir():
                                        continue
                                    frames_dir = project_dir / "frames"
                                    if frames_dir.exists():
                                        frame_path = frames_dir / filename
                                        if frame_path.exists():
                                            logger.info(f"✓ 在项目目录中找到文件: {frame_path}")
                                            return frame_path.read_bytes()
            else:
                return None
            
            logger.warning(f"Local file not found: {local_path}")
            return None
        
        elif os.path.exists(image_input):
            return Path(image_input).read_bytes()
        
        return None
    
    async def _compress_image(self, image_data: bytes) -> bytes:
        """压缩图片"""
        try:
            from PIL import Image
        except ImportError:
            return image_data
        
        img = Image.open(BytesIO(image_data))
        
        max_size = 1280
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        buffer = BytesIO()
        img.convert('RGB').save(buffer, format='JPEG', quality=90)
        return buffer.getvalue()
    
    async def _save_frame_from_input(self, input_frame: str, output_path: Path):
        """保存帧图片"""
        image_data = await self._load_image(input_frame)
        if image_data:
            output_path.write_bytes(image_data)
    
    async def _poll_video_task(self, task_id: str, headers: Dict[str, str], max_attempts: int = 120) -> str:
        """
        轮询 VectorEngine 视频生成任务状态
        默认最大等待时间：10 + (120-10) * 3 = 340秒 ≈ 5.5分钟
        """
        import requests

        # 允许通过环境变量覆盖轮询次数（用于排队较久时避免过早超时）
        try:
            max_attempts = int(os.getenv("VECTORENGINE_POLL_MAX_ATTEMPTS", str(max_attempts)))
        except Exception:
            pass
        
        logger.info(f"开始轮询 VectorEngine 视频任务: task_id={task_id}, max_attempts={max_attempts}")
        
        for attempt in range(max_attempts):
            # 动态间隔：前10次每秒，之后每3秒
            if attempt < 10:
                await asyncio.sleep(1)
            else:
                await asyncio.sleep(3)
            
            try:
                api_url = f"{self.base_url}/videos/{task_id}" if "/v1" in self.base_url else f"{self.base_url}/v1/videos/{task_id}"
                response = requests.get(
                    api_url,
                    headers=headers,
                    timeout=30,
                    proxies={"http": "", "https": ""}
                )
                
                if response.status_code != 200:
                    logger.debug(f"Poll attempt {attempt+1}: status code {response.status_code}, waiting...")
                    continue
                
                result = response.json()
                status = result.get('status', '').lower()
                progress = result.get('progress', 0)
                
                elapsed = attempt if attempt < 10 else 10 + (attempt - 10) * 3
                logger.info(f"Poll {attempt+1}/{max_attempts}: status={status}, progress={progress}%, elapsed={elapsed}s")
                
                if status in ['completed', 'succeeded']:
                    video_url = result.get('url') or result.get('video_url') or result.get('output', {}).get('url')
                    if video_url:
                        logger.info(f"视频生成完成: {video_url} (耗时 {elapsed}秒)")
                        return video_url
                    raise Exception(f"任务完成但未返回视频URL")
                
                elif status in ['failed', 'error']:
                    error_msg = result.get('error', result.get('message', 'Unknown error'))
                    logger.error(f"视频生成失败: {error_msg}")
                    raise Exception(f"视频生成失败: {error_msg}")
                    
            except requests.RequestException as e:
                logger.warning(f"Poll error (attempt {attempt+1}): {e}")
                continue
        
        total_wait = 10 + (max_attempts - 10) * 3
        logger.error(f"视频生成超时: 等待 {total_wait}秒 后仍未完成")
        raise Exception(f"视频生成超时（等待超过 {total_wait}秒）")
    
    async def _poll_zhipu_task(self, task_id: str, headers: Dict[str, str], max_attempts: int = 120) -> str:
        """
        轮询智谱视频生成任务状态
        智谱API返回格式: {"model": "vidu2-image", "id": "xxx", "task_status": "PROCESSING/SUCCESS/FAIL"}
        """
        import requests
        
        logger.info(f"开始轮询智谱视频任务: task_id={task_id}, max_attempts={max_attempts}")
        
        for attempt in range(max_attempts):
            # 智谱建议间隔2-5秒
            await asyncio.sleep(3)
            
            try:
                # 智谱使用相同的任务创建接口来查询状态（需要传入task_id）
                response = requests.get(
                    f"{self.base_url}/async-result/{task_id}",
                    headers=headers,
                    timeout=30
                )
                
                if response.status_code != 200:
                    logger.debug(f"Poll attempt {attempt+1}: status code {response.status_code}, waiting...")
                    continue
                
                result = response.json()
                
                # 检查错误
                if 'error' in result:
                    error_info = result['error']
                    error_msg = error_info.get('message', 'Unknown error')
                    logger.error(f"智谱任务失败: {error_msg}")
                    raise Exception(f"视频生成失败: {error_msg}")
                
                task_status = result.get('task_status', '').upper()
                elapsed = (attempt + 1) * 3
                logger.info(f"Poll {attempt+1}/{max_attempts}: task_status={task_status}, elapsed={elapsed}s")
                
                if task_status == 'SUCCESS':
                    # 智谱返回的视频URL在 video_result 字段
                    video_result = result.get('video_result', [])
                    if video_result and len(video_result) > 0:
                        video_url = video_result[0].get('url')
                        if video_url:
                            logger.info(f"智谱视频生成完成: {video_url} (耗时 {elapsed}秒)")
                            return video_url
                    raise Exception(f"任务完成但未返回视频URL")
                
                elif task_status == 'FAIL':
                    error_msg = result.get('error', result.get('message', 'Unknown error'))
                    logger.error(f"智谱视频生成失败: {error_msg}")
                    raise Exception(f"视频生成失败: {error_msg}")
                
                elif task_status == 'PROCESSING':
                    continue  # 继续等待
                    
            except requests.RequestException as e:
                logger.warning(f"Poll error (attempt {attempt+1}): {e}")
                continue
        
        total_wait = max_attempts * 3
        logger.error(f"智谱视频生成超时: 等待 {total_wait}秒 后仍未完成")
        raise Exception(f"视频生成超时（等待超过 {total_wait}秒）")
    
    async def _download_and_extract_frames(self, video_url: str, segment_index: int, project_id: Optional[str] = None, segment_type: Optional[str] = None) -> Tuple[str, str, str]:
        """下载视频并提取首尾帧
        
        Returns:
            Tuple[str, str, str]: (first_frame_url, last_frame_url, local_video_url)
        """
        import requests
        
        try:
            # 下载视频
            logger.info(f"Downloading video from: {video_url[:100]}...")
            response = requests.get(video_url, timeout=60)
            response.raise_for_status()
            
            video_data = response.content
            logger.info(f"Downloaded {len(video_data)} bytes")
            
            # 确定存储目录（项目目录或旧目录）
            project_dir = self.get_project_dir(project_id)
            logger.info(f"Video storage: project_id={project_id}, project_dir={project_dir}, using_new_structure={bool(project_dir)}")
            if project_dir:
                segments_dir = project_dir / "segments"
                frames_dir = project_dir / "frames"
                segments_dir.mkdir(parents=True, exist_ok=True)
                frames_dir.mkdir(parents=True, exist_ok=True)
                video_filename = self.get_segment_filename(segment_index, segment_type)
                video_path = segments_dir / video_filename
                first_frame_filename = self.get_frame_filename(segment_index, "first")
                last_frame_filename = self.get_frame_filename(segment_index, "last")
                first_frame_path = frames_dir / first_frame_filename
                last_frame_path = frames_dir / last_frame_filename
                # 【关键修复】使用本地路径替代云端URL
                local_video_url = f"/storage/projects/{project_id}/segments/{video_filename}"
                first_frame_url = f"/storage/projects/{project_id}/frames/{first_frame_filename}"
                last_frame_url = f"/storage/projects/{project_id}/frames/{last_frame_filename}"
            else:
                # 向后兼容：使用旧目录结构
                video_id = uuid.uuid4().hex[:8]
                video_path = self.videos_dir / f"segment_{segment_index}_{video_id}.mp4"
                first_frame_path = self.frames_dir / f"first_{segment_index}_{video_id}.jpg"
                last_frame_path = self.frames_dir / f"last_{segment_index}_{video_id}.jpg"
                local_video_url = f"/storage/videos/segment_{segment_index}_{video_id}.mp4"
                first_frame_url = f"/storage/frames/first_{segment_index}_{video_id}.jpg"
                last_frame_url = f"/storage/frames/last_{segment_index}_{video_id}.jpg"
            
            # 保存视频
            video_path.write_bytes(video_data)
            logger.info(f"✅ 视频已保存到本地: {video_path}")
            
            # 提取帧
            await self._extract_first_frame_from_video(str(video_path), first_frame_path)
            await self._extract_last_frame_from_video(str(video_path), last_frame_path)
            
            # 返回本地存储路径（包含视频路径）
            return (
                first_frame_url,
                last_frame_url,
                local_video_url
            )
            
        except Exception as e:
            logger.error(f"Failed to download/extract: {e}")
            # Fallback
            if project_id:
                video_filename = self.get_segment_filename(segment_index, segment_type)
                local_video_url = f"/storage/projects/{project_id}/segments/{video_filename}"
                first_frame_url = f"/storage/projects/{project_id}/frames/segment_{segment_index}_first.jpg"
                last_frame_url = f"/storage/projects/{project_id}/frames/segment_{segment_index}_last.jpg"
            else:
                video_id = uuid.uuid4().hex[:8]
                local_video_url = f"/storage/videos/segment_{segment_index}_{video_id}.mp4"
                first_frame_url = f"/storage/frames/first_{segment_index}_{video_id}.jpg"
                last_frame_url = f"/storage/frames/last_{segment_index}_{video_id}.jpg"
            return (
                first_frame_url,
                last_frame_url,
                local_video_url
            )
    
    def _update_storyboard_with_online_url(self, project_id: str, segment_index: int, video_url: str, first_frame_url: Optional[str], last_frame_url: Optional[str]):
        """获得在线URL后，立即写入storyboard.json（使用 V2 路径结构）"""
        try:
            from .project_path_service import get_project_path_service
            path_service = get_project_path_service()
            storyboard_path_str = path_service.get_project_file_path(project_id, "storyboard.json")
            if not storyboard_path_str:
                logger.warning(f"⚠️ 无法获取项目 {project_id} 的 storyboard.json 路径")
                return
            storyboard_path = Path(storyboard_path_str)
            
            if not storyboard_path.exists():
                logger.warning(f"⚠️ storyboard.json 不存在: {storyboard_path}")
                return
            
            with open(storyboard_path, "r", encoding="utf-8") as f:
                storyboard_data = json.load(f)
            
            if "storyboards" not in storyboard_data:
                logger.warning(f"⚠️ storyboard.json 中没有 storyboards 字段")
                return
            
            storyboards = storyboard_data["storyboards"]
            if segment_index >= len(storyboards):
                logger.warning(f"⚠️ segment_index {segment_index} 超出范围 ({len(storyboards)})")
                return
            
            # 立即写入在线URL
            storyboards[segment_index]["video_url"] = video_url
            if first_frame_url:
                storyboards[segment_index]["first_frame_url"] = first_frame_url
            if last_frame_url:
                storyboards[segment_index]["last_frame_url"] = last_frame_url
            storyboards[segment_index]["status"] = "generating"  # 标记为生成中（下载完成后会改为completed）
            
            with open(storyboard_path, "w", encoding="utf-8") as f:
                json.dump(storyboard_data, f, ensure_ascii=False, indent=2)
            
            logger.warning(f"✅ 已立即写入在线URL到 storyboard.json (segment {segment_index}): {video_url[:60]}...")
        except Exception as e:
            logger.error(f"❌ 写入在线URL到 storyboard.json 失败: {e}", exc_info=True)
    
    def _update_storyboard_with_local_frames(self, project_id: str, segment_index: int, first_frame_url: str, last_frame_url: str):
        """下载完成后，更新storyboard.json中的本地帧路径（使用 V2 路径结构）"""
        try:
            from .project_path_service import get_project_path_service
            path_service = get_project_path_service()
            storyboard_path_str = path_service.get_project_file_path(project_id, "storyboard.json")
            if not storyboard_path_str:
                return
            storyboard_path = Path(storyboard_path_str)
            
            if not storyboard_path.exists():
                return
            
            with open(storyboard_path, "r", encoding="utf-8") as f:
                storyboard_data = json.load(f)
            
            if "storyboards" not in storyboard_data:
                return
            
            storyboards = storyboard_data["storyboards"]
            if segment_index >= len(storyboards):
                return
            
            # 更新本地帧路径和状态
            storyboards[segment_index]["first_frame_url"] = first_frame_url
            storyboards[segment_index]["last_frame_url"] = last_frame_url
            storyboards[segment_index]["status"] = "completed"
            
            with open(storyboard_path, "w", encoding="utf-8") as f:
                json.dump(storyboard_data, f, ensure_ascii=False, indent=2)
            
            logger.warning(f"✅ 已更新本地帧路径到 storyboard.json (segment {segment_index})")
        except Exception as e:
            logger.error(f"❌ 更新本地帧路径到 storyboard.json 失败: {e}", exc_info=True)
    
    
    async def merge_videos(self, segment_urls: List[str], project_id: Optional[str] = None) -> Dict[str, Any]:
        """合并视频片段（支持任意段数，3-8段）使用 V2 路径结构"""
        import requests

        if not segment_urls or len(segment_urls) < 1:
            raise ValueError(f"至少需要1个视频片段，当前: {len(segment_urls)}")

        if len(segment_urls) > 8:
            raise ValueError(f"最多支持8个视频片段，当前: {len(segment_urls)}")

        # 合并任务ID：用于临时文件命名（无论是否提供 project_id 都需要）
        merge_id = uuid.uuid4().hex[:8]

        # 如果提供了 project_id，使用 V2 路径结构
        if project_id:
            from .project_path_service import get_project_path_service
            path_service = get_project_path_service()
            storage_path = path_service.get_project_storage_path(project_id)
            if storage_path:
                output_path = Path(storage_path) / "final_video.mp4"
                final_video_url = f"/storage/projects/{project_id}/final_video.mp4"
                logger.info(f"合并视频将保存到项目目录 (V2): {output_path}")
            else:
                # 项目不存在于数据库，回退到旧结构
                output_path = self.videos_dir / f"final_{merge_id}.mp4"
                final_video_url = f"/storage/videos/final_{merge_id}.mp4"
                logger.warning(f"项目 {project_id} 不在数据库中，使用旧路径结构")
        else:
            output_path = self.videos_dir / f"final_{merge_id}.mp4"
            final_video_url = f"/storage/videos/final_{merge_id}.mp4"
        
        # 转换 URL 为文件路径
        video_paths = []
        for i, url in enumerate(segment_urls):
            if url.startswith('/storage/'):
                relative_path = url[len('/storage/'):]
                local_path = self.storage_dir / relative_path
                if local_path.exists():
                    video_paths.append(str(local_path))
                else:
                    logger.warning(f"Video not found: {local_path}")
            elif url.startswith('http://') or url.startswith('https://'):
                # 下载远程视频
                try:
                    logger.info(f"Downloading segment {i} from {url[:60]}...")
                    response = requests.get(url, timeout=60)
                    response.raise_for_status()
                    
                    temp_path = self.temp_dir / f"segment_{i}_{merge_id}.mp4"
                    temp_path.write_bytes(response.content)
                    video_paths.append(str(temp_path))
                except Exception as e:
                    logger.error(f"Failed to download segment {i}: {e}")
            elif os.path.exists(url):
                video_paths.append(url)
        
        if len(video_paths) < len(segment_urls):
            raise ValueError(f"只有 {len(video_paths)}/{len(segment_urls)} 个视频可用，无法合并")
        
        try:
            # 创建 FFmpeg concat 列表
            concat_file = self.temp_dir / f"concat_{merge_id}.txt"
            with open(concat_file, 'w', encoding='utf-8') as f:
                for video_path in video_paths:
                    escaped_path = str(Path(video_path).absolute()).replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")
            
            # 合并视频
            subprocess.run([
                'ffmpeg', '-f', 'concat', '-safe', '0',
                '-i', str(concat_file),
                '-c', 'copy',
                '-y',
                str(output_path)
            ], check=True, capture_output=True)
            
            return {
                "success": True,
                "final_video_url": final_video_url,
                "message": "视频合成完成"
            }
            
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg merge failed: {e}")
            raise Exception(f"FFmpeg 合并失败")
        except FileNotFoundError:
            raise Exception("FFmpeg 未安装或不可用")


# Singleton instance
_video_segment_service = None


def get_video_segment_service() -> Optional[VideoSegmentService]:
    """获取或创建 VideoSegment 服务单例"""
    global _video_segment_service
    if _video_segment_service is None:
        try:
            _video_segment_service = VideoSegmentService()
        except Exception as e:
            logger.warning(f"VideoSegmentService not available: {e}")
            return None
    return _video_segment_service
