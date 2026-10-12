# NASA POWER（全球太阳辐射与气象再分析数据平台，官方数据源）

**来源**：美国国家航空航天局（NASA）Langley 研究中心官方平台
**原始 URL**：https://power.larc.nasa.gov/
**整理时间**：2026-09-27
**查阅日期**：2026-09-27
**主题**：气象资源（太阳辐射与气象数据源、历史与典型年数据）
**证据类型**：权威机构官方数据平台（官方页面核验）
**适用场景**：无测站地区光伏资源初评与历史辐照/气象数据获取；卫星+再分析数据用于辐照、温度、风速等特征；与地面观测（BSRN）、欧盟 PVGIS 互补的全球化数据源

## 一、原始信息与版本

- 名称：NASA Prediction Of Worldwide Energy Resources（POWER）
- 维护机构：NASA Langley Research Center（兰利研究中心）
- 数据性质：**基于卫星观测与模型的太阳辐射和气象数据**，覆盖全球，供能源、基础设施与农业气候等社区使用
- 提供方式：Data Access Viewer（交互式查看器）、**Application Programming Interface（API）**、Direct Datastore Access、Geospatial Data Services

## 二、原文直接支持的事实（基于官方页面）

- 目标：为全球用户提供太阳辐射与气象数据，帮助回应环境挑战与社会需求（"solar and meteorological data from satellite observations and models"）。
- 规模：**300+ 太阳辐射与气象参数**目录（solar and meteorological data parameters）。
- 特色：免费、低延迟、按社区定制（customizable units and formats）；提供数据方法论、参数字典、教程与引用 POWER 数据的出版物列表。
- 适用方向（官方页面自述）：能源（含光伏资源评估）、基础设施与农业气候。

## 三、限制条件

- POWER 为卫星反演/再分析数据，与地面实测存在偏差（官方文档提供精度评估）；决策性项目建议结合当地实测校准。
- 具体参数（如 GHI/DNI/DHI、POA、温度、风速的时空分辨率与时段范围）需在参数字典/API 文档核对，勿按印象引用。
- 引用数值时必须注明数据版本与时间范围。

## 四、不能推出的结论

- 不能把 POWER 数据当作某地实测辐照（属卫星/再分析产品）。
- 不能从官方首页推出具体参数的分辨率与时段（需查文档）。
- 不能推出中国光伏度电成本或收益数值（数据源本身不含电价）。

## 五、对应主题与查重

- 对应主题6「气象资源：GHI/DNI/DHI/POA……」的数据源缺口（与 PVGIS 同为卫星+再分析工程数据源，与 BSRN 实测基准互补）。
- 查重：raw/ 有 PVGIS（欧盟）、BSRN（地面基准）、王科综述（评估方法）；NASA POWER 为中国语境下常用的另一全球化数据源，新增互补。