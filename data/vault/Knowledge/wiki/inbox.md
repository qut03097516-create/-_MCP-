# 📥 待编译清单（Inbox）

> **工作流规则（强制）**：
> 1. 只要 `raw/` 新增文件，就必须在本页"待编译"区登记一条（文件名 + 来源链接 + 登记日期）。
> 2. LLM 按 `prompts/01-compile.md` 编译后，勾选该条并移入末尾"已完成"区。
> 3. 本页是 LLM 的待办入口：编译时只处理"待编译"区条目，不处理已完成区。

## 待编译

> [!note] 2026-09-17 更新：11 条 Crossref 占位条目已按 `prompts/06-historical-backfill.md` 回填正文（8 条取得开放源摘要，3 条仅元数据保留待确认），全部移入"已完成"区。

> [!note] 2026-09-22 更新：第二批历史知识补全（主题=电价与收益）新增 3 条 raw 并直接编译完成，见"已完成"区；本次按 `prompts/06-historical-backfill.md` 执行，不并入每日 Horizon 链路。
> [!note] 2026-09-27 更新：04A 批量扩容 Batch 1/2/3/4/5/6（60 份 raw）全部编译完成，移入"已完成"区。待编译区已清空。

> [!note] 2026-10-03 更新：Horizon 摄取 1 份新简报（horizon-2026-10-03-en.md），编译完成移入"已完成"区。待编译区已清空。

## 已完成

- [x] `raw/horizon/horizon-2026-10-03-en.md`（2026-10-03 编译 → sources +1：[[2026-10-03_美国组件质量挑战与采购政策]]；concepts 无新增；topics 更新 [[行业动态与政策]]、[[光伏组件]]）
  - 来源：Horizon AI 每日简报（1 条入选新闻，评分 6.0/10，信源 rss/PV-Tech）

- [x] `raw/horizon/horizon-2026-10-01-en.md`（2026-10-01 编译 → sources +2：[[2026-10-01_通威490W-TOPCon住宅组件24.5效率]]、[[2026-10-01_Actis印度3GW可再生能源平台Leo]]；concepts 更新 [[TOPCon]]（通威 TNC 2.0 FULLX G12R-48 住宅组件 490W/24.5%、零间隙设计）；topics 更新 [[行业动态与政策]]）
  - 来源：Horizon AI 每日简报（2 条入选新闻，评分 6.0/5.0，信源 rss/PV-Tech）

- [x] `raw/储能系统_2026-09-27_GBT34131-2023电力储能用电池管理系统.md`（2026-09-27 04A Batch 1 编译 -> sources [[2026-09-27_GBT34131-2023电力储能用电池管理系统]]；concepts 更新 [[SOC与SOH]]；topics 更新 [[储能系统]]；标准全文未取得，功能条款标 `[!question]`）
- [x] `raw/储能系统_2026-09-27_光伏配锂电容量配置与调度联合优化Berrueta2018.md`（2026-09-27 04A Batch 1 编译 -> sources [[2026-09-27_光伏配锂电容量配置与调度联合优化Berrueta2018]]；topics 更新 [[储能系统]]）
- [x] `raw/储能系统_2026-09-27_大容量储能电池模组热失控传播与燃爆风险.md`（2026-09-27 04A Batch 1 编译 -> sources [[2026-09-27_大容量储能电池模组热失控传播与燃爆风险]]；concepts +1 [[热失控]]；topics 更新 [[储能系统]]）
- [x] `raw/光伏发电技术_2026-09-27_GBT19964-2024光伏发电站接入电力系统技术规定.md`（2026-09-27 04A Batch 1 编译 -> sources [[2026-09-27_GBT19964-2024光伏发电站接入电力系统技术规定]]；topics +1 [[并网与政策]]；标准全文未取得，穿越曲线标 `[!question]`）
- [x] `raw/光伏发电技术_2026-09-27_倾角容量系数行间距对预测精度影响Mayer2022.md`（2026-09-27 04A Batch 1 编译 -> sources [[2026-09-27_倾角容配比行间距对预测精度影响Mayer2022]]；concepts +1 [[容配比]]；topics +1 [[光伏系统设计]]）
- [x] `raw/光伏发电技术_2026-09-27_容配比DCAC比与逆变器截断损失DiazBello2023.md`（2026-09-27 04A Batch 1 编译 -> sources [[2026-09-27_容配比DCAC比与逆变器截断损失DiazBello2023]]；concepts 更新 [[容配比]]；topics 更新 [[光伏系统设计]]）
- [x] `raw/功率预测与建模_2026-09-27_GEFCom2014光伏概率预测Nagy2016.md`（2026-09-27 04A Batch 1 编译 -> sources [[2026-09-27_GEFCom2014光伏概率预测Nagy2016]]；concepts +1 [[概率预测]]；topics 更新 [[功率预测与建模]]）
- [x] `raw/功率预测与建模_2026-09-27_GEFCom2014概率预测综述Hong2016.md`（2026-09-27 04A Batch 1 编译 -> sources [[2026-09-27_GEFCom2014概率预测综述Hong2016]]；concepts 更新 [[概率预测]]；topics 更新 [[功率预测与建模]]）
- [x] `raw/功率预测与建模_2026-09-27_太阳能预测技术综合综述Singla2022.md`（2026-09-27 04A Batch 1 编译 -> sources [[2026-09-27_太阳能预测技术综合综述Singla2022]]；concepts 更新 [[概率预测]]；topics 更新 [[功率预测与建模]]）
- [x] `raw/电价与收益_2026-09-27_两部制电价与需量电费执行政策发改办价格2016-1583.md`（2026-09-27 04A Batch 1 编译 -> sources [[2026-09-27_两部制电价与需量电费执行政策2016-1583号]]；concepts +1 [[两部制电价]]；topics 更新 [[电价与收益]]）

