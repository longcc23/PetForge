"""
Pareto AI API Server - 简化版
批量视频生产平台后端服务

核心功能：健康检查、批量处理、飞书图片代理
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse

# 简单的日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("paretoai")

# 创建 FastAPI 应用
app = FastAPI(
    title="PetForge Batch API",
    description="批量视频生产平台 API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 配置 - 允许前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite 前端
        "http://localhost:3000",  # 备用前端端口
        "*"  # 开发模式允许所有
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 导入并注册路由
try:
    from .routes import health_router, batch_router
    app.include_router(health_router)
    app.include_router(batch_router)
    logger.info("路由注册成功: health, batch")
except Exception as e:
    logger.error(f"路由注册失败: {e}")

# 静态文件服务
uploads_path = Path(os.getenv("LOCAL_STORAGE_PATH", "./data/uploads"))
uploads_path.mkdir(parents=True, exist_ok=True)

# ========== 飞书图片代理 ==========
@app.get("/proxy/image")
async def proxy_feishu_image(url: str):
    """
    代理飞书图片请求
    
    飞书图片需要 tenant_access_token 才能访问，
    前端无法直接访问，需要后端代理。
    
    Args:
        url: 飞书图片的原始 URL (URL encoded)
    """
    import aiohttp
    from urllib.parse import unquote
    
    try:
        # 解码 URL
        decoded_url = unquote(url)
        logger.info(f"[Proxy] 代理飞书图片: {decoded_url[:100]}...")
        
        # 获取飞书服务实例以获取 token
        from .routes.batch import _feishu_services
        
        # 尝试从任意已连接的服务获取 token
        token = None
        logger.info(f"[Proxy] 当前已连接的飞书服务: {list(_feishu_services.keys())}")
        
        for table_id, conn_info in _feishu_services.items():
            try:
                # _feishu_services 的值是字典，包含 "service" 键
                service = conn_info.get("service")
                if service:
                    token = await service._get_tenant_access_token()
                    if token:
                        logger.info(f"[Proxy] 成功从 table_id={table_id} 获取 token")
                        break
            except Exception as e:
                logger.warning(f"[Proxy] 从 table_id={table_id} 获取 token 失败: {e}")
                continue
        
        if not token:
            logger.warning("[Proxy] 无法获取飞书 token，尝试无认证访问")
        
        # 构建请求头
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        # 下载图片（减少超时到 10 秒，避免长时间阻塞）
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(decoded_url, headers=headers) as response:
                if response.status == 200:
                    content = await response.read()
                    content_type = response.headers.get("Content-Type", "image/jpeg")
                    
                    from fastapi.responses import Response
                    return Response(
                        content=content,
                        media_type=content_type,
                        headers={
                            "Cache-Control": "public, max-age=3600",
                            "Access-Control-Allow-Origin": "*"
                        }
                    )
                else:
                    logger.warning(f"[Proxy] 飞书图片请求失败: status={response.status}")
                    return JSONResponse(
                        status_code=response.status,
                        content={"error": f"飞书图片请求失败: {response.status}"}
                    )
    
    except asyncio.TimeoutError:
        logger.warning(f"[Proxy] 飞书图片请求超时 (10s): {url[:80]}...")
        return JSONResponse(
            status_code=504,
            content={"error": "飞书图片请求超时"}
        )
    except aiohttp.ClientError as e:
        logger.warning(f"[Proxy] 网络错误: {e}")
        return JSONResponse(
            status_code=502,
            content={"error": f"网络错误: {str(e)}"}
        )
    except Exception as e:
        logger.error(f"[Proxy] 代理异常: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

# ========== 静态文件服务 ==========
@app.get("/storage/{file_path:path}")
async def serve_storage_file(file_path: str):
    """
    提供存储文件访问
    支持两种路径格式：
    1. 直接路径：/storage/xxx.jpg
    2. 项目短路径：/storage/projects/{projectId}/xxx.jpg -> 搜索 data/uploads/projects/*/*/{projectId}/
    """
    try:
        logger.info(f"[Storage] 请求: {file_path}")
        
        # 先尝试直接路径（完整路径）
        full_path = uploads_path / file_path
        logger.info(f"[Storage] 尝试直接路径: {full_path.absolute()}, exists={full_path.exists()}")
        if full_path.exists() and full_path.is_file():
            logger.info(f"[Storage] 直接路径命中: {full_path}")
            return FileResponse(full_path)
        
        # 如果是项目路径格式 projects/{projectId}/xxx.jpg
        if file_path.startswith("projects/"):
            parts = file_path.split("/")
            logger.info(f"[Storage] 项目路径解析: parts={parts}")
            if len(parts) >= 3:
                project_id = parts[1]
                file_name = "/".join(parts[2:])
                
                # 在 data/uploads/projects/ 下搜索项目目录
                projects_base = uploads_path / "projects"
                logger.info(f"[Storage] 搜索项目: project_id={project_id}, file_name={file_name}, base={projects_base.absolute()}, exists={projects_base.exists()}")
                
                if projects_base.exists():
                    # 遍历日期目录和模板目录查找项目
                    for date_dir in projects_base.iterdir():
                        if date_dir.is_dir() and not date_dir.name.startswith('.'):
                            for template_dir in date_dir.iterdir():
                                if template_dir.is_dir() and not template_dir.name.startswith('.'):
                                    project_dir = template_dir / project_id
                                    if project_dir.exists():
                                        target_file = project_dir / file_name
                                        logger.info(f"[Storage] 检查: {target_file}, exists={target_file.exists()}")
                                        if target_file.exists() and target_file.is_file():
                                            logger.info(f"[Storage] ✅ 找到: {file_path} -> {target_file}")
                                            return FileResponse(target_file)
        
        logger.warning(f"[Storage] ❌ 文件不存在: {file_path}")
        return JSONResponse(
            status_code=404,
            content={"error": f"文件不存在: {file_path}"}
        )
    except Exception as e:
        logger.error(f"[Storage] 路由异常: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.on_event("startup")
async def startup():
    """启动事件"""
    logger.info("=" * 60)
    logger.info("PetForge Batch API 启动中...")
    logger.info("=" * 60)
    
    # 初始化数据库
    try:
        from .db import init_db
        init_db()
        logger.info("✓ 数据库初始化完成")
    except Exception as e:
        logger.warning(f"✗ 数据库初始化失败: {e}")
    
    # 恢复飞书连接
    try:
        from .routes.batch import _restore_feishu_connections
        await _restore_feishu_connections()
        logger.info("✓ 飞书连接恢复完成")
    except Exception as e:
        logger.warning(f"✗ 飞书连接恢复失败: {e}")
    
    logger.info("=" * 60)
    logger.info("服务器启动成功!")
    logger.info("API 文档: http://localhost:8000/docs")
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown():
    """关闭事件"""
    logger.info("服务器关闭中...")

# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理器"""
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "服务器内部错误", "detail": str(exc)}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
