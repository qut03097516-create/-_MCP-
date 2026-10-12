# UI 方案版本记录

每次界面改版记录于此，供最终选型对比。

---

## 方案 A — MiMo Desktop 蓝色浅色（v1）

**状态**: 已完成（历史版本）

| 项目 | 值 |
|------|-----|
| 背景 | `#f5f6f7` |
| 卡片 | `#ffffff` |
| 主色 | `#3370ff`（MiMo 蓝） |
| 文字 | `#1f2329` |
| 次要文字 | `#646a73` |
| 边框 | `#dee0e3` |
| 错误 | `#e34d59` |
| 成功 | `#2ea44f` |

**布局**: 紧凑 h-14 导航、Hero + 统计卡 + 编号功能行（section-row）
**动效**: 少量（淡入、hover 变色）
**参考**: mimo.xiaomimimo.com/desktop/ 配色 + 布局

---

## 方案 B — 米色暖调 + 丰富动效（v2）

**状态**: 已完成（历史版本）

| 项目 | 值 |
|------|-----|
| 背景 | `#f8f5f0`（暖奶油） |
| 卡片 | `#fffcf7`（暖白） |
| 主色 | `#c8956c`（琥珀金） |
| 辅色 | `#7c9a73`（鼠尾草绿） |
| 文字 | `#3d3530`（暖棕） |
| 次要文字 | `#6b615a` |
| 弱文字 | `#9e948a` |
| 边框 | `#e5ddd2` |
| 错误 | `#d4644a` |

**布局**: 顶栏导航 + 各页独立内容区
**动效**: 打字机、stagger、浮动光球、shimmer 扫光、玻璃 tilt
**问题**: 偏「玻璃光面」，用户希望改为磨砂质感

---

## 方案 C — 磨砂暖调 + 豆包式对话布局（v3）★ 当前

**状态**: 已完成（当前生效）

| 项目 | 值 |
|------|-----|
| 背景 | `#f8f5f0` + 细噪点纹理 |
| 卡片 | `#fffcf7` 哑光 + 噪点（非玻璃） |
| 主色 | `#c8956c` 平实色块（无渐变扫光） |
| 辅色 | `#7c9a73` |
| 文字 | `#3d3530` |
| 边框 | `#e5ddd2` |

**材质**:
- 去掉按钮 shimmer 扫光、玻璃高光描边、亮面渐变
- 卡片/登录卡：哑光暖白 + 噪点纹理 + 细边框 + 轻阴影
- 顶栏：高不透明磨砂（blur 降低），不发亮

**布局（参考豆包/DeepSeek，工作台壳）**:
- **展示页 `/home`**：保留轻量顶栏 Layout；Hero + CTA「开始对话」→ `/app`
- **工作台 `/app*`**（`AppShell` 统一壳，全侧边栏）：
  - 左栏：品牌、新对话、AI 设置、功能入口（对话/数据/导入/预测/知识库/场景/个人）、会话历史、用户
  - 功能页路由：`/app` 对话、`/app/dataset`、`/app/import`、`/app/predict`、`/app/kb`、`/app/kb/note/:slug`、`/app/scenes`、`/app/profile`
  - 对话主区：标题顶栏、上下文栏、消息流、底部大输入框 + 快捷建议（`Query` 只渲染主区）
  - 其他功能页：壳内滚动内容区，侧栏切换不丢会话
- 旧路径 `/query` `/data-explore` 等已直接改掉，不做 redirect

**动效**: stagger 入场、计数、浮动装饰；去掉反光类效果

---

## 数据集页图表修复（方案 C 增量 · 数据正确性）

**状态**: 已完成（当前生效）

| 文件 | 变更 |
|------|------|
| `frontend/src/pages/DataExplore.tsx` | 处理选项接入 `processedData`；缺失率/相关矩阵/注释/区间标签修正；箱线图与直方图按量纲拆分 |

要点：
- `aggMode` / `removeNight` / `removeOutliers` 真正作用于统计卡与全部分析 Tab
- 缺失只认 `null` / `''` / `NaN`（0 不再算缺失）；删除写死假回归注释
- 相关系数保留符号，轴与热力图色标 `[-1, 1]`；方差为 0 返回 0，避免 NaN
- 峰值/夜间注释按真实数据与分类轴字符串定位；区间标签改为真实阈值
- 质量箱线图、分布直方图拆成三列独立子图；过滤后无数据给出空态与重置入口

