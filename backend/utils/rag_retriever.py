#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
rag_retriever.py —— 阶段三 M3.3 混合检索与重排

BM25(jieba) + 向量(BGE-small-zh) 双通道召回 → 合并去重 → 二次评分 → 可解释重排。
消费 data/rag/releases/<version>/ 已发布索引（corpus.jsonl + embeddings.jsonl + manifest.json），
按 active_manifest.json 做版本单例加载；sync 换版后需 reload()/重启进程生效（M3.3 运维说明）。

接口契约（rag/eval_m33|m34|m35 验收脚本冻结）：
    DATA_RAG                      # data/rag 目录常量
    Retriever(data_rag=None)       # 构造（可注入 target 目录）
    Retriever.instance()           # active 版本单例
    .load_version(v) -> bool       # 加载候选版本
    .reload() -> bool              # 重新加载 active
    .version / .corpus             # 当前版本号 / 语料行列表
    .retrieve(query, top=n)        # 返回证据 dict 列表（含 row/id/title/semantic/...）

降级路径：embedding 模型不可用时 semantic 全为 0、仅 BM25 排序（查询侧降级，
不影响索引本身）；上层 search_knowledge/kb 还可回退旧 search_kb。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .region_words import REGION_TERMS, extract_regions

BASE = Path(__file__).resolve().parents[2]          # 项目根
DATA_RAG = BASE / "data" / "rag"

EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
EMBEDDING_DIM = 512
FASTEMBED_CACHE = BASE / "rag" / "idx" / ".fastembed_cache"

# M3.3 rerank 权重（交付说明冻结）
W_SEMANTIC = 0.55
W_BM25 = 0.35
SEM_FLOOR = 0.45                 # 相似度 < 0.45 视为弱相关截断为 0
HEURISTIC_CAP = 0.42
CAND_TOPK = 20                   # 双通道各取 top20 合并

# 正则保护：标准号 / 设备型号 / 故障码（IEC 61853-2、HJT-210、E023 不被切散）
_TOKEN_KEEP_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/.]{1,24}")
_STOPWORDS = set("的 了 是 在 和 与 及 对 什么 如何 怎么 哪些 请问 吗 呢 啊 吧 而 或".split())

_AUTHORITY_STRONG = ("发改委", "能源局", "IEC", "IEEE", "ISO", "国标", "规范", "标准委")


def _clip(text: str, n: int = 220) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t[:n]


