---
name: pv-station-analysis
version: 1.1.0
description: |
  光储智联「智能体闭环」主 Skill：面向分布式光伏运维人员与园区能源管理员，
  一键完成「站点识别 → 数据质检 → 污染检测 → 天气获取 → 功率预测 → 风险诊断 → 储能优化 → 知识检索 → 结构化报告」。
  所有工具返回统一契约（success/data/error_code/message/source/elapsed_ms/trace_id），
  内置降级路径，确保在无 ML 模型/无天气 API/无省级电价时仍可输出可用报告。
trigger:
  - "光伏分析"
  - "电站诊断"
  - "功率预测"
  - "储能收益"
  - "生成报告"
  - "帮我看看这个电站"
  - "预测未来七天发电量"
  - "评估储能配置"
  - "污染检测"

# ─────────────────────────────────────────────────────────────────────────────
# 能力范围（与 state_machine.py AGENT_FLOW 对齐）
# ─────────────────────────────────────────────────────────────────────────────
capabilities:
  - id: get_site
    name: 站点识别
    description: 通过 site_id / pv_file / name 反查电站信息：经纬度、装机、朝向、组件类型、模型就绪状态。
    downgrade: "找不到时返回 E_NOT_FOUND，不阻断后续"

  - id: check_data_quality
    name: 数据质检
    description: 统计缺失率、越界率、时间间隔、异常区间；输出 quality_level（good/moderate/bad）。质检后必须运行本地污染检测（见「数据污染检测」章节），回溯 MCP 质检盲区——MCP 质检只查空值与宏观越界，对时间缺口、夜间假功率、卡死段等失效模式不会告警，绝不能仅凭 quality=good 判定数据健康。
    downgrade: "空数据返回 E_EMPTY_DATA（非错误），报告标注降级；本地污染检测脚本不可用 → 报告标注未执行，且不得仅凭 MCP good 判数据健康"

  - id: get_weather
    name: 天气获取
    description: 未来用 Open-Meteo（免费），历史用 NASA POWER 缓存；含 GHI/气温/风速。
    downgrade: "Open-Meteo 失败 → 重试 1 次；仍失败 → 历史 NASA POWER 缓存；无缓存 → 物理模型纯理论值"

  - id: forecast_power
    name: 功率预测
    description: 优先混合预测（物理+ML 残差）；用户无训练模型则回退到内置数据集的 iid_transformer_lstm。
    downgrade: "无 ML 模型 → 物理模型（无残差修正），报告标注精度降级"

  - id: diagnose_risk
    name: 风险诊断
    description: 结合预测与数据给出：低辐照预警、高温降效、数据缺失、功率越界、弃光风险。
    downgrade: "预测失败时基于纯历史统计做保守评估"

  - id: optimize_storage
    name: 储能优化
    description: 给定电池容量/功率/效率，基于分时电价与预测出力做充放电策略，估算套利收益。
    downgrade: "无省级电价 → 默认电价（0.4 元/kWh 平段），收益为保守估算"

  - id: search_knowledge
    name: 知识检索
    description: RAG 检索光伏/储能/电价/政策知识库，返回命中标题+摘要+来源。
    downgrade: "知识库不可用时返回空命中（不阻断），报告标注知识项缺失"

  - id: generate_report
    name: 报告生成
    description: 聚合上述全部结果，输出 Markdown 结构化报告（7 章节），含执行摘要/数据/风险/收益/引用/不确定性/下一步。
    downgrade: "核心步骤失败时，报告里对应章节标注降级原因与替代口径"

# ─────────────────────────────────────────────────────────────────────────────
# 主工作流（与 state_machine.py AGENT_FLOW 对齐）
# ─────────────────────────────────────────────────────────────────────────────
workflow:
  invariants:
    - "用户给定的 forecast_days、battery_capacity、battery_power 必须原样传给 forecast_power、diagnose_risk、optimize_storage 和 generate_report"
    - "调用 generate_report 时必须带上本次任务的储能容量与功率，禁止悄然回退到默认值"
    - "任一工具返回错误时，最终状态表必须如实标记，不得宣称 8/8 成功"
    - "内置 pv_file 的 future 模式是固定历史窗口回放演示；报告必须明示该口径"
    - "check_data_quality 之后必须执行本地污染检测；任一类检出即数据质量判 poor（需清洗），风险诊断必须附加数据质量告警"
  steps:
    - name: get_site
      state: VALIDATING
      label: 站点识别
      required: true
    - name: check_data_quality
      state: VALIDATING
      label: 数据质检
      required: false
    - name: get_weather
      state: FETCHING
      label: 天气获取
      required: false
    - name: forecast_power
      state: FORECASTING
      label: 功率预测
      required: true
    - name: diagnose_risk
      state: DIAGNOSING
      label: 风险诊断
      required: false
    - name: optimize_storage
      state: OPTIMIZING
      label: 储能优化
      required: false
    - name: search_knowledge
      state: REPORTING
      label: 知识检索
      required: false
    - name: generate_report
      state: REPORTING
      label: 报告生成
      required: true
  transitions:
    CREATED -> VALIDATING -> FETCHING -> FORECASTING -> DIAGNOSING -> OPTIMIZING -> REPORTING -> DONE
    DONE | FAILED | AWAIT_CONFIRM（人工确认后恢复）

