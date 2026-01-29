# PetForge 批量处理工坊

> **版本**: 2.0  
> **描述**: 基于飞书多维表格的批量视频生产平台，专为宠物类短视频内容的规模化生产而设计。

---

## 核心特性

- **批量处理**: 一键生成多个视频的分镜脚本和视频段
- **飞书集成**: 以飞书多维表格为协作中心，支持团队分工
- **AI 驱动**: 使用 DeepSeek 生成分镜，VEO 生成视频
- **四端同步**: 数据库、本地文件、飞书、前端数据一致

---

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone https://github.com/longcc23/PetForge.git
cd PetForge

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # macOS/Linux

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入必要的 API Key
```

**必需配置项**:
- `DEEPSEEK_API_KEY`: DeepSeek API 密钥（用于分镜生成）
- `DB_URL`: 数据库连接字符串

### 3. 启动后端

```bash
cd paretoai
python -m uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### 4. 启动前端

```bash
cd video-studio
npm install
npm run dev
```

访问 http://localhost:5173/batch 即可使用批量处理工坊。

---

## 项目结构

```
PetForge/
├── paretoai/                 # 后端 (FastAPI)
│   ├── routes/batch.py       # 批量处理 API
│   ├── services/             # 业务服务层
│   │   ├── feishu_bitable.py
│   │   ├── storyboard_service.py
│   │   └── video_segment_service.py
│   ├── models.py             # 数据模型
│   └── prompts/              # 提示词模板
│
├── video-studio/             # 前端 (React + Vite)
│   └── src/
│       ├── pages/BatchPage.tsx
│       └── components/batch/
│
├── data/                     # 数据文件
├── docs/                     # 文档
└── requirements.txt          # Python 依赖
```

---

## 核心功能

| 功能 | 描述 |
|------|------|
| 飞书连接 | 连接飞书多维表格作为数据源 |
| 分镜生成 | 基于 LLM 批量生成视频分镜脚本 |
| 视频生成 | 调用 VEO API 生成各段视频 |
| 视频合并 | 将分段视频合成完整视频 |
| 同步回写 | 将结果同步到飞书/云盘 |

---

## 技术栈

**后端**:
- FastAPI + SQLModel
- DeepSeek API (LLM)
- Google VEO API (视频生成)

**前端**:
- React 19 + TypeScript
- Vite + TailwindCSS
- TanStack Table

---

## 文档

- [产品规格](docs/PETFORGE_PRODUCT_SPEC.md)
- [技术指南](docs/PETFORGE_TECHNICAL_GUIDE.md)
- [文件清单](docs/PETFORGE_FILES.md)

---

## License

MIT License