class Retriever:
    """版本化混合检索器（单例按 active manifest 加载）"""

    _inst: "Retriever | None" = None
    _inst_lock = threading.Lock()

    def __init__(self, data_rag: Path | str | None = None):
        self.data_rag = Path(data_rag) if data_rag else DATA_RAG
        self.version = ""
        self.corpus: list[dict] = []
        self.manifest: dict = {}
        self._vecs: np.ndarray | None = None       # (N, 512) float32 L2 归一化
        self._bm25 = None                          # BM25Okapi
        self._doc_tokens: list[list[str]] = []
        self._embedder = None
        self._embedder_failed = False
        self._load_lock = threading.Lock()

    # ── 单例 ──────────────────────────────────────────────
    @classmethod
    def instance(cls) -> "Retriever":
        with cls._inst_lock:
            if cls._inst is None:
                r = cls()
                r.reload()
                cls._inst = r
            return cls._inst

    @classmethod
    def reset_instance(cls) -> None:
        with cls._inst_lock:
            cls._inst = None

    # ── 加载 ──────────────────────────────────────────────
    def reload(self) -> bool:
        """按 active_manifest.json 重新加载当前线上版本。"""
        act = self.data_rag / "active_manifest.json"
        if not act.is_file():
            return False
        try:
            meta = json.loads(act.read_text(encoding="utf-8"))
        except Exception:
            return False
        version = str(meta.get("version") or "").strip()
        if not version:
            return False
        return self.load_version(version)

    def load_version(self, version: str) -> bool:
        """加载 releases/<version>/；成功返回 True。"""
        rel = self.data_rag / "releases" / str(version)
        corpus_f = rel / "corpus.jsonl"
        emb_f = rel / "embeddings.jsonl"
        mf_f = rel / "manifest.json"
        if not (corpus_f.is_file() and emb_f.is_file()):
            return False

        with self._load_lock:
            corpus: list[dict] = []
            with corpus_f.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        corpus.append(json.loads(line))

            # embeddings.jsonl：{"id": ..., "vector": [...]}，按 id 对齐 corpus
            vec_by_id: dict[str, np.ndarray] = {}
            with emb_f.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    vec_by_id[str(obj.get("id"))] = np.asarray(obj.get("vector") or [],
                                                               dtype=np.float32)
            ids = [str(c.get("id") or "") for c in corpus]
            missing = [i for i in ids if i not in vec_by_id]
            if missing:
                raise RuntimeError(f"版本 {version} 向量缺失 {len(missing)} 条: {missing[:3]}")
            mat = np.stack([vec_by_id[i] for i in ids])
            # L2 归一化保险（sync 声明 l2；加载侧复验）
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            mat = mat / norms

            manifest = {}
            if mf_f.is_file():
                try:
                    manifest = json.loads(mf_f.read_text(encoding="utf-8"))
                except Exception:
                    manifest = {}

            self.corpus = corpus
            self._vecs = mat
            self.manifest = manifest
            self.version = str(version)
            self._build_bm25()
            return True

    # ── 分词（含地区全称/简称桥接）────────────────────────────
    def _tokenize(self, text: str) -> list[str]:
        import jieba
        raw = text or ""
        keepers = set(m.group(0).lower() for m in _TOKEN_KEEP_RE.finditer(raw))
        segs = [w.strip() for w in jieba.lcut(raw) if w and w.strip()]
        out: list[str] = []
        regions = set()
        for t in extract_regions(raw):
            regions.add(t)
            # 山东 ↔ 山东省 互桥
            if t.endswith("省") or t.endswith("市"):
                regions.add(t[:-1])
            else:
                regions.add(t + "省") if t + "省" in REGION_TERMS else None
                regions.add(t + "市") if t + "市" in REGION_TERMS else None
        for w in segs + list(keepers) + list(regions):
            lw = w.lower()
            if not lw or lw in _STOPWORDS:
                continue
            out.append(lw)
        return out

    def _build_bm25(self) -> None:
        from rank_bm25 import BM25Okapi
        self._doc_tokens = [self._tokenize(f"{c.get('title','')}\n{c.get('content','')}")
                            for c in self.corpus]
        self._bm25 = BM25Okapi(self._doc_tokens) if self._doc_tokens else None

    # ── 查询向量化 ─────────────────────────────────────────
    def _get_embedder(self):
        if self._embedder_failed:
            return None
        if self._embedder is not None:
            return self._embedder
        try:
            from fastembed import TextEmbedding
            FASTEMBED_CACHE.mkdir(parents=True, exist_ok=True)
            self._embedder = TextEmbedding(model_name=EMBEDDING_MODEL,
                                           cache_dir=str(FASTEMBED_CACHE))
            return self._embedder
        except Exception:
            self._embedder_failed = True
            return None

    def _embed_query(self, query: str) -> np.ndarray | None:
        emb = self._get_embedder()
        if emb is None or self._vecs is None:
            return None
        try:
            vecs = list(emb.embed([query]))
            v = np.asarray(vecs[0], dtype=np.float32)
            n = float(np.linalg.norm(v))
            if n > 0:
                v = v / n
            if v.shape[0] != self._vecs.shape[1]:
                return None
            return v
        except Exception:
            return None

    # ── 检索 ──────────────────────────────────────────────
    def retrieve(self, query: str, top: int = 8) -> list[dict]:
        if not self.corpus or self._vecs is None:
            return []
        q = (query or "").strip()
        if not q:
            return []

        n = len(self.corpus)

        # 语义通道（全量余弦；查询向量与语料向量均 L2 归一化 → 点积=余弦）
        qv = self._embed_query(q)
        sem_all = (self._vecs @ qv).astype(np.float64) if qv is not None else np.zeros(n)

        # BM25 通道（全量打分）
        if self._bm25 is not None:
            tokens = self._tokenize(q)
            bm25_all = np.asarray(self._bm25.get_scores(tokens), dtype=np.float64)
        else:
            bm25_all = np.zeros(n)

        # 双通道 top20 合并（按 id 即行号合并，各保留候选资格）
        sem_order = np.argsort(-sem_all)[:CAND_TOPK]
        bm_order = np.argsort(-bm25_all)[:CAND_TOPK]
        cand_rows = sorted(set(int(i) for i in list(sem_order) + list(bm_order)))

        bm_max = float(bm25_all.max()) if bm25_all.size and bm25_all.max() > 0 else 0.0
        now = datetime.now(timezone.utc)

        query_regions = extract_regions(q)
        query_norm = [self._norm_region(r) for r in query_regions]
        q_words = set(self._tokenize(q))

        scored: list[tuple[float, int]] = []
        for row in cand_rows:
            hit = self.corpus[row]
            cos = float(sem_all[row])

            # 语义分：< SEM_FLOOR 截断为 0，其上线性拉开（0.6~0.8 区分度）
            if cos < SEM_FLOOR:
                sem_part = 0.0
            else:
                sem_part = (cos - SEM_FLOOR) / (1.0 - SEM_FLOOR)
            sem_part *= W_SEMANTIC

            bm_norm = (float(bm25_all[row]) / bm_max) if bm_max > 0 else 0.0
            bm_part = bm_norm * W_BM25

            heur = self._heuristic_bonus(hit, q, q_words, query_norm, now)
            total = sem_part + bm_part + min(heur, HEURISTIC_CAP)
            scored.append((total, row))

        scored.sort(key=lambda x: -x[0])
        out: list[dict] = []
        for total, row in scored[: max(1, int(top))]:
            out.append(self._evidence_row(row, float(sem_all[row]),
                                          float(bm25_all[row]) if bm_max <= 0
                                          else float(bm25_all[row]) / bm_max,
                                          total))
        return out

    @staticmethod
    def _norm_region(r: str) -> str:
        return (r or "").replace("省", "").replace("市", "").replace("自治区", "") \
                        .replace("特别行政区", "").replace("壮族", "").replace("维吾尔", "") \
                        .replace("回族", "")

    def _heuristic_bonus(self, hit: dict, q: str, q_words: set,
                         query_regions_norm: list, now) -> float:
        """启发式加分（M3.3 交付说明口径，上限 HEURISTIC_CAP）"""
        bonus = 0.0
        title = str(hit.get("title") or "")
        # 1) title 命中 query 词：+0.05/词（上限 0.15）
        t_words = set(self._tokenize(title))
        common = [w for w in q_words if len(w) > 1 and w in t_words]
        bonus += min(0.05 * len(common), 0.15)
        # 2) authority 强权威：+0.05
        auth = str(hit.get("authority") or "")
        if any(a.lower() in auth.lower() for a in _AUTHORITY_STRONG):
            bonus += 0.05
        # 3) region：匹配 +0.12 / 提到地区但不匹配 −0.15 / 无地区标注 −0.05
        regions = hit.get("region") or []
        if isinstance(regions, str):
            regions = [regions]
        regions = [str(r) for r in regions if r]
        if query_regions_norm:
            if regions:
                hit_norm = [self._norm_region(r) for r in regions]
                national = any(self._norm_region(r) in ("中国", "全国") or
                               r in ("中国", "全国") for r in regions)
                matched = any(hr in query_regions_norm or qr in hr
                              for hr in hit_norm for qr in query_regions_norm)
                if matched:
                    bonus += 0.12
                elif not national:
                    bonus -= 0.15
            else:
                bonus -= 0.05
        elif not regions:
            bonus -= 0.05
        # 4) updated_at 距今 ≤90 天：+0.06×(1−age/90)
        upd = str(hit.get("updated_at") or hit.get("date") or "")[:10]
        if upd:
            try:
                d = datetime.strptime(upd, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                age = max(0, (now - d).days)
                if age <= 90:
                    bonus += 0.06 * (1 - age / 90)
            except ValueError:
                pass
        # 5) 一级证据 evidence 非占位：+0.04
        evs = hit.get("evidence") or []
        if isinstance(evs, str):
            evs = [evs]
        ev_ok = False
        for e in evs:
            s = str(e).strip()
            if s and "placeholder" not in s.lower() and "暂无" not in s and "待补" not in s:
                ev_ok = True
                break
        if ev_ok:
            bonus += 0.04
        return bonus

    def _evidence_row(self, row: int, cos: float, bm_norm: float, total: float) -> dict:
        c = self.corpus[row]
        region = c.get("region")
        if region is None:
            region = []
        elif isinstance(region, str):
            region = [region]
        authority = c.get("authority")
        if authority is None:
            authority = []
        elif isinstance(authority, str):
            authority = [authority]
        ev = c.get("evidence")
        if ev is None:
            ev = []
        elif isinstance(ev, str):
            ev = [ev]
        path = str(c.get("source_path") or "")
        date = str(c.get("updated_at") or "")[:10]
        return {
            "row": row,
            "id": str(c.get("id") or ""),
            "title": str(c.get("title") or ""),
            "path": path,
            "source": path,
            "snippet": _clip(str(c.get("content") or "")),
            "tags": c.get("tags") or [],
            "topic": str(c.get("topic") or ""),
            "region": region,
            "authority": authority,
            "date": date,
            "updated_at": str(c.get("updated_at") or ""),
            "valid_from": c.get("valid_from"),
            "valid_to": c.get("valid_to"),
            "evidence": ev,
            "semantic": round(cos, 4),
            "bm25": round(float(bm_norm), 4),
            "score": round(float(total), 4),
        }