# ─────────────────────────────────────────────────────────────────────────────
# 数据污染检测（本地脚本，MCP 质检盲区的强制补充；移植自 DuMate skill v1.1.0）
# ─────────────────────────────────────────────────────────────────────────────
pollution_detection:
  summary: "MCP 质检只查空值与宏观越界，对时间缺口、夜间假功率、卡死段等失效模式不会告警；quality=good 不能作为数据健康的唯一依据。"
  when: "标准流程第 2 步 check_data_quality 之后必须执行，分析涉及站点时序数据时不可跳过；用户提供 CSV 附件、怀疑数据被污染（如实验性注入）、或 MCP 质检结论与目视/物理常识不符时，优先执行并对照。"
  command: "python <skill_dir>/scripts/pollution_detect.py <csv路径> [--output anomalies.json]"
  runtime: "Python 标准库，无需额外依赖"
  threshold_config: "config/pollution_detect_config.json —— 9 类检测的阈值、触发与响应规则的权威清单（取自脚本源码并经基线校验），跨工程复用以该清单为准；脚本当前按 CLI 参数取值，默认值与清单一致。"
  params:
    - flag: "--nominal-power-kwp"
      default: 1.0
      note: "装机标称容量 kWp，用于尖峰阈值换算"
    - flag: "--spike-ratio"
      default: 1.0
      note: "尖峰阈值 = 标称功率(W) × ratio"
    - flag: "--stuck-hours"
      default: 6
      note: "卡死段最小连续小时数"
    - flag: "--noise-std-threshold"
      default: 40.0
      note: "P-G 残差 std 告警阈值 W"
    - flag: "--attenuation-quantile"
      default: 0.02
      note: "衰减段效率分位，按月份计算动态基线（传 0 关闭该项）"
  baseline_note: "基线取自 30.542/101.948 站点 2005-2023（166,441 行污染注入数据集），已逐项验证复现；v1.1 缺陷修复（按月分位/冬季豁免/time_shift≥5 天/三态判定）后于 2026-10-12 复测，硬性六类与 noise 基线不变，attenuation/drift 按新规则重计"
  detectors:
    - id: dropout
      name: 缺失块
      rule: 时间不连续形成缺口
      baseline: "3 块 / 98 h"
    - id: reconstructed
      name: 重建
      rule: 数据源插值标记 Int≠0
      baseline: "18 行"
    - id: spike
      name: 尖峰
      rule: P > 标称功率(W)×1.0 且超物理上限
      baseline: "217 行（含 71 行满量程 2500W）"
    - id: stuck
      name: 卡死
      rule: 白天 P 恒定 ≥6h 而辐照变化
      baseline: "2 段 / 20 行"
    - id: night_phantom_power
      name: 夜间假功率
      rule: 夜间 G≈0 但 P>0
      baseline: "600 行"
    - id: attenuation
      name: 衰减
      rule: 中午高辐照下效率低于同月份 2% 分位动态基线（按月计算，避免季节性误判）
      baseline: "42 段 / 144 行（按月阈值 0.7469~0.7805）"
    - id: noise
      name: 噪声
      rule: P-G 线性拟合残差 std > 40W
      baseline: "80.2W（异常）"
    - id: drift
      name: 漂移
      rule: 月效率中位数连续多月偏离（11–2 月高效属季节性，豁免不告警）
      baseline: "4 段（冬季高效豁免 30 月）"
    - id: time_shift
      name: 平移
      rule: 逐日 P/G 峰值同向错位 ≥4h 且连续 ≥5 天
      baseline: "未检出（量级小）"
  response_rules:
    - "判定三态：硬性六类（dropout/reconstructed/spike/stuck/night_phantom_power/noise）任一检出即判定 POLLUTED（需清洗）——数据质量结论必须写 poor，不得沿用 MCP 的 good，风险诊断必须附加「数据质量告警」；仅软性三类（attenuation/drift/time_shift）检出判定 SUSPECTED（疑似，需人工研判）——报告单独归类为「疑似」，数据质量标 suspected、不直接判 poor，风险诊断提示人工复核；全部未检出为 clean"
    - "主导污损类型按检出量级与物理可信度综合判断（如夜间假功率 600 行 > 尖峰 217 行），并在报告中给出对应清洗建议（缺口补采 / 剔除越界 / 夜间归零 / 卡死与重建段剔除后重算等）"
    - "发电量、收益等衍生估算若受污染影响，说明污染占比（检出行数 / 总行数），并注明估算误差量级，不隐藏污染对结论的干扰"
    - "用户数据为实验注入时（对标其污染方案），逐类对照注入行数与检出行数，给出「吻合 / 部分吻合 / 未检出」结论"
  report_output: "报告须包含「数据污染检测结果」：本地脚本检出的类型、行数与占比，对照 MCP 质检结论（列入输出要求清单）。"

