# 光储智联 · MCP 后端最小运行包

- 版本：v1.0.1（与 DuMate Skill `pv-station-analysis-v1.1.0` 配套；技能更新于 2026-10-12）
- 打包日期：2026-10-10
- 内容：DuMate 所需的 **MCP 后端最小可运行集合**（不含 Web 前端与开发工程）

## 一、包内结构

```
光储智联_MCP后端/
├── backend/            FastAPI 后端 + MCP 适配层（/mcp 入口，8 个业务工具）
├── utils/              预测/物理/数据加载/站点存储等运行时模块
├── models/             已训练模型（云南、山东站点 cnn_lstm / iid_transformer_lstm 等）
├── data/               运行数据（pv_data.duckdb、weather.duckdb、RAG 索引 data/rag、知识库 vault 等）
├── skills/pv-station-analysis/SKILL.md   DuMate 技能源文件（v1.1.0，含数据污染检测）
├── skills/pv-station-analysis/scripts/   9 类污染检测脚本 pollution_detect.py（纯标准库）
├── skills/pv-station-analysis/config/    污染阈值与响应规则清单 pollution_detect_config.json
├── requirements.txt    Python 依赖
├── .env.example        环境变量示例（真实 .env 含密钥，按安全规范未打包）
├── mcp_test.py         MCP 全链路自检脚本（8 工具验证）
└── 启动MCP后端.bat      一键启动（端口 8000）
```

## 二、启动步骤

1. 安装依赖（建议 Python 3.12）：
   ```
   pip install -r requirements.txt
   ```
2. 配置密钥（二选一）：
   - 直接运行 `启动MCP后端.bat`（未配置时自动生成临时密钥）；
   - 或设置系统环境变量 `APP_SECRET_KEY`（推荐持久化）：
     ```
     powershell -Command "$b=New-Object byte[] 48;[Security.Cryptography.RandomNumberGenerator]::Fill($b);[Convert]::ToBase64String($b)"
     ```
3. 双击 `启动MCP后端.bat`，看到 `后端已就绪` 即成功。
4. 自检：`python mcp_test.py`，应输出 `工具数=8`、`get_site success=True`、`全链路验证通过`。

## 三、DuMate 侧对接

- MCP 地址：`http://127.0.0.1:8000/mcp`（Streamable HTTP）
- 鉴权：先调 `POST /api/auth/login` 获取 Bearer Token
- 技能：安装本目录下 `pv-station-analysis-v1.1.0.zip`（SKILL.md v1.1.0 + 污染检测脚本与配置；由 `skills/pv-station-analysis/` 打出）

## 四、已剔除的内容（及原因）

| 剔除项 | 原因 |
|---|---|
| `frontend/`（约 467 MB） | Web 前端构建与源码，MCP 运行不需要 |
| `rag/`（约 91 MB） | RAG 管道与评测脚本；运行时索引已含于 `data/rag/` |
| `.git/`、`.mimocode/`、`logs/`、缓存 | 版本库与运行痕迹 |
| `.env` | **含真实密钥，按安全规范禁止入包**（见 `backend/api/auth.py`） |
| `console/`、`docs/`、`evaluation/`、`tests/` | 控制台、文档、评测与测试工程，非运行时依赖 |
| `ai_sessions.json`、`__pycache__`、`*.log` | 运行状态与编译缓存 |

## 五、安全说明

- 本包不含任何 API Key / 签名密钥；拿到包后必须配置 `APP_SECRET_KEY` 才能启动（代码强制）。
- `data/pv_system.db` 含演示账号数据，部署到公网前请修改默认账号口令。
