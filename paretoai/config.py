"""
配置管理模块
从环境变量加载配置
"""
import os
from pathlib import Path
from typing import Optional, List


class Settings:
    """应用配置"""
    
    def __init__(self):
        # 加载 .env 文件（如果存在）
        self._load_env_file()
        
        # 环境
        self.environment = os.getenv("ENVIRONMENT", "development")
        
        # 数据库
        self.db_url = os.getenv("DB_URL", "sqlite:///./data/petforge.db")
        
        # DeepSeek API
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        
        # Nano (图片生成) API  
        self.nano_api_key = os.getenv("NANO_API_KEY", "")
        self.nano_base_url = os.getenv("NANO_BASE_URL", "https://api.nano.com")
        self.nano_model = os.getenv("NANO_MODEL", "nano-1")
        
        # Google VEO API
        self.google_api_key = os.getenv("GOOGLE_API_KEY", "")
        self.veo_project_id = os.getenv("VEO_PROJECT_ID", "")
        
        # 存储
        self.local_storage_path = os.getenv("LOCAL_STORAGE_PATH", "./data/uploads")
        
        # CORS
        allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "*")
        if allowed_origins_str == "*":
            self.allowed_origins = ["*"]
        else:
            self.allowed_origins = [origin.strip() for origin in allowed_origins_str.split(",")]
        
        # API Keys（用于认证）
        api_keys_str = os.getenv("API_KEYS", "")
        self.api_keys = [key.strip() for key in api_keys_str.split(",") if key.strip()]
    
    def _load_env_file(self):
        """加载 .env 文件"""
        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        # 只在环境变量不存在时设置
                        if key and not os.getenv(key):
                            os.environ[key] = value


# 全局配置实例
settings = Settings()