---

## 首页「个人资料」导航修复

**状态**: 已完成（历史）

| 文件 | 变更 |
|------|------|
| `frontend/src/pages/Home.tsx` | `featurePathMap` 补上 `个人资料 → /app/profile` |

要点：
- 后端 `/api/home/features` 返回 `page: "个人资料"`，此前映射缺失，点击回落 `/home`，表现为导航失效
- 顶栏头像 → `/app/profile` 与 AppShell 菜单 → `/app/profile` 原本正常，未改动

---

## 应用场景本地化 P0 + 导入隐私（方案 C 增量）

**状态**: 已完成（当前生效）

| 文件 | 变更 |
|------|------|
| `frontend/src/api/index.ts` | `siteApi.setVisibility`；`list(includeShared)` |
| `frontend/src/pages/Application.tsx` | 用户电站+演示源合并选择；`site_id` 分析；尖峰平谷/上网自定义电价；`?site=` 导入联动；数据可用性与隐私徽标 |
| `frontend/src/pages/DataImport.tsx` | 隐私协议说明；私有/分享切换；建站可选分享；导入成功跳转 `/app/scenes?site=` |
| `backend/api/application.py` | 策略导出电量；`feed_in` 计入净收益；用户站日期无交集时回退全量 |

要点：
- 数据默认 `visibility=private`，仅所有者可写；分享后他人只读分析
- 光储协同与收益预估均可改本地电价并可保存到电站
- 导入成功卡片直达应用场景并带上 `site` 参数
- `tsc --noEmit` 通过；`npm run build` 无警告（主包约 280kB，plotly 独立 chunk）

---

## 应用场景「收益测算」白屏修复

**状态**: 已完成（历史）

| 文件 | 变更 |
|------|------|
| `frontend/src/pages/Application.tsx` | `renderRevenueTab` 内 `result.comparison` 改为 `result?.comparison`；`period_energy_kwh` / `daily` 空值防护 |

要点：
- 未点「生成策略」时 `result === null`，点「收益测算」Tab 读 `result.comparison` 抛 TypeError，React 整树卸载表现为全白
- 与场景对比区空态并存：无策略时仍展示 RevenueEstimateCard + 默认场景对比
- `utils/site_store.py` 同步修复：`create_site(..., share_user_ids)`、`list_sites`/`get_site_readable` 按 `public|shared|custom` 过滤（分享增强进行中）
- 验证：`tsc --noEmit` EXIT:0；`npm run build` EXIT:0

---

## 全站选站联动 + 指定用户分享 + 对话/诊断（A–E）

**状态**: 已完成（当前生效）


| 文件 | 变更 |
|------|------|
| `utils/site_store.py` | `site_shares` 表；`visibility=private\|public\|custom`（旧 `shared`→`public`）；`set_share_targets` / `get_site_readable` |
| `backend/api/sites.py` | VisibilityUpdate 支持 `share_user_ids`；`GET /sites/shareable-users`、`GET /sites/{id}/shares`；create 接分享目标 |
| `backend/api/query.py` | `user_site:{id}` 解析 → 发电摘要 + hybrid 模型指标（config.pkl RMSE/MAE/改善%）；`/query/sites` 返回用户站 |
| `backend/api/data_import.py` | `generation_summary` 轻量诊断：覆盖缺口/超容/零出力日/日间骤降 |
| `backend/api/prediction.py` | hybrid 预报 `get_site_readable`（分享只读可算）；训练仍仅 owner |
| `frontend/src/store/siteStore.ts` | 统一站点 `user:{id}` / `demo:{file}` + `selectedKey`；默认 `includeShared` |
| `frontend/src/pages/Query.tsx` | 选站写回 siteStore；对话注入 `user_site:` |
| `frontend/src/pages/Prediction.tsx` | 演示站与 siteStore 联动；用户站切 hybrid Tab |
| `frontend/src/pages/DataExplore.tsx` | 本地演示站与 siteStore 联动 |
| `frontend/src/pages/Application.tsx` | 读/写 siteStore；隐私文案 public/custom；`visText`/`visLabel` |
| `frontend/src/pages/DataImport.tsx` | 诊断列表 UI；建站 `public`；选站回写 store；三档隐私切换 |
| `frontend/src/components/HybridForecast.tsx` | 选站回写 siteStore；公共/指定/只读徽标 |