- [x] `raw/储能系统_2026-09-27_GBT34120-2023电化学储能变流器技术要求.md`（2026-09-27 04A Batch 2 编译 -> sources [[2026-09-27_GBT34120-2023电化学储能变流器技术要求]]；topics 更新 [[储能系统]]；标准全文未取得标 `[!question]`）
- [x] `raw/储能系统_2026-09-27_SOC与SOH协同估计车用锂电实测Wu2026.md`（2026-09-27 04A Batch 2 编译 -> sources [[2026-09-27_SOC与SOH协同估计车用锂电实测Wu2026]]；concepts 更新 [[SOC与SOH]]；topics 更新 [[储能系统]]）
- [x] `raw/光伏发电技术_2026-09-27_截断修正性能比CCPR高容配比系统Blakesley2026.md`（2026-09-27 04A Batch 2 编译 -> sources [[2026-09-27_截断修正性能比CCPR高容配比系统Blakesley2026]]；concepts 更新 [[容配比]]；topics 更新 [[光伏系统设计]]）
- [x] `raw/光伏组件_2026-09-27_退化率位置依赖性多晶单晶实测Frick2020.md`（2026-09-27 04A Batch 2 编译 -> sources [[2026-09-27_退化率位置依赖性多晶单晶实测Frick2020]]；concepts 更新 [[组件衰减]]；topics 更新 [[光伏组件]]）
- [x] `raw/功率预测与建模_2026-09-27_物理模型链系统对比MayerGrof2021.md`（2026-09-27 04A Batch 2 编译 -> sources [[2026-09-27_物理模型链系统对比MayerGrof2021]]；topics 更新 [[功率预测与建模]]）
- [x] `raw/并网与政策_2026-09-27_电力现货市场基本规则试行发改能源规2023-1217.md`（2026-09-27 04A Batch 2 编译 -> sources [[2026-09-27_电力现货市场基本规则试行2023-1217号]]；topics 更新 [[并网与政策]]）
- [x] `raw/气象与辐照度_2026-09-27_BSRN地面辐射观测基准网Driemel2018.md`（2026-09-27 04A Batch 2 编译 -> sources [[2026-09-27_BSRN地面辐射观测基准网Driemel2018]]；concepts 更新 [[辐照度]]；topics 更新 [[气象与辐照度]]）
- [x] `raw/气象与辐照度_2026-09-27_NWP日前GHI误差特性与天气分型校正Dou2024.md`（2026-09-27 04A Batch 2 编译 -> sources [[2026-09-27_NWP日前GHI误差特性与天气分型校正Dou2024]]；concepts 更新 [[辐照度]]；topics 更新 [[气象与辐照度]]、[[功率预测与建模]]）
- [x] `raw/电价与收益_2026-09-27_煤电容量电价机制发改价格2023-1501.md`（2026-09-27 04A Batch 2 编译 -> sources [[2026-09-27_煤电容量电价机制发改价格2023-1501号]]；concepts 更新 [[两部制电价]]；topics 更新 [[电价与收益]]）
- [x] `raw/运维与故障诊断_2026-09-27_组串逆变器电压电流信号故障检测ZunigaReyes2021.md`（2026-09-27 04A Batch 2 编译 -> sources [[2026-09-27_组串逆变器电压电流信号故障检测ZunigaReyes2021]]；topics 更新 [[运维与故障诊断]]）
- [x] `raw/储能电池_2026-09-27_锂电池日历老化机器学习建模Celen2023.md`（2026-09-27 04A Batch 3 编译 -> sources [[2026-09-27_锂电池日历老化机器学习建模Celen2023]]；concepts 更新 [[SOC与SOH]]；topics 更新 [[储能系统]]）
- [x] `raw/光伏发电技术_2026-09-27_IEC61724-1光伏系统性能监测标准.md`（2026-09-27 04A Batch 3 编译 -> sources [[2026-09-27_IEC61724-1光伏系统性能监测标准]]；concepts 更新 [[性能比]]、[[容配比]]；topics 更新 [[光伏系统设计]]、[[运维与故障诊断]]；标准正文未取得标 `[!question]`）
- [x] `raw/光伏发电技术_2026-09-27_IEC62548光伏阵列设计要求标准.md`（2026-09-27 04A Batch 3 编译 -> sources [[2026-09-27_IEC62548光伏阵列设计要求标准]]；concepts 更新 [[容配比]]；topics 更新 [[光伏系统设计]]；标准正文未取得标 `[!question]`）
- [x] `raw/光伏组件_2026-09-27_光伏组件失效与检测综述WaqarAkram2022.md`（2026-09-27 04A Batch 3 编译 -> sources [[2026-09-27_光伏组件失效与检测综述WaqarAkram2022]]；concepts 更新 [[热斑]]；topics 更新 [[光伏组件]]、[[运维与故障诊断]]）
- [x] `raw/光伏组件_2026-09-27_多晶硅片微裂纹4000样本功率退化Dhimish2020.md`（2026-09-27 04A Batch 3 编译 -> sources [[2026-09-27_多晶硅片微裂纹4000样本功率退化Dhimish2020]]；concepts 更新 [[组件衰减]]、[[隐裂]]、[[热斑]]；topics 更新 [[光伏组件]]、[[运维与故障诊断]]）
- [x] `raw/并网与政策_2026-09-27_分布式光伏开发建设管理办法国能发新能规2025-7号.md`（2026-09-27 04A Batch 3 编译 -> sources [[2026-09-27_分布式光伏开发建设管理办法国能发新能规2025-7号]]；topics 更新 [[并网与政策]]、[[电价与收益]]）
- [x] `raw/并网与政策_2026-09-27_调度侧功率预测系统技术要求GBT40607-2021.md`（2026-09-27 04A Batch 3 编译 -> sources [[2026-09-27_调度侧功率预测系统技术要求GBT40607-2021]]；concepts 更新 [[概率预测]]；topics 更新 [[并网与政策]]、[[功率预测与建模]]；性能指标未取得标 `[!question]`）
- [x] `raw/气象资源_2026-09-27_太阳能资源评估方法综述王科2023.md`（2026-09-27 04A Batch 3 编译 -> sources [[2026-09-27_太阳能资源评估方法综述王科2023]]；concepts 更新 [[辐照度]]；topics 更新 [[气象与辐照度]]、[[功率预测与建模]]）
- [x] `raw/电价收益_2026-09-27_IRENA2023可再生能源发电成本LCOE.md`（2026-09-27 04A Batch 3 编译 -> sources [[2026-09-27_IRENA2023可再生能源发电成本LCOE]]；concepts 更新 [[LCOE]]、[[两部制电价]]；topics 更新 [[电价与收益]]；LCOE 数值为媒体引述标 `[!question]`）
- [x] `raw/电价收益_2026-09-27_储能套利价值欧洲市场Zafirakis2016.md`（2026-09-27 04A Batch 3 编译 -> sources [[2026-09-27_储能套利价值欧洲市场Zafirakis2016]]；concepts 更新 [[两部制电价]]；topics 更新 [[电价与收益]]、[[储能系统]]）

