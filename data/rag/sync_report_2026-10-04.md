# RAG 同步报告

- 同步时间: 2026-10-04T06:13:08Z
- 索引版本: `2026-10-04`（上一版本: `-`）
- 来源: `D:\Demo\Script\data\rag\releases\2026-10-04\corpus.jsonl`
- chunk 数: 80
- 差异: 新增 80 / 变更 0 / 未变 0 / 下线 0
- embedding: `BAAI/bge-small-zh-v1.5` (dim=512, norm=l2)
- 向量构建耗时: 33.3s
- 保留版本数: 2

## 主题覆盖

- 光伏发电技术: 39
- 行业动态与政策: 18
- 气象与辐照度: 13
- 运维与故障诊断: 8
- 功率预测与建模: 1
- 光伏综合: 1

## 回滚

```bash
python rag/sync_rag_to_app.py --rollback
```
