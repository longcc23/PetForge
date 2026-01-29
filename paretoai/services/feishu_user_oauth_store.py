"""
飞书用户 OAuth Token 存储（极简版）

用于云空间(Drive)操作切换为“用户身份”。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional, Any

import aiohttp
import logging

logger = logging.getLogger(__name__)


TOKEN_FILE = Path("./data/feishu_user_oauth_tokens.json")


@dataclass
class UserOAuthToken:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds
    scope: Optional[str] = None
    open_id: Optional[str] = None
    union_id: Optional[str] = None
    token_type: Optional[str] = None
    obtained_at: Optional[float] = None


class FeishuUserOAuthStore:
    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self, token_file: Path = TOKEN_FILE):
        self.token_file = token_file
        self._cache: Dict[str, UserOAuthToken] = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        if not self.token_file.exists():
            return
        try:
            raw = json.loads(self.token_file.read_text(encoding="utf-8"))
            for table_id, v in raw.items():
                self._cache[table_id] = UserOAuthToken(**v)
        except Exception:
            # 读取失败则忽略
            self._cache = {}

    def _save(self):
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        raw = {k: asdict(v) for k, v in self._cache.items()}
        self.token_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_token(self, table_id: str, token: UserOAuthToken):
        self._load()
        self._cache[table_id] = token
        self._save()

    def get_token(self, table_id: str) -> Optional[UserOAuthToken]:
        self._load()
        return self._cache.get(table_id)

    def clear_token(self, table_id: str):
        self._load()
        if table_id in self._cache:
            self._cache.pop(table_id, None)
            self._save()

    async def exchange_code_for_token(
        self,
        *,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> UserOAuthToken:
        """
        通过授权码换取 user_access_token。
        """
        url = f"{self.BASE_URL}/authen/v2/oauth/token"
        payload: Dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30, connect=10)) as session:
            # 飞书 OAuth token 接口更兼容 form 编码
            async with session.post(url, data=payload) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    raise Exception(f"OAuth token exchange failed ({resp.status}): {data}")
                # 兼容两种返回结构：
                # 1) 标准 OAuth：{"access_token": "...", "refresh_token": "...", "expires_in": 6900, ...}
                # 2) 飞书通用包装：{"code":0,"msg":"success","data":{...}}
                if isinstance(data, dict) and "error" in data:
                    raise Exception(f"OAuth token exchange failed: {data.get('error')}: {data.get('error_description')}")

                if isinstance(data, dict) and "code" in data and data.get("code") != 0:
                    raise Exception(f"OAuth token exchange failed: {data.get('msg')}")

                if isinstance(data, dict) and data.get("access_token"):
                    d = data
                elif isinstance(data, dict) and isinstance(data.get("data"), dict):
                    d = data.get("data", {}) or {}
                else:
                    d = {}

        access_token = d.get("access_token") or ""
        refresh_token = d.get("refresh_token") or ""
        if not access_token:
            logger.error(f"OAuth token exchange missing access_token: raw={data}, extracted={d}")
            raise Exception("OAuth 换取 token 失败：返回缺少 access_token，请检查应用 OAuth 配置/权限后重试")

        expires_in = float(d.get("expires_in") or d.get("expire") or 7200)
        now = time.time()
        return UserOAuthToken(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=now + expires_in - 60,
            scope=d.get("scope"),
            open_id=d.get("open_id"),
            union_id=d.get("union_id"),
            token_type=d.get("token_type"),
            obtained_at=now,
        )

    async def refresh_access_token(
        self,
        *,
        refresh_token: str,
        client_id: str,
        client_secret: str,
    ) -> UserOAuthToken:
        url = f"{self.BASE_URL}/authen/v2/oauth/token"
        payload: Dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30, connect=10)) as session:
            async with session.post(url, data=payload) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    raise Exception(f"OAuth token refresh failed ({resp.status}): {data}")
                if isinstance(data, dict) and "error" in data:
                    raise Exception(f"OAuth token refresh failed: {data.get('error')}: {data.get('error_description')}")

                if isinstance(data, dict) and "code" in data and data.get("code") != 0:
                    raise Exception(f"OAuth token refresh failed: {data.get('msg')}")

                if isinstance(data, dict) and data.get("access_token"):
                    d = data
                elif isinstance(data, dict) and isinstance(data.get("data"), dict):
                    d = data.get("data", {}) or {}
                else:
                    d = {}

        new_access_token = d.get("access_token") or ""
        if not new_access_token:
            logger.error(f"OAuth token refresh missing access_token: raw={data}, extracted={d}")
            raise Exception("OAuth 刷新 token 失败：返回缺少 access_token")

        expires_in = float(d.get("expires_in") or d.get("expire") or 7200)
        now = time.time()
        return UserOAuthToken(
            access_token=new_access_token,
            refresh_token=d.get("refresh_token") or refresh_token,
            expires_at=now + expires_in - 60,
            scope=d.get("scope"),
            open_id=d.get("open_id"),
            union_id=d.get("union_id"),
            token_type=d.get("token_type"),
            obtained_at=now,
        )

    async def get_valid_access_token(self, *, table_id: str, client_id: str, client_secret: str) -> Optional[str]:
        tok = self.get_token(table_id)
        if not tok:
            logger.info(f"[OAuth] 未找到 table_id={table_id} 的 token")
            return None
        now = time.time()
        logger.info(f"[OAuth] 找到 token: expires_at={tok.expires_at}, now={now}, diff={tok.expires_at - now:.0f}s")
        if tok.access_token and now < tok.expires_at:
            logger.info(f"[OAuth] token 有效，直接返回")
            return tok.access_token
        if not tok.refresh_token:
            logger.info(f"[OAuth] token 已过期且无 refresh_token，返回 None")
            return None
        logger.info(f"[OAuth] token 已过期，尝试刷新...")
        new_tok = await self.refresh_access_token(
            refresh_token=tok.refresh_token,
            client_id=client_id,
            client_secret=client_secret,
        )
        self.set_token(table_id, new_tok)
        return new_tok.access_token


_global_store: Optional[FeishuUserOAuthStore] = None


def get_feishu_user_oauth_store() -> FeishuUserOAuthStore:
    global _global_store
    if _global_store is None:
        _global_store = FeishuUserOAuthStore()
    return _global_store