- [x] `raw/储能电池_2026-09-27_电化学储能电站安全规程GBT42288-2022.md`（2026-09-27 04A Batch 4 编译 -> sources [[2026-09-27_电化学储能电站安全规程GBT42288-2022]]；concepts 更新 [[热失控]]；topics 更新 [[储能系统]]；标准全文未取得标 `[!question]`）
- [x] `raw/储能电池_2026-09-27_锂电池经验老化模型V2G寿命影响Petit2016.md`（2026-09-27 04A Batch 4 编译 -> sources [[2026-09-27_锂电池经验老化模型V2G寿命影响Petit2016]]；concepts 更新 [[SOC与SOH]]、[[组件衰减]]；topics 更新 [[储能系统]]）
- [x] `raw/光伏组件_2026-09-27_IEC61215-1地面光伏组件设计鉴定与定型.md`（2026-09-27 04A Batch 4 编译 -> sources [[2026-09-27_IEC61215-1地面光伏组件设计鉴定与定型]]；concepts 更新 [[隐裂]]、[[热斑]]；topics 更新 [[光伏组件]]；标准正文未取得标 `[!question]`）
- [x] `raw/并网与政策_2026-09-27_新能源场站调度运行信息交换技术要求GBT40604-2021.md`（2026-09-27 04A Batch 4 编译 -> sources [[2026-09-27_新能源场站调度运行信息交换技术要求GBT40604-2021]]；topics 更新 [[并网与政策]]；标准全文未取得标 `[!question]`）
- [x] `raw/气象资源_2026-09-27_PVGIS欧盟JRC光伏地理信息系统官方数据源.md`（2026-09-27 04A Batch 4 编译 -> sources [[2026-09-27_PVGIS欧盟JRC光伏地理信息系统官方数据源]]；concepts 更新 [[辐照度]]；topics 更新 [[气象与辐照度]]）
- [x] `raw/电价收益_2026-09-27_北京完善分时电价机制落地通知2023.md`（2026-09-27 04A Batch 4 编译 -> sources [[2026-09-27_北京完善分时电价机制落地通知2023]]；concepts 更新 [[分时电价]]；topics 更新 [[电价与收益]]）
- [x] `raw/电价收益_2026-09-27_发改委完善分时电价机制通知2021-1093号.md`（2026-09-27 04A Batch 4 编译 -> sources [[2026-09-27_发改委完善分时电价机制通知2021-1093号]]；concepts 更新 [[分时电价]]；topics 更新 [[电价与收益]]、[[并网与政策]]）
- [x] `raw/逆变器与运维_2026-09-27_光伏发电并网逆变器技术要求GBT37408-2019.md`（2026-09-27 04A Batch 4 编译 -> sources [[2026-09-27_光伏发电并网逆变器技术要求GBT37408-2019]]；topics 更新 [[运维与故障诊断]]；标准全文未取得标 `[!question]`）
- [x] `raw/逆变器与运维_2026-09-27_光伏系统故障检测诊断方法综述Mellit2018.md`（2026-09-27 04A Batch 4 编译 -> sources [[2026-09-27_光伏系统故障检测诊断方法综述Mellit2018]]；topics 更新 [[运维与故障诊断]]）
- [x] `raw/逆变器与运维_2026-09-27_电力安全工作规程发电厂变电站电气部分GB26860-2011.md`（2026-09-27 04A Batch 4 编译 -> sources [[2026-09-27_电力安全工作规程发电厂变电站电气部分GB26860-2011]]；topics 更新 [[运维与故障诊断]]；标准全文未取得标 `[!question]`）
- [x] `raw/储能系统_2026-09-27_IEC62619-2022工业储能锂电池安全要求.md`（2026-09-27 04A Batch 5 编译 -> sources [[2026-09-27_IEC62619-2022工业储能锂电池安全要求]]；concepts 更新 [[热失控]]；topics 更新 [[储能系统]]；标准正文未取得标 `[!question]`）
- [x] `raw/储能系统_2026-09-27_电力储能用锂离子电池GBT36276-2023.md`（2026-09-27 04A Batch 5 编译 -> sources [[2026-09-27_电力储能用锂离子电池GBT36276-2023]]；concepts 更新 [[SOC与SOH]]；topics 更新 [[储能系统]]；标准正文未取得标 `[!question]`）
- [x] `raw/光伏发电技术_2026-09-27_移动云影光伏失配损失Lappalainen2017.md`（2026-09-27 04A Batch 5 编译 -> sources [[2026-09-27_移动云影光伏失配损失Lappalainen2017]]；concepts 更新 [[容配比]]；topics 更新 [[光伏系统设计]]）
- [x] `raw/光伏发电技术_2026-09-27_部分遮挡缓解硬件方案综述Mehedi2021.md`（2026-09-27 04A Batch 5 编译 -> sources [[2026-09-27_部分遮挡缓解硬件方案综述Mehedi2021]]；concepts 更新 [[容配比]]；topics 更新 [[光伏系统设计]]；摘要全文未获得标 `[!question]`）
- [x] `raw/光伏组件_2026-09-27_IEC61730-1光伏组件安全鉴定2023.md`（2026-09-27 04A Batch 5 编译 -> sources [[2026-09-27_IEC61730-1光伏组件安全鉴定2023]]；topics 更新 [[光伏组件]]；标准正文未取得标 `[!question]`）
- [x] `raw/气象资源_2026-09-27_NASA-POWER全球太阳辐射气象数据平台.md`（2026-09-27 04A Batch 5 编译 -> sources [[2026-09-27_NASA-POWER全球太阳辐射气象数据平台]]；concepts 更新 [[辐照度]]；topics 更新 [[气象与辐照度]]）
- [x] `raw/电价收益_2026-09-27_促进绿证市场高质量发展意见2025-262号.md`（2026-09-27 04A Batch 5 编译 -> sources [[2026-09-27_促进绿证市场高质量发展意见2025-262号]]；topics 更新 [[电价与收益]]）
- [x] `raw/电价收益_2026-09-27_深化新能源上网电价市场化改革通知2025-136号.md`（2026-09-27 04A Batch 5 编译 -> sources [[2026-09-27_深化新能源上网电价市场化改革通知2025-136号]]；concepts 更新 [[分时电价]]；topics 更新 [[电价与收益]]）
- [x] `raw/电价收益_2026-09-27_绿证与自愿减排市场衔接通知2024.md`（2026-09-27 04A Batch 5 编译 -> sources [[2026-09-27_绿证与自愿减排市场衔接通知2024]]；topics 更新 [[电价与收益]]）
- [x] `raw/逆变器运维_2026-09-27_IEC62109-1光伏电源转换器安全通用要求.md`（2026-09-27 04A Batch 5 编译 -> sources [[2026-09-27_IEC62109-1光伏电源转换器安全通用要求]]；topics 更新 [[运维与故障诊断]]；标准正文未取得标 `[!question]`）
- [x] `raw/光伏发电技术_2026-09-27_GBT39854-2021光伏发电站性能评估技术规范.md`（2026-09-27 04A Batch 6 编译 -> sources [[2026-09-27_GBT39854-2021光伏发电站性能评估技术规范]]；concepts 更新 [[性能比]]；topics 更新 [[光伏系统设计]]；标准正文未取得标 `[!question]`）
- [x] `raw/光伏发电技术_2026-09-27_IECTS61724-3能量评估方法2016.md`（2026-09-27 04A Batch 6 编译 -> sources [[2026-09-27_IECTS61724-3能量评估方法2016]]；concepts 更新 [[性能比]]；topics 更新 [[光伏系统设计]]；标准正文未取得标 `[!question]`）
- [x] `raw/并网与政策_2026-09-27_IEEE1547-2018分布式能源并网互操作标准.md`（2026-09-27 04A Batch 6 编译 -> sources [[2026-09-27_IEEE1547-2018分布式能源并网互操作标准]]；topics 更新 [[并网与政策]]、[[光伏系统设计]]；标准正文未取得标 `[!question]`）
- [x] `raw/并网与政策_2026-09-27_全额保障性收购可再生能源电量监管办法2024.md`（2026-09-27 04A Batch 6 编译 -> sources [[2026-09-27_全额保障性收购可再生能源电量监管办法2024]]；topics 更新 [[并网与政策]]、[[电价与收益]]）
- [x] `raw/并网与政策_2026-09-27_电力中长期市场基本规则发改能源规2025-1656号.md`（2026-09-27 04A Batch 6 编译 -> sources [[2026-09-27_电力中长期市场基本规则发改能源规2025-1656号]]；topics 更新 [[并网与政策]]、[[电价与收益]]）
- [x] `raw/并网与政策_2026-09-27_电力市场运行基本规则2024年第20号令.md`（2026-09-27 04A Batch 6 编译 -> sources [[2026-09-27_电力市场运行基本规则2024年第20号令]]；topics 更新 [[并网与政策]]、[[电价与收益]]）
- [x] `raw/气象与辐照度_2026-09-27_GBT37526-2019太阳能资源评估方法.md`（2026-09-27 04A Batch 6 编译 -> sources [[2026-09-27_GBT37526-2019太阳能资源评估方法]]；concepts 更新 [[辐照度]]；topics 更新 [[气象与辐照度]]；标准正文待核对标 `[!question]`）
- [x] `raw/电价与收益_2026-09-27_绿证全覆盖通知发改能源2023-1044号.md`（2026-09-27 04A Batch 6 编译 -> sources [[2026-09-27_绿证全覆盖通知发改能源2023-1044号]]；concepts 更新 [[LCOE]]；topics 更新 [[电价与收益]]）
- [x] `raw/逆变器与运维_2026-09-27_IEC63027直流电弧检测与中断.md`（2026-09-27 04A Batch 6 编译 -> sources [[2026-09-27_IEC63027直流电弧检测与中断]]；topics 更新 [[运维与故障诊断]]；标准正文未取得标 `[!question]`）
- [x] `raw/逆变器与运维_2026-09-27_阳光电源组串逆变器故障代码与排查官方文档.md`（2026-09-27 04A Batch 6 编译 -> sources [[2026-09-27_阳光电源组串逆变器故障代码与排查官方文档]]；topics 更新 [[运维与故障诊断]]；文档无版本号标 `[!question]`）


