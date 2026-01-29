"""
分镜脚本生成服务
使用 Nano Banana API (Gemini Vision) 分析开场图生成7段分镜脚本
"""
import logging
import os
import json
import base64
import httpx
from typing import Dict, List, Optional
from pathlib import Path
from PIL import Image
from io import BytesIO

logger = logging.getLogger(__name__)


class StoryboardService:
    """分镜脚本生成服务"""
    
    def __init__(self):
        """初始化服务"""
        # 导入 config 确保 .env 已加载
        from ..config import settings
        
        self.base_url = os.getenv("NANO_BASE_URL") or settings.nano_base_url
        self.api_key = os.getenv("NANO_API_KEY") or settings.nano_api_key
        if self.api_key:
            self.api_key = self.api_key.strip()
        
        # 使用文本视觉模型生成分镜脚本
        self.model = os.getenv("STORYBOARD_MODEL", "gemini-3-pro-preview")
        self.timeout = int(os.getenv("NANO_TIMEOUT", "180"))  # 增加到180秒
        
        logger.info(f"StoryboardService initialized: base_url={self.base_url}, model={self.model}")
        
        # 加载专业的分镜脚本提示词模板
        prompt_path = Path(__file__).parent.parent / "prompts" / "storyboard_generation.txt"
        if prompt_path.exists():
            with open(prompt_path, 'r', encoding='utf-8') as f:
                self.prompt_template = f.read()
            logger.info(f"Loaded professional storyboard prompt from: {prompt_path}")
        else:
            logger.warning(f"Professional prompt not found: {prompt_path}, using fallback")
            self.prompt_template = """You are a professional video storyboard director specializing in pet mukbang content.

Analyze the opening image and generate a 7-segment storyboard for a pet eating show video.

## Output Format (JSON Array with 7 segments)

Return ONLY a JSON array with exactly 7 segments. Each segment must have:
- segment_index: 0-6
- segment_type: "intro" | "eating" | "outro"
- crucial: Key visual moment (English, 1 sentence)
- crucial_zh: 关键画面 (中文, 1句话)
- action: Pet's action description (English, 1 sentence)
- action_zh: 宠物动作 (中文, 1句话)
- sound: Sound effects description (English, brief)
- sound_zh: 音效描述 (中文, 简短)

Now analyze the opening image and generate the storyboard."""
    
    def generate_storyboard(
        self,
        opening_image_url: str,
        scene_description: str,
        opening_image_base64: Optional[str] = None,
        segment_count: int = 5,
        segment_durations: Optional[List[int]] = None
    ) -> List[Dict]:
        """
        使用 Nano Banana Vision API 生成分镜脚本
        
        Args:
            opening_image_url: 开场图 URL 或路径
            scene_description: 场景描述
            opening_image_base64: Base64 编码的图片（可选）
            segment_count: 分镜段数（3-8），默认5段
            segment_durations: 每段时长（秒），4-8秒，如果未提供则使用默认值8秒
        
        Returns:
            包含指定段数的分镜脚本列表
        """
        # 确保 segment_count 是整数
        if isinstance(segment_count, str):
            segment_count = int(segment_count) if segment_count.isdigit() else 5
        elif not isinstance(segment_count, int):
            segment_count = 5
        # 限制范围在 3-8
        segment_count = max(3, min(8, segment_count))
        
        if not self.base_url or not self.api_key:
            logger.warning("Nano service not configured, using mock storyboard")
            return self._generate_mock_storyboard(scene_description, segment_count, segment_durations)
        
        try:
            logger.info(f"=== Starting storyboard generation ===")
            logger.info(f"Opening image URL: {opening_image_url}")
            logger.info(f"Scene description: {scene_description}")
            
            # 准备图片数据
            logger.info("Loading image...")
            image_base64 = self._prepare_image(opening_image_url, opening_image_base64)
            logger.info(f"Image loaded successfully, size: {len(image_base64)} chars")
            
            # 压缩图片（如果太大）
            max_size_mb = 2  # 最大 2MB base64
            if len(image_base64) > max_size_mb * 1024 * 1024:
                logger.warning(f"图片过大 ({len(image_base64) / 1024 / 1024:.2f} MB)，开始压缩...")
                image_base64 = self._compress_image_base64(image_base64, max_size_mb * 1024 * 1024)
                logger.info(f"压缩后大小: {len(image_base64) / 1024 / 1024:.2f} MB")
            
            # 动态调整 prompt 模板中的段数
            prompt_with_count = self.prompt_template.replace("7-segment", f"{segment_count}-segment")
            prompt_with_count = prompt_with_count.replace("7 segments", f"{segment_count} segments")
            prompt_with_count = prompt_with_count.replace("exactly 7 segments", f"exactly {segment_count} segments")
            prompt_with_count = prompt_with_count.replace("Segment 0-6", f"Segment 0-{segment_count-1}")
            
            # 根据段数调整结构说明
            if segment_count <= 5:
                # 短视频：intro + (segment_count-2) eating + outro
                eating_count = segment_count - 2
                structure_note = f"- **Segment 0 (Intro)**: Greeting, no eating\n- **Segments 1-{eating_count} (Eating)**: Consume food items in order\n- **Segment {segment_count-1} (Outro)**: Full belly, sleepy, goodbye"
            else:
                # 长视频：intro + (segment_count-2) eating + outro
                eating_count = segment_count - 2
                structure_note = f"- **Segment 0 (Intro)**: Greeting, no eating\n- **Segments 1-{eating_count} (Eating)**: Consume food items in order (left → center → right)\n- **Segment {segment_count-1} (Outro)**: Full belly, sleepy, goodbye"
            
            # 对于 5 段，特别强调完整性要求（因为 API 容易返回不完整结果）
            extra_emphasis = ""
            if segment_count == 5:
                extra_emphasis = """
**CRITICAL FOR 5 SEGMENTS**: 
- You MUST generate ALL 5 segments: Segment 0 (Intro), Segments 1-3 (Eating), Segment 4 (Outro)
- DO NOT stop at 4 segments. The JSON array MUST have exactly 5 objects.
- If you run out of tokens, prioritize completing all 5 segments with concise but complete descriptions.
"""
            
            # 构建完整提示词（更明确地强调段数要求）
            full_prompt = f"""{prompt_with_count}

## CRITICAL: Segment Count Requirement
**YOU MUST GENERATE EXACTLY {segment_count} SEGMENTS. NO MORE, NO LESS.**
{extra_emphasis}
The JSON array you return MUST contain exactly {segment_count} objects:
- segment_index: 0, 1, 2, ..., {segment_count - 1}
- Total count: {segment_count} segments

## Segment Structure ({segment_count} segments total)
{structure_note}

Opening Image: [See attached image]

Scene Description: {scene_description}

**IMPORTANT**: Please analyze the opening image and generate EXACTLY {segment_count} segments in the JSON array. The array must have {segment_count} elements, with segment_index from 0 to {segment_count - 1}.
**DO NOT return incomplete JSON. Ensure the array is properly closed with a closing bracket `]`.**"""
            logger.info(f"Prompt prepared for {segment_count} segments, length: {len(full_prompt)} chars")
            
            # 计算 max_tokens：段数越多 JSON 越长；此前 6–8 段用 4000、≤5 用 5000，导致 7 段时被截断→仅 5 段→补全 ] 后解析出 5 段
            max_tokens = self._max_tokens_for_segments(segment_count)
            
            # 调用 API
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": full_prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                            }
                        ]
                    }
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens,
            }
            logger.info(f"=== Calling Nano API ===")
            logger.info(f"Model: {self.model}")
            logger.info(f"Base URL: {self.base_url}")
            logger.info(f"Timeout: {self.timeout}s")
            logger.info(f"Prompt length: {len(full_prompt)} chars")
            logger.info(f"Segment count: {segment_count}, max_tokens: {max_tokens}")
            
            # 增加超时时间，并添加重试机制
            timeout_config = httpx.Timeout(self.timeout, connect=30.0, read=self.timeout, write=30.0, pool=30.0)
            with httpx.Client(timeout=timeout_config) as client:
                logger.info("Sending POST request...")
                logger.info(f"Request payload size: {len(json.dumps(payload))} bytes")
                logger.info(f"Image base64 size: {len(image_base64)} chars")
                
                try:
                    response = client.post(
                        f"{self.base_url}/v1/chat/completions",
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        follow_redirects=True
                    )
                except httpx.RemoteProtocolError as e:
                    logger.error(f"Remote protocol error: {e}")
                    # 可能是图片太大，尝试压缩或使用更小的图片
                    raise RuntimeError(f"API 服务器连接中断，可能是请求过大或超时。请检查图片大小或网络连接。")
                except httpx.TimeoutException as e:
                    logger.error(f"Request timeout: {e}")
                    raise RuntimeError(f"API 请求超时（{self.timeout}秒）。请稍后重试或检查网络连接。")
                
                logger.info(f"Response received: {response.status_code}")
                
                if response.status_code != 200:
                    error_text = response.text[:500]
                    logger.error(f"Nano API error: {response.status_code}")
                    logger.error(f"Error details: {error_text}")
                    raise RuntimeError(f"Nano API error: {response.status_code}: {error_text}")
                
                response_data = response.json()
                logger.info("Response parsed as JSON")
                
                if "choices" not in response_data or len(response_data["choices"]) == 0:
                    logger.error(f"Unexpected response format: {str(response_data)[:200]}")
                    raise ValueError(f"Unexpected API response format")
                
                response_text = response_data["choices"][0]["message"]["content"].strip()
                logger.info(f"Got response text, length: {len(response_text)} chars")

            # 解析 JSON 响应
            storyboards = self._parse_response(response_text)

            # 验证段数是否正确
            actual_count = len(storyboards)
            if actual_count != segment_count:
                logger.warning(f"⚠️ 生成的段数 ({actual_count}) 与请求的段数 ({segment_count}) 不匹配！")
                if actual_count < segment_count:
                    logger.warning(f"缺少 {segment_count - actual_count} 段，尝试补充...")
                    # 补充缺失的段（基于最后一个eating段的模式）
                    last_eating_segment = None
                    for seg in reversed(storyboards):
                        if seg.get('segment_type') == 'eating':
                            last_eating_segment = seg.copy()
                            break
                    
                    # 补充缺失的段
                    for i in range(actual_count, segment_count):
                        if i == segment_count - 1:
                            # 最后一段应该是 outro
                            new_segment = {
                                "segment_index": i,
                                "segment_type": "outro",
                                "food_item": None,
                                "crucial": storyboards[0].get("crucial", ""),
                                "crucial_zh": storyboards[0].get("crucial_zh", ""),
                                "action": "The cat slowly lowers its upper body to rest its chin gently on its front paws on the table. It looks at the lens and blinks slowly.",
                                "action_zh": "猫咪慢慢压低上半身，将下巴轻轻搁在桌面的前爪上。它看着镜头，缓慢眨眼。",
                                "negative_constraint": "No reaching for background shelves, no sudden movements.",
                                "negative_constraint_zh": "禁止伸手够背景架子，禁止突然动作。",
                                "sound": "Soft 'Rustle' of fur settling. Cute breathy exhale. No music.",
                                "sound_zh": "毛发安顿时的轻微摩擦声。可爱的呼吸声。无音乐。"
                            }
                        else:
                            # 中间段应该是 eating（基于最后一个eating段）
                            if last_eating_segment:
                                new_segment = last_eating_segment.copy()
                                new_segment["segment_index"] = i
                                new_segment["food_item"] = f"Food Item {i}"
                            else:
                                new_segment = {
                                    "segment_index": i,
                                    "segment_type": "eating",
                                    "food_item": f"Food Item {i}",
                                    "crucial": storyboards[0].get("crucial", ""),
                                    "crucial_zh": storyboards[0].get("crucial_zh", ""),
                                    "action": "The cat picks up a food item and eats it.",
                                    "action_zh": "猫咪拿起食物并吃掉。",
                                    "negative_constraint": "No morphing, no disappearing objects.",
                                    "negative_constraint_zh": "无变形，无物体消失。",
                                    "sound": "Crunch, Chewing. No music.",
                                    "sound_zh": "咀嚼声，嘎吱声。无音乐。"
                                }
                        storyboards.append(new_segment)
                        logger.warning(f"已补充段 {i}")
                else:
                    # 如果生成的段数多于请求的，截断到请求的数量
                    logger.warning(f"生成的段数过多，截断到 {segment_count} 段")
                    storyboards = storyboards[:segment_count]

            # 验证并补充字段
            default_duration = 8
            for i, segment in enumerate(storyboards):
                # 确保 segment_index 正确
                segment['segment_index'] = i
                segment['id'] = f"seg_{i}_{os.urandom(4).hex()}"
                segment['prompt'] = self._construct_full_prompt(segment)
                segment['status'] = 'pending'
                segment['video_url'] = None
                segment['first_frame_url'] = None
                segment['last_frame_url'] = None
                # 固定每段时长为8秒
                segment['duration_sec'] = 8
            
            # 最终验证
            final_count = len(storyboards)
            if final_count != segment_count:
                logger.error(f"❌ 最终段数验证失败: {final_count} != {segment_count}")
                raise ValueError(f"生成的段数 ({final_count}) 与请求的段数 ({segment_count}) 不匹配")
            
            logger.info(f"✅ Storyboard generated successfully: {final_count} segments (requested: {segment_count})")
            return storyboards
            
        except Exception as e:
            logger.error(f"Storyboard generation failed: {e}", exc_info=True)
            # 不要静默回退到 mock，而是抛出错误让调用方知道
            error_msg = f"分镜生成失败: {type(e).__name__}: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
    
    def _prepare_image(self, opening_image_url: str, opening_image_base64: Optional[str]) -> str:
        """准备图片 base64 数据（V2 结构：从数据库获取路径）"""
        if opening_image_base64:
            if ',' in opening_image_base64:
                return opening_image_base64.split(',')[1]
            return opening_image_base64

        if opening_image_url.startswith('/storage/'):
            # 本地存储路径（V2 结构：从数据库获取路径）
            # 提取 project_id
            parts = opening_image_url.split('/')
            if len(parts) >= 3 and parts[2] == 'projects':
                # 尝试从数据库获取 V2 路径
                project_id = parts[3] if len(parts) > 3 else None
                file_name = parts[-1] if len(parts) > 3 else 'opening_image.jpg'

                if project_id:
                    try:
                        from paretoai.services.project_path_service import get_project_path_service
                        path_service = get_project_path_service()
                        v2_path = path_service.get_project_storage_path(project_id)

                        if v2_path:
                            # 使用 V2 路径
                            file_path = Path(v2_path) / file_name

                            if file_path.exists():
                                with open(file_path, 'rb') as f:
                                    logger.info(f"✅ 使用 V2 路径读取图片: {file_path}")
                                    return base64.b64encode(f.read()).decode('utf-8')
                            else:
                                logger.warning(f"V2 路径中文件不存在: {file_path}，尝试 V1 路径")
                    except Exception as e:
                        logger.warning(f"从数据库获取 V2 路径失败: {e}，尝试 V1 路径")

                # 回退到 V1 路径（兼容旧代码）
                storage_path = Path(os.getenv("LOCAL_STORAGE_PATH", "./data/uploads"))
                relative_path = opening_image_url[len('/storage/'):]
                file_path = storage_path / relative_path

                if file_path.exists():
                    with open(file_path, 'rb') as f:
                        logger.info(f"⚠️ 使用 V1 路径读取图片: {file_path}")
                        return base64.b64encode(f.read()).decode('utf-8')
                else:
                    raise ValueError(f"Image file not found: {file_path}")
            else:
                raise ValueError(f"Invalid /storage/ path format: {opening_image_url}")

        elif opening_image_url.startswith('http'):
            # HTTP URL
            with httpx.Client(timeout=30) as client:
                response = client.get(opening_image_url)
                response.raise_for_status()
                return base64.b64encode(response.content).decode('utf-8')

        elif opening_image_url.startswith('data:image'):
            # 已经是 base64
            return opening_image_url.split(',')[1]

        else:
            raise ValueError(f"Unsupported image format: {opening_image_url[:50]}")
    
    def _compress_image_base64(self, image_base64: str, max_size_bytes: int) -> str:
        """压缩 base64 图片，确保不超过指定大小"""
        try:
            # 解码 base64
            image_data = base64.b64decode(image_base64)
            img = Image.open(BytesIO(image_data))
            
            # 转换为 RGB（如果是 RGBA）
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 逐步压缩
            quality = 85
            max_dimension = 2048  # 最大尺寸
            
            while True:
                # 调整尺寸
                if max(img.size) > max_dimension:
                    ratio = max_dimension / max(img.size)
                    new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                    logger.info(f"调整尺寸到: {new_size}")
                
                # 压缩质量
                output = BytesIO()
                img.save(output, format='JPEG', quality=quality, optimize=True)
                compressed_data = output.getvalue()
                compressed_b64 = base64.b64encode(compressed_data).decode('utf-8')
                
                if len(compressed_b64) <= max_size_bytes or quality <= 50:
                    logger.info(f"压缩完成: {len(compressed_b64) / 1024 / 1024:.2f} MB, quality={quality}")
                    return compressed_b64
                
                quality -= 10
                if quality < 50:
                    # 如果质量已经很低，进一步缩小尺寸
                    max_dimension = int(max_dimension * 0.8)
                    if max_dimension < 512:
                        logger.warning("图片压缩到最小尺寸，仍可能过大")
                        return compressed_b64
                        
        except Exception as e:
            logger.error(f"图片压缩失败: {e}，使用原始图片")
            return image_base64
    
    def _max_tokens_for_segments(self, segment_count: int) -> int:
        """
        根据段数计算所需的 max_tokens
        
        段数越多，JSON 输出越长（每段包含 crucial/crucial_zh/action/action_zh/sound/sound_zh 等字段）。
        此前 6–8 段用 4000、≤5 用 5000，导致 7 段时被截断（只生成 5 段后输出被切断）。
        """
        # 每段约 500–800 tokens，留足余量
        token_map = {
            3: 4000,
            4: 4500,
            5: 5000,
            6: 6000,
            7: 7000,
            8: 8000,
        }
        return token_map.get(segment_count, 5000)
    
    def _parse_response(self, response_text: str) -> List[Dict]:
        """解析 API 响应"""
        # 提取 JSON
        original_text = response_text
        if '```json' in response_text:
            json_start = response_text.find('```json') + 7
            json_end = response_text.find('```', json_start)
            if json_end == -1:
                # 如果没有找到结束标记，尝试找到文本末尾
                json_end = len(response_text)
            response_text = response_text[json_start:json_end].strip()
        elif '```' in response_text:
            json_start = response_text.find('```') + 3
            json_end = response_text.find('```', json_start)
            if json_end == -1:
                json_end = len(response_text)
            response_text = response_text[json_start:json_end].strip()
        
        # 尝试修复不完整的 JSON（如果以 [ 开头但没有 ] 结尾，尝试补全）
        if response_text.strip().startswith('[') and not response_text.strip().endswith(']'):
            logger.warning("检测到不完整的 JSON 响应，尝试修复...")
            # 尝试找到最后一个完整的对象
            last_brace = response_text.rfind('}')
            if last_brace > 0:
                response_text = response_text[:last_brace + 1] + ']'
                logger.info("已尝试修复 JSON：补全结束括号")
            else:
                logger.error(f"无法修复 JSON，原始响应长度: {len(original_text)}")
                logger.error(f"响应前500字符: {original_text[:500]}")
                raise ValueError(f"JSON 响应不完整，无法解析")
        
        try:
            storyboards = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}")
            logger.error(f"尝试解析的文本长度: {len(response_text)}")
            logger.error(f"文本前500字符: {response_text[:500]}")
            logger.error(f"文本后500字符: {response_text[-500:]}")
            # 尝试更宽松的解析：查找第一个 [ 和最后一个 ]
            if '[' in response_text and ']' in response_text:
                first_bracket = response_text.find('[')
                last_bracket = response_text.rfind(']')
                if first_bracket < last_bracket:
                    try:
                        response_text = response_text[first_bracket:last_bracket + 1]
                        storyboards = json.loads(response_text)
                        logger.warning("通过提取 JSON 数组部分成功解析")
                    except:
                        raise ValueError(f"JSON 解析失败: {e}") from e
                else:
                    raise ValueError(f"JSON 解析失败: {e}") from e
            else:
                raise ValueError(f"JSON 解析失败: {e}") from e
        
        if not isinstance(storyboards, list):
            raise ValueError(f"Expected list, got {type(storyboards).__name__}")
        # 不再强制检查段数，因为段数是动态的

        return storyboards

    def _construct_full_prompt(self, segment: Dict) -> str:
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
    
    def _generate_mock_storyboard(self, scene_description: str, segment_count: int = 5, segment_durations: Optional[List[int]] = None) -> List[Dict]:
        """生成 Mock 分镜脚本"""
        # 根据段数生成模板
        templates = [
            {"type": "intro", "action": "宠物坐在餐桌前，好奇地看向镜头，耳朵竖起", "sound": "欢快BGM开始"},
        ]
        # 添加吃播段（根据段数动态生成）
        eating_actions = [
            "宠物凑近食物，闻了闻，开始品尝第一口",
            "宠物大口吃着，表情满足，尾巴轻轻摇摆",
            "宠物抬头看镜头，嘴角有食物残渣，可爱地舔嘴",
            "宠物继续享用美食，偶尔停下来喝水",
            "宠物吃完最后一口，满意地打了个小嗝",
            "宠物继续享受美食，表情越来越满足",
        ]
        # 吃播段数 = 总段数 - 2（intro + outro）
        eating_count = max(1, segment_count - 2)
        for i in range(eating_count):
            templates.append({
                "type": "eating",
                "action": eating_actions[i % len(eating_actions)],
                "sound": ["咀嚼声", "满足的叫声", "舔舐声", "喝水声", "打嗝声", "享受声"][i % 6]
            })
        templates.append({"type": "outro", "action": "宠物心满意足地看向镜头，用爪子擦擦嘴", "sound": "温馨BGM结束"})
        
        default_duration = 8
        storyboards = []
        for i, template in enumerate(templates[:segment_count]):
            storyboards.append({
                "id": f"mock_seg_{i}_{os.urandom(4).hex()}",
                "segment_index": i,
                "segment_type": template["type"],
                "crucial": f"Scene {i+1} key moment",
                "crucial_zh": f"场景{i+1}的关键画面",
                "action": template["action"],
                "action_zh": template["action"],
                "sound": template["sound"],
                "sound_zh": template["sound"],
                "prompt": f"[关键] 场景{i+1} [动作] {template['action']} [音效] {template['sound']}",
                "status": "pending",
                "video_url": None,
                "first_frame_url": None,
                "last_frame_url": None,
                "duration_sec": 8  # 固定8秒
            })
        
        return storyboards


# Singleton instance
_storyboard_service = None


def get_storyboard_service() -> Optional[StoryboardService]:
    """获取或创建 Storyboard 服务单例"""
    global _storyboard_service
    if _storyboard_service is None:
        try:
            _storyboard_service = StoryboardService()
        except Exception as e:
            logger.warning(f"StoryboardService not available: {e}")
            return None
    return _storyboard_service