要点：
- 分享语义：默认 private；public=登录用户只读；custom=site_shares 指定用户只读；写仅 owner
- 对话上下文：数据摘要（含电价/异常提示）+ hybrid 是否训练及验证指标
- 密度诊断入口：导入页 SummaryPanel 展示 diagnosis（error/warning/info）
- 经典预测/本地分析仅演示 CSV；用户站走混合预测/对话/场景
- 验证：`tsc --noEmit` EXIT:0；`npm run build` EXIT:0；后端 6 文件 `ast.parse` OK

---

## 指定用户分享：搜索选人（不再整表勾选）

**状态**: 已完成（当前生效）

| 文件 | 变更 |
|------|------|
| `frontend/src/pages/DataImport.tsx` | `VisibilityToggle` 改为搜索用户名添加；已选标签可移除；不默认展示全部用户 |

要点：
- 点「指定用户分享」打开面板：仅搜索框 + 提示，输入用户名后展示匹配结果（最多 8 条，排除已选）
- 点击结果加入「已选」标签，可 × 移除；保存时写 `share_user_ids`
- 已是 custom 的站点打开时从 `/sites/{id}/shares` 回填已选用户名标签
- 验证：`tsc --noEmit` EXIT:0

---

## 控制台：异步刷新 + 刷新状态 / 重新构建

**状态**: 已完成（当前生效）

| 文件 | 变更 |
|------|------|
| `console/app.py` | 状态采集移出主线程；顶栏「刷新状态」「重新构建」；表格内容未变不重建 |
| `console/process_mgr.py` | PID/健康短缓存；`rebuild_frontend`（npm run build）；`invalidate_status_cache` |
| `console/paths.py` | 局域网 IP 30s 缓存 |
| `console/stats.py` | 在线校验解析 `last_seen` + 仅启用用户；overview 单次 users 查询 |

要点：
- 卡顿根因：每 2s 在 UI 线程同步跑 netstat / 健康检查 / SQLite / getaddrinfo 并整表重建
- 修复：后台线程采集 → UI 队列回写；轮询 3s；`netstat`/健康/局域网短缓存；内容相同跳过 Tree 重建
- 「刷新状态」强制失效缓存并立即重采；「重新构建」后台执行 `frontend` 的 `npm run build`
- 在线：`is_active=0` 不计在线；时间解析窗口 5 分钟（时钟超前 30s 容忍）
- 验证：4 文件 `ast.parse` OK；`is_user_online` 断言通过；`overview()` 可调用

---

## 彩蛋：贝塞尔曲线小鸭（Bezier Duck）

**状态**: 已完成（当前生效）

| 文件 | 变更 |
|------|------|
| `frontend/src/components/BezierDuck.tsx` | 新增：按课件公式绘制的小鸭弹层 + 三种触发 hook |
| `frontend/src/App.tsx` | 挂载 `useDuckHotkeys` / `useBrandClickEgg` / `<BezierDuck>` |
| `frontend/src/components/Layout.tsx`、`AppShell.tsx` | 品牌 Logo 加 `data-brand`（连点触发） |

要点：
- 曲线与**修正版**课件图一致：原梗图控制点与图形错位（右端 x=4.8 出框、眼睛被头弧穿过），改用拟合修正值
- r₁: (-1.39,-4)(-0.62,-2.27)(-0.29,-1.14)(-1.34,0.33)；r₂: →(3.17,0.30)；r₃: →(4.92,-4)；r₄: (-1.21,1.03)…
- 眼睛为椭圆 r₅/r₆：外 (0.28+0.56cos t, 1.80+0.77sin t)、内 (0.48+0.27cos t, 1.78+0.37sin t)；嘴 y=0.23 (-1.22≤x≤-0.16)
- 坐标映射 OX=3, OY=4（整数使网格对齐原点）；全部曲线落在 504×504 viewBox 内
- 触发：键盘依次输入 `duck`；连点左上角「☀ 光储智联」Logo 7 次（2.5s 窗口）；控制台 `__bezierDuck()`
- 打开时 stroke-dashoffset 逐段描线动画，眼睛延后淡入；Esc / 点遮罩关闭
- 弹层底部列出 B(t) 公式与全部控制点，还原课件排版
- 验证：Python PIL 按公式复绘比对形状一致；`tsc --noEmit` EXIT:0；`npm run build` EXIT:0