- [x] `raw/运维与故障诊断_2026-09-22_EL电致发光检测标准.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_EL电致发光检测标准]]；concept [[EL检测]]；topics [[运维与故障诊断]]）

- [x] `raw/运维与故障诊断_2026-09-22_IV特性测量与数据修正标准.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_IV特性测量与数据修正标准]]；concept [[IV曲线]]；topics [[运维与故障诊断]]）

- [x] `raw/运维与故障诊断_2026-09-22_PID电势诱导衰减测试标准.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_IECTS62804-PID测试标准]]；concept [[PID效应]]；topics [[运维与故障诊断]]）

- [x] `raw/运维与故障诊断_2026-09-22_光伏发电站安全规程.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_光伏发电站安全规程]]；topics [[运维与故障诊断]]）

- [x] `raw/运维与故障诊断_2026-09-22_热斑检测标准与判定边界.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_IEC61215-2热斑耐久试验]]；concept [[热斑]]；topics [[运维与故障诊断]]）

- [x] `raw/运维与故障诊断_2026-09-22_积灰损失与发电量影响.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_IEA-PVPS积灰损失]]；concept [[积灰]]；topics [[运维与故障诊断]]）

- [x] `raw/运维与故障诊断_2026-09-22_红外热成像检测标准.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_红外热成像检测标准]]；concept [[红外热成像]]；topics [[运维与故障诊断]]）

- [x] `raw/运维与故障诊断_2026-09-22_逆变器安全检测与电站运行规程.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_逆变器安全与电站运行规程]]；topics [[运维与故障诊断]]）