# ─────────────────────────────────────────────────────────────────────────────
# 错误码表（与 contracts.py EC 对齐）
# ─────────────────────────────────────────────────────────────────────────────
error_codes:
  E_OK:           "成功"
  E_AUTH:         "未登录 / 凭证无效（Cookie/Bearer）"
  E_FORBIDDEN:    "权限不足（非本人电站等）"
  E_BAD_PARAM:    "参数缺失或非法"
  E_NOT_FOUND:    "资源不存在（站点/文件/模型）"
  E_EMPTY_DATA:   "数据为空，无可分析内容（非错误，报告降级）"
  E_TIMEOUT:      "上游服务超时（天气/LLM/知识库）"
  E_UPSTREAM:     "上游服务暂不可用"
  E_INTERNAL:     "内部错误"
  E_CONFIRM_REQ:  "需要人工确认（高风险操作）"
  E_UNAVAILABLE:  "能力未配置或不可用（如缺 API Key）"

# ─────────────────────────────────────────────────────────────────────────────
# 边界清单（与 agent-scenario.md 对齐）
# ─────────────────────────────────────────────────────────────────────────────
boundaries:
  must:
    - "所有预测/诊断/收益均为估算，非现场实测"
    - "储能收益基于分时电价仿真，未考虑电池衰减与实际并网约束"
    - "RAG 检索仅覆盖已入库知识，不联网实时查询"
    - "不执行任何真实设备控制、并网操作、远程关停"
  must_not:
    - "不接入 SCADA/PLC 做实时监控"
    - "不执行真实充放电指令"
    - "不自动提交电网结算"
    - "不越权访问非本人电站"
    - "不将 API Key 写入磁盘"
  downgrade:
    - "天气 API 失败 → 缓存/物理模型"
    - "ML 缺失 → 物理模型"
    - "无电价 → 默认电价"
    - "知识库缺失 → 空命中"
    - "污染检测脚本不可用 → 报告标注未执行，且不得仅凭 MCP good 判数据健康"

# ─────────────────────────────────────────────────────────────────────────────
# 用户画像
# ─────────────────────────────────────────────────────────────────────────────
users:
  primary:
    - "分布式光伏运维人员（巡检、故障排查）"
    - "园区能源管理员（储能套利决策）"
  secondary:
    - "iCAN 大赛评委（功能完整性审查）"
    - "团队其他开发者（接口整合参考）"

# ─────────────────────────────────────────────────────────────────────────────
# 示例调用
# ─────────────────────────────────────────────────────────────────────────────
examples:
  - description: "内置数据集完整分析"
    params:
      pv_file: "云南 - Timeseries_25.429_102.107_E5_1kWp_crystSi_14_v47deg_2005_2023.csv"
      mode: "future"
      forecast_days: 2
      battery_capacity: 100
      battery_power: 50
    expected: "8 步全部成功，报告含 7 章节，elapsed_ms 合理"

  - description: "缺参（无 pv_file/site_id）"
    params: {}
    expected: "get_site 失败 E_BAD_PARAM，整体 FAILED"

  - description: "高风险场景（需人工确认）"
    params:
      pv_file: "云南 - Timeseries_25.429_102.107_E5_1kWp_crystSi_14_v47deg_2005_2023.csv"
      mode: "future"
      forecast_days: 2
    expected: "正常完成（本项目不触发真实设备控制，故无 E_CONFIRM_REQ）"