---

## 10-04 合并事故恢复（回放 9-23 ~ 9-28 编辑）

**状态**: 已完成（当前生效）

| 项目 | 说明 |
|------|------|
| 范围 | DataExplore/Application/DataImport/Query/Prediction/Home/HybridForecast/AppShell/App/Layout/api/vite.config、BezierDuck、siteStore、site_store、application/query/prediction/sites/data_import、start.bat、本文件 |
| 方法 | 从 trajectory 按序回放打包（9-23 03:40）后至合并（10-03）前的成功编辑；agent 增量（/agent 路由、agentApi、Bot 导航）重新叠加 |
| 保留 | auth/main/news_database/console（10-03 恢复态已验证）；被覆盖前文件备份于 `.restore_backup_1004/` |
| 验证 | `tsc --noEmit` EXIT:0；`npm run build` 20.9s；`py_compile` OK；import 75 routes；/api/sites 鉴权 401 正常 |


---

## 10-04 阶段三 RAG 接入：知识库页 RAG 索引状态卡

**状态**: 已完成（当前生效）

| 文件 | 变更 |
|------|------|
| `frontend/src/api/index.ts` | `kbApi` 新增 `health()`（GET /api/health，读取 rag 状态字段） |
| `frontend/src/pages/Knowledge.tsx` | 左栏统计下方新增「RAG 索引」状态卡：已加载时显示版本/块数/embedding 模型（绿点），未加载显示琥珀点与原因；挂载时随目录树一并拉取 |

- 依赖后端 `/api/health` 返回的 `rag: {loaded, version, chunk_count, embedding}`（M3.2，backend/main.py）
- 验证：`./node_modules/.bin/tsc --noEmit` EXIT:0

---

## 10-04 智能体工作台整合进 AI 问答页（双 Tab）

**状态**: 已完成（当前生效）

| 文件 | 变更 |
|------|------|
| `frontend/src/pages/Query.tsx` | 顶栏右侧新增「对话 / 智能体分析」分段切换；智能体视图内嵌 `<AgentWorkbench embedded>`；两视图用 hidden 保持挂载（切 Tab 不丢会话/轮询/报告）；`?tab=agent` 初始化视图；对话关联站点命中内置数据集时带入预选 |
| `frontend/src/pages/AgentWorkbench.tsx` | 新增 props：`embedded`（内嵌时隐藏页级大标题）、`initialPvFile`（任务未启动时预选数据集）；导出 `BUILTIN_DATASETS` |
| `frontend/src/App.tsx` | `/agent` 路由改为重定向 `/app?tab=agent`（老链接不断），不再独立挂 Layout |
| `frontend/src/components/Layout.tsx` | 导航移除「智能体工作台」独立入口（整合进「对话」页 Tab），清理 Bot 图标 import |

- 验证：`./node_modules/.bin/tsc --noEmit` EXIT:0；`npm run build` EXIT:0（37.68s）
- 浏览器冒烟（playwright + Edge/chromium，dev :3000 + 后端 :8000）：登录后 `/app` 顶栏双 Tab 正常；切「智能体分析」内嵌工作台渲染、切回「对话」状态保留；`/agent` 重定向落 `/app?tab=agent`；真实任务 配置→时间线→AWAIT_CONFIRM 确认门→DONE→七节报告全链路通过（总耗时 17.6s，0 console error）；截图见 `output/playwright/`

---

## 10-05 修复知识库页白屏（React #31 对象渲染崩溃）

**状态**: 已完成（当前生效）

| 文件 | 变更 |
|------|------|
| `frontend/src/pages/Knowledge.tsx` | RAG 索引状态卡：`embedding` 类型改为 `string \| {model, dim, normalization}` 对象兼容，新增 `fmtEmbedding()` 格式化；原实现把对象直渲染触发 React #31，导致 `/app/kb` 整页白屏 |

- 根因：`/api/health` 的 `rag.embedding` 返回对象，前端按字符串渲染 → Minified React error #31（已在 8000 端口复现，2 console error）
- 验证：`tsc --noEmit` EXIT:0；`npm run build` EXIT:0；浏览器新开标签实测 `/app/kb` 列表与 `/app/kb/note/:slug` 详情均正常渲染、0 console error；`/api/health`、`/api/kb/tree`、`/api/kb/note` 均 200