- [x] `raw/储能系统_2026-09-22_GB36558-2023储能系统通用技术条件.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_GB36558-2023储能系统通用技术条件]]；topics [[储能系统]]）

- [x] `raw/储能系统_2026-09-22_SOC与SOH术语定义.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_SOC与SOH术语定义]]；concept [[SOC与SOH]]；topics [[储能系统]]）

- [x] `raw/储能系统_2026-09-22_储能接入电网与安全规程标准.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_储能接入电网与安全规程标准]]；topics [[储能系统]]）

- [x] `raw/储能系统_2026-09-22_新型储能参与电力市场与收益模式.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_新型储能参与电力市场与收益模式]]；concept [[储能收益模式]]；topics [[储能系统]]）

- [x] `raw/功率预测与建模_2026-09-22_NB32011-2013功率预测系统技术要求.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_NB32011-2013功率预测系统技术要求]]；topics [[功率预测与建模]]）

- [x] `raw/功率预测与建模_2026-09-22_光伏单位辨析kW-kWh-kWp.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_光伏单位辨析kW-kWh-kWp]]；concept [[光伏单位辨析]]；topics [[功率预测与建模]]）

- [x] `raw/功率预测与建模_2026-09-22_预测方法选型物理基线vs机器学习.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_预测方法选型物理基线vs机器学习]]；topics [[功率预测与建模]]）

- [x] `raw/电价与收益_2026-09-22_收益计算输入清单与边界综述.md`（2026-09-22 阶段02 核心主题补全编译 → sources [[2026-09-22_收益计算输入清单与边界模板]]；topics [[电价与收益]]）

- [x] `raw/horizon/horizon-2026-09-24-en.md`（2026-09-24 编译 → sources +6：[[2026-09-24_LONGiHIBC电池效率纪录2829]]、[[2026-09-24_西班牙11GW可再生能源与储能电网容量分配]]、[[2026-09-24_ARENA资助2500万澳元Lightspeed试验降本]]、[[2026-09-24_美国光伏政策转向设备禁令与关税]]、[[2026-09-24_Norfund投资1亿美元印度Ampin2GW]]、[[2026-09-24_Nadara意大利227MW农光互补项目投运]]；concepts 更新 [[HJT]]（HIBC 28.29%）、[[ABC电池]]（背接触关联）；topics 更新 [[行业动态与政策]]）
  - 来源：Horizon AI 每日简报（6 条入选新闻，评分 9.0/7.0/7.0/6.0/5.0/5.0，信源 rss/PV-Tech）

- [x] `raw/horizon/horizon-2026-09-25-en.md`（2026-09-25 编译 → sources +5：[[2026-09-25_US-DOE52.5亿美元投资23GW电网升级]]、[[2026-09-25_光伏技改退役占2040年代新增装机23%]]、[[2026-09-25_跟踪支架与东西固定倾角系统对比]]、[[2026-09-25_美国插拔式光伏市场受州级监管分化阻碍]]、[[2026-09-25_Websol西孟加拉4GW电池组件工厂用地]]；topics 更新 [[行业动态与政策]]）
  - 来源：Horizon AI 每日简报（5 条入选新闻，评分 8.0/7.0/6.0/5.0/5.0，信源 rss/PV-Tech）

- [x] `raw/运维与故障诊断_2026-09-22_DOE光伏系统运维与性能确认.md`（2026-09-22 登记并编译 → [[2026-09-22_DOE光伏系统运维与性能确认]]；新建 [[运维与故障诊断]] 主题页）
  - 来源：https://www.energy.gov/cmei/femp/life-cycle-photovoltaic-systems-operate-and-maintain-existing-photovoltaic-system
- [x] `raw/运维与故障诊断_2026-09-22_Sandia性能比说明.md`（2026-09-22 登记并编译 → [[2026-09-22_Sandia性能比说明]]、[[性能比]]）
  - 来源：https://pvpmc.sandia.gov/modeling-guide/5-ac-system-output/pv-performance-metrics/performance-ratio/

- [x] `raw/电价与收益_2026-09-22_自发自用与余电上网收益计算.md`（2026-09-22 编译 → sources +1：[[2026-09-22_自发自用余电上网收益计算]]；concepts +1：[[自发自用余电上网]]；topics +1：[[电价与收益]]）
  - 来源：国能发新能规〔2025〕7号（gov.cn 公报全文）｜发改价格〔2025〕136号（百科整理版）｜渭南市发改委官方问答｜湖南绿电直连通知（2026-09-18）
- [x] `raw/电价与收益_2026-09-22_分时电价官方文件与各省落地.md`（2026-09-22 编译 → sources +1：[[2026-09-22_分时电价机制与各省落地政策文件]]；concepts +1：[[分时电价]]；topics [[电价与收益]]）
  - 来源：发改价格〔2021〕1093号（发改委官网全文 + gov.cn 转载）｜山东鲁发改价格函〔2026〕68号｜广东粤发改价格〔2021〕331号｜深圳粤发改价格函〔2021〕2490号｜陕西陕发改价格〔2021〕1757号及 2025-07 调整｜湖南湘发改价调规〔2021〕848号
- [x] `raw/电价与收益_2026-09-22_LCOE平准化度电成本.md`（2026-09-22 编译 → sources +1：[[2026-09-22_LCOE平准化度电成本]]；concepts +1：[[LCOE]]；topics [[电价与收益]]）
  - 来源：EIA 官方术语表 ｜ EIA Today in Energy（2020-03-06）｜ OECD LCOE 方法章；IEA GECM 参数页 403 未直读，标注待确认

- [x] `raw/功率预测与建模_2026-09-22_光伏功率预测输入数据与预处理.md`（2026-09-22 编译 → sources +1：[[2026-09-22_光伏功率预测输入数据与预处理]]；topics +1：[[功率预测与建模]]）
  - 来源：Front. Energy 综述 / PMC 综述 / PVGIS 官方文档 / IEA PVPS 官网；缺失值填充与时间对齐具体做法待确认
- [x] `raw/功率预测与建模_2026-09-22_Huld物理模型.md`（2026-09-22 编译 → sources +1：[[2026-09-22_Huld物理模型]]；concepts +1：[[Huld模型]]；topics [[功率预测与建模]]）
  - 来源：https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/general-information/data-sources-calculation-methods_en ｜ https://doi.org/10.1016/j.solener.2009.12.002 ｜ Huld & Gracia Amillo 2015 (Energies 8:5159-5181)
- [x] `raw/功率预测与建模_2026-09-22_预测误差指标MAE-RMSE-nRMSE-MAPE.md`（2026-09-22 编译 → sources +1：[[2026-09-22_预测误差指标与MAPE局限]]；concepts +1：[[功率预测误差指标]]；topics [[功率预测与建模]]）
  - 来源：https://otexts.com/fpp3/accuracy.html ｜ https://pmc.ncbi.nlm.nih.gov/articles/PMC9834683/ ｜ Front. Energy 综述；nRMSE 归一化口径不统一（均值 vs 装机容量）已用 `> [!warning] 矛盾` 标注

- [x] `raw/horizon/horizon-2026-09-22-en.md`（2026-09-22 编译 → sources +2：[[2026-09-22_美国法院恢复70亿美元Solar-for-All计划]]、[[2026-09-22_DilipBuildcon出售1.36GW印度光伏组合]]；3 条与 9-21 简报同 URL 重复报道，在旧来源页追加"相关来源"，不新建页；topics 更新 [[行业动态与政策]]）
  - 来源：Horizon AI 每日简报（5 条入选新闻，评分 7.0/6.0/6.0/6.0/5.0，信源 rss/PV-Tech）

- [x] `raw/horizon/horizon-2026-09-21-en.md`（2026-09-21 编译 → sources +4：[[2026-09-21_波兰64TWh光伏风电拍卖]]、[[2026-09-21_PremierEnergies7GWTOPCon电池厂投产]]、[[2026-09-21_晶澳HJT组件在轨太空测试]]、[[2026-09-21_Madison1GWDER社区能源倡议]]；更新 [[TOPCon]]（印度 7GW 电池厂）、[[HJT]]（首次在轨测试）、[[光伏组件]]、[[行业动态与政策]]）
  - 来源：Horizon AI 每日简报（4 条入选新闻，评分 7.0/7.0/6.0/5.0，信源 rss/PV-Tech）

- [x] `raw/光伏发电技术_2026-09-14_Degradation of photovoltaic module output power by microparticles.md`（2026-09-17 回填+编译 → [[2026-09-17_Saito微颗粒造成组件输出功率衰减]]；[[组件衰减]]）
  - 来源：https://doi.org/10.1109/pvsc.2011.6186559 ｜ 状态：已回填（OpenAlex 摘要）
- [x] `raw/光伏发电技术_2026-09-14_Detection of PV Module Temperature Coefficient Using Machine Learning.md`（2026-09-17 回填+编译 → [[2026-09-17_机器学习检测组件温度系数]]；[[温度系数]]）
  - 来源：https://doi.org/10.1109/pvsc48320.2023.10360007 ｜ 状态：已回填（OpenAlex 摘要）
- [x] `raw/光伏发电技术_2026-09-14_Dual-inverter-based MPPT algorithm for grid-connected photovoltaic systems.md`（2026-09-17 回填+编译 → [[2026-09-17_双逆变器并网MPPT算法]]；[[MPPT]]）
  - 来源：https://doi.org/10.1109/iccep.2009.5212023 ｜ 状态：已回填（OpenAlex 摘要）
- [x] `raw/光伏发电技术_2026-09-14_Evaluation of temperature and humidity on PV module component degradation.md`（2026-09-17 回填+编译 → [[2026-09-17_温湿度对组件部件降解影响]]；[[组件衰减]]）
  - 来源：https://doi.org/10.1109/pvsc.2013.6744112 ｜ 状态：已回填（OpenAlex 摘要）
- [x] `raw/光伏发电技术_2026-09-14_Evaluation of temperature and humidity on PV module degradation- in field degrad.md`（2026-09-17 回填+编译 → [[2026-09-17_晶硅组件现场降解温湿度分析]]；[[组件衰减]]）
  - 来源：https://doi.org/10.1109/pvsc40753.2019.8981241 ｜ 状态：已回填（OpenAlex 摘要）
- [x] `raw/光伏发电技术_2026-09-14_Irradiance Dependence of the Short-Circuit Current Temperature Coefficient of sc.md`（2026-09-17 回填+编译 → [[2026-09-17_短路电流温度系数辐照度依赖]]；[[温度系数]]）
  - 来源：https://doi.org/10.1109/pvsc45281.2020.9300416 ｜ 状态：已回填（OpenAlex 摘要）
- [x] `raw/光伏发电技术_2026-09-14_JECET.md`（2026-09-17 回填+编译 → [[2026-09-17_JECET并网光伏最优MPPT与逆变器控制]]；[[MPPT]]）
  - 来源：https://doi.org/10.24214/jecet.c.6.3.32644 ｜ 状态：**待确认**（仅 Crossref 元数据，摘要/作者未获取）
- [x] `raw/光伏发电技术_2026-09-14_The micro-grid connected single-phase photovoltaic inverter with simple MPPT con.md`（2026-09-17 回填+编译 → [[2026-09-17_微电网单相光伏逆变器简易MPPT]]；[[MPPT]]）
  - 来源：https://doi.org/10.1109/ieecon.2017.8075751 ｜ 状态：已回填（OpenAlex 摘要）
- [x] `raw/气象与辐照度_2026-09-14_A simple, solar spectral model for direct-normal and diffuse horizontal irradian.md`（2026-09-17 回填+编译 → [[2026-09-17_Bird简单太阳光谱模型]]；[[辐照度]]）
  - 来源：https://doi.org/10.1016/0038-092x(84)90260-3 ｜ 状态：**待确认**（仅 Crossref 元数据，ScienceDirect 原文 WAF 拦截）
- [x] `raw/气象与辐照度_2026-09-14_Data for Solar Forecasting.md`（2026-09-17 回填+编译 → [[2026-09-17_太阳预报数据综述]]；[[辐照度]]）
  - 来源：https://doi.org/10.1201/9781003203971-6 ｜ 状态：已回填（OpenAlex 摘要）
- [x] `raw/气象与辐照度_2026-09-14_Estimation of direct normal irradiance from measured global and corrected diffus.md`（2026-09-17 回填+编译 → [[2026-09-17_由GHI与DHI估计DNI]]；[[辐照度]]）
  - 来源：https://doi.org/10.1016/j.energy.2014.04.012 ｜ 状态：**待确认**（仅 Crossref 元数据，ScienceDirect 原文 WAF 拦截）

- [x] `raw/horizon/horizon-2026-09-17-en.md`（2026-09-17 编译 → sources +1：[[2026-09-17_FirstSolar撤回ITC-TOPCon专利投诉]]；更新 [[TOPCon]]（专利执法动态、美国电池产能结构）、[[行业动态与政策]]、[[光伏组件]]）
  - 来源：Horizon AI 每日简报（1 条入选新闻，评分 6.0/10，信源 rss/PV-Tech）

- [x] `raw/horizon/horizon-2026-09-16-en.md`（2026-09-16 编译 → sources +6：[[2026-09-16_REPowerEU资金不足两成欧盟光伏增长停滞]]、[[2026-09-16_佐治亚理工24.3%铜接触TOPCon电池]]、[[2026-09-16_NZIA进程迟缓难振欧洲光伏制造]]、[[2026-09-16_巴西8月新增891MW公用事业光伏]]、[[2026-09-16_官方问答澄清中国强制光伏国标]]、[[2026-09-16_美国社区光伏融资3.7亿美元]]；concepts +1（[[铜浆金属化]]）；topics +1（[[行业动态与政策]]）；更新 [[TOPCon]]、[[HJT]]、[[光伏组件]]）
  - 来源：Horizon AI 每日简报（6 条入选新闻，评分 7.0/7.0/6.0/6.0/6.0/5.0）

- [x] `raw/horizon/horizon-2026-09-15-en.md`（2026-09-15 编译 → 与 9-14 简报同源重复报道，追加"相关来源"至 `wiki/sources/2026-09-14_刚果铜矿233MW光储电站投运.md`、`wiki/sources/2026-09-14_西班牙Teruel937MW可再生能源储能拍卖.md`，不新建页）
  - 来源：Horizon AI 每日简报（2 条入选新闻，均评分 6.0）：CrossBoundary 刚果铜矿 233MW 光储投运、西班牙 Teruel 937MW 储能招标
- [x] `raw/光伏发电技术_2026-09-14_BS EN 61853-2-2016 - 31 Jan 2017 - BSI Knowledge.md`（2026-09-15 编译 → `wiki/sources/2026-09-15_IEC61853组件性能测试与能量额定标准.md`、概念页 +`wiki/concepts/能量额定.md`）
  - 来源：https://doi.org/10.3403/30232513u
- [x] `raw/光伏发电技术_2026-09-14_US finalises solar AD-CVD duties on India, Indonesia, Laos.md`（2026-09-15 编译 → 与已编译来源页同 URL，追加"相关来源"至 `wiki/sources/2026-09-14_美国光伏电池双反终裁249%.md`，不新建页）
  - 来源：https://www.pv-tech.org/us-finalises-ad-cvd-duties-on-solar-cell-imports-from-india-indonesia-and-laos/
- [x] `raw/气象与辐照度_2026-09-14_A Comprehensive Approach for Modelling Horizontal Diffuse Radiation, Direct Norm.md`（2026-09-15 编译 → `wiki/sources/2026-09-15_丹麦气候下水平散射辐射与倾斜面辐射建模.md`、概念页 +`wiki/concepts/辐照度.md`）
  - 来源：https://doi.org/10.3390/en11051315
- [x] `raw/气象与辐照度_2026-09-14_Abstract EMS2024-863.md`（2026-09-15 编译 → `wiki/sources/2026-09-15_DLR地表太阳辐照度变率分类方法.md`）
  - 来源：https://doi.org/10.5194/ems2024-863
- [x] `raw/horizon/horizon-2026-09-14-en.md`（2026-09-14 编译 → `wiki/sources/2026-09-14_美国光伏电池双反终裁249%.md`、`wiki/sources/2026-09-14_西班牙Teruel937MW可再生能源储能拍卖.md`、`wiki/sources/2026-09-14_刚果铜矿233MW光储电站投运.md`；概念页 +`wiki/concepts/ABC电池.md`）
  - 来源：Horizon AI 每日简报（信源 pv-tech.org/feed/，3 条入选新闻，评分 9.0/6.0/5.0）
- [x] `raw/光伏组件_2026-09-14_PV Chart of the Week- US HJT module production growing fastest.md`（2026-09-14 编译 → `wiki/sources/2026-09-14_US-HJT组件产能增长最快.md`）
  - 来源：https://www.pv-tech.org/pv-chart-of-the-week-hjt-module-production-growing-the-fastest-us/
- [x] `raw/光伏组件_2026-09-14_华为发布2026智能光伏十大趋势.md`（2026-09-14 编译 → `wiki/sources/2026-09-14_华为2026智能光伏十大趋势.md`）
  - 来源：https://digitalpower.huawei.com/cn/news/fusionsolar/pv-trends-2026
- [x] `output/rag/rag_export_report_2026-09-14.md`（2026-09-14 file back 回流 → 内部产物来源页 `wiki/sources/2026-09-14_RAG语料导出.md`）
  - 来源：知识库内部产物（RAG 导出报告），按 04-output 第 5 步回流
