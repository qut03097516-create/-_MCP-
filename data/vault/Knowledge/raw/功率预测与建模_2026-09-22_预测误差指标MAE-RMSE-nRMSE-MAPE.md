# 预测评价指标：MAE、RMSE、nRMSE、MAPE 定义与 MAPE 局限

**来源**：见下方各节原始链接
**整理时间**：2026-09-22
**主题**：功率预测与建模

> 记法约定：yi(pred) 为预测值、yi(act) 为实际值，e = y_pred − y_act，N 为样本数。

## 定义（FPP3 官方免费教材全文）

- Hyndman, R.J., & Athanasopoulos, G. *Forecasting: Principles and Practice*（3rd ed., OTexts）"Evaluating forecast accuracy" 一章，给出：
  - `MAE = mean(|e|)`：平均绝对误差。
  - `RMSE = sqrt(mean(e^2))`：均方根误差。
  - `MAPE = mean(100 * |e| / y)`：平均绝对百分比误差（教材以百分比形式给出）。
- 链接（全文可读）：https://otexts.com/fpp3/accuracy.html

## nRMSE 等指标（PMC 综述全文）

- *A Comprehensive Review on Ensemble Solar Power Forecasting Algorithms*（J. Electr. Eng. Technol. 2023; 18:719–733；PMCID: PMC9834683，开放获取）给出太阳辐照度预报常用统计指标公式：
  - `MBE = (1/N) Σ [yi(pred) − yi(act)]`（MBE>0 表示过预报，<0 表示欠预报）
  - `MAE = (1/N) Σ |yi(pred) − yi(act)|`（适于均匀误差，等权处理所有偏差）
  - `MSE = (1/N) Σ [yi(pred) − yi(act)]^2`
  - `RMSE = sqrt( (1/N) Σ [yi(pred) − yi(act)]^2 )`（突出大误差，常用于主评价指标）
  - `nRMSE = sqrt( (1/N) Σ [yi(pred) − yi(act)]^2 ) / y_bar`，其中 `y_bar` 为实际辐照度（或功率）的均值——**即用实际均值归一化的 RMSE**。
  - `MAPE = (1/N) Σ |yi(pred) − yi(act)| / yi(act)`（按文献公式未乘 100；口径差异需注意）
  - R²（决定系数，0–1）；Skill Score S = 1 − RMSE_forecast / RMSE_benchmark。
- 链接（全文可读）：https://pmc.ncbi.nlm.nih.gov/articles/PMC9834683/

## nRMSE 归一化基准不统一（口径提示）

- nRMSE 的归一化分母业界并不统一：PMC 综述使用**实际值均值**（y_bar）；部分工程报告/项目材料使用**装机容量**归一化（如站内复盘材料 .dumate 目录按 RMSE/装机容量 计算）。

> [!warning] 矛盾
> nRMSE 归一化基准存在“实际均值”与“装机容量”两种口径，跨文献/跨项目比较 nRMSE 前必须先对齐归一化方式；PVGIS 官方验证表中出现的 RMSD（W/m²）为绝对单位，不做归一化。

## MAPE 在低功率/零功率时的局限（FPP3 全文）

- FPP3 原文指出：**MAPE 在 y_t = 0 时未定义（除以零）**；当 y_t 接近 0 时会产生**极大的百分比误差**；且 MAPE 对**负误差（预测低于实际）的惩罚重于正误差**（不对称），导致偏向于低估的系统性偏差；sMAPE 同样存在除以零导致不稳定/未定义的问题。因此 MAPE 只适合实际值有明确且不为零的尺度（如辐照度日总量），对夜间/低功率时段占比高的光伏功率序列要谨慎使用。
- 链接：https://otexts.com/fpp3/accuracy.html

## 其他佐证

- *A comprehensive review and analysis of solar forecasting techniques*（Frontiers in Energy, 2021；DOI: 10.1007/s11708-021-0722-7）综述同样采用 RMSE/MAE/MAPE/R²/MBE/nRMSE（或 rRMSE 百分比归一化）作为太阳预报通用评价指标集合。
  - 链接（全文可读）：https://journal.hep.com.cn/fie/EN/10.1007/s11708-021-0722-7

## 关键术语
- [[功率预测与建模]]、[[功率预测误差指标]]

---
*本笔记由 2026-09-22 历史知识补全整理（第一批，主题=功率预测与建模），按 prompts/06-historical-backfill.md 流程新增 raw 资料。*