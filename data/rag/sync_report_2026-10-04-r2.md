# RAG 同步报告

- 同步时间: 2026-10-04T07:19:09Z
- 索引版本: `2026-10-04-r2`（上一版本: `2026-10-04`）
- 来源: `D:\Demo\Script\data\rag\releases\2026-10-04-2e493f40\corpus.jsonl`
- chunk 数: 123
- 差异: 新增 43 / 变更 0 / 未变 80 / 下线 0
- embedding: `BAAI/bge-small-zh-v1.5` (dim=512, norm=l2)
- 向量构建耗时: 2.43s
- 保留版本数: 2
- 已清理旧版本: 2026-10-04

## 主题覆盖

- 光伏发电技术: 50
- 气象与辐照度: 25
- 运维与故障诊断: 20
- 行业动态与政策: 18
- 功率预测与建模: 9
- 光伏综合: 1

## 回滚

```bash
python rag/sync_rag_to_app.py --rollback
```
