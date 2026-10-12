#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
evidence_policy.py —— 阶段三 M3.4 证据约束回答与拒答

查询意图（政策类）识别 → 地区匹配 → 时间有效性 → 冲突标记 → 拒答决策 → 上下文格式化。
与 backend/api/query.py 的检索-过滤闭环配合：拒答时直接返回标准语，不走 LLM。

接口契约（rag/eval_m34_acceptance.py 冻结）：
    is_policy_question(query) -> bool
    check_region_match(query, regions) -> bool
    check_time_validity(hit, now) -> (valid: bool, note: str)
    detect_conflict(hits) -> hits（就地标 _conflict_region）
    filter_policy_evidence(hits, query) -> (kept: list, reason: str | None)
    format_kb_context(hits) -> str
    format_kb_rules(has_evidence: bool) -> str
    refusal_message(reason, query) -> str
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .region_words import extract_regions

# ── 政策意图（与 rag_schema.json policy_signal_patterns 对齐 + 高频政策词）──
_POLICY_PATTERNS = re.compile(
    r"电价|补贴|政策|发改|上网|分时|峰谷|尖峰|深谷|代理购电|价差|机制电价"
    r"|入市|关税|拍卖|管理办法|监管|消纳|余电|FIT|强制|门槛|并网规范|并网标准"
    r"|国家能源局|国能发|发改价格|136号|7号文|规范性文件|招标|中标",
    re.IGNORECASE,
)

_NATIONAL = ("中国", "全国", "国家", "全国性", "各省")


def is_policy_question(query: str) -> bool:
    """问题是否涉及政策/电价/并网/标准等需地区+时间过滤的敏感主题。"""
    return bool(_POLICY_PATTERNS.search(query or ""))


def _norm_region(r: str) -> str:
    return (r or "").strip().replace("省", "").replace("市", "") \
        .replace("特别行政区", "").replace("壮族", "").replace("维吾尔", "") \
        .replace("回族", "").replace("自治区", "")


def check_region_match(query: str, regions) -> bool:
    """查询与证据 region 是否兼容。
    - 查询无地区 → True（不过滤）
    - 证据为全国性 → True
    - 否则归一化后简称/全称匹配
    """
    if isinstance(regions, str):
        regions = [regions]
    regions = [str(r) for r in (regions or []) if r]
    q_regions = extract_regions(query or "")
    if not q_regions:
        return True
    if not regions:
        return False
    if any(r in _NATIONAL for r in regions):
        return True
    qn = {_norm_region(r) for r in q_regions}
    rn = {_norm_region(r) for r in regions}
    return any(q == r or q in r or r in q for q in qn for r in rn)


def _hit_region_matches(query: str, hit: dict) -> bool:
    """filter 专用：查询含地区时，证据必须命中该地区（全国条目不放行，
    保证『错地区政策题 → 拒答』；全国性问题查询本身无地区，不受此限）。"""
    q_regions = extract_regions(query or "")
    if not q_regions:
        return True
    regions = hit.get("region") or []
    if isinstance(regions, str):
        regions = [regions]
    regions = [str(r) for r in regions if r]
    if not regions:
        return False
    qn = {_norm_region(r) for r in q_regions}
    rn = {_norm_region(r) for r in regions}
    return any(q == r or q in r or r in q for q in qn for r in rn)


def check_time_validity(hit: dict, now: datetime | None = None) -> tuple[bool, str]:
    """valid_from/valid_to 是否覆盖当前日期。返回 (valid, note)。
    两者皆空 → 长期有效 True；未生效/已过期 → False。
    """
    now = now or datetime.now(timezone.utc)
    vf = str(hit.get("valid_from") or "")[:10]
    vt = str(hit.get("valid_to") or "")[:10]
    today = now.strftime("%Y-%m-%d")
    if vf and vf > today:
        return False, f"未生效（valid_from={vf}）"
    if vt and vt < today:
        return False, f"已过期（valid_to={vt}）"
    return True, "有效"


def detect_conflict(hits: list[dict]) -> list[dict]:
    """同主题政策条目间的冲突标记（就地标注 _conflict_region 后原样返回）。
    规则：同 topic 政策条目 region 集合互不相同 → 组内互标；
    或单条目本身含 ≥2 个不同地区（多地区政策文件）→ 标记。
    """
    for h in hits:
        h.setdefault("_conflict_region", False)

    def _policy_topic(h: dict) -> bool:
        return str(h.get("topic") or "") in ("行业动态与政策", "电价与收益")

    groups: dict[str, list[dict]] = {}
    for h in hits:
        if _policy_topic(h) or extract_regions(" ".join(str(x) for x in (h.get("title") or ""))):
            groups.setdefault(str(h.get("topic") or "_"), []).append(h)

    for group in groups.values():
        if len(group) < 2:
            continue
        sigs = []
        for h in group:
            rs = h.get("region") or []
            if isinstance(rs, str):
                rs = [rs]
            sigs.append(frozenset(_norm_region(str(r)) for r in rs if r))
        if len(set(sigs)) > 1:
            for h in group:
                h["_conflict_region"] = True
        for h, sig in zip(group, sigs):
            if len(sig) >= 2:
                h["_conflict_region"] = True
    return hits


def filter_policy_evidence(hits: list[dict], query: str) -> tuple[list[dict], str | None]:
    """检索后过滤闭环。返回 (保留证据, 拒答原因|None)。
    - 无证据 → 拒答
    - 政策题且查询含地区 → 仅保留命中该地区证据，全空 → 拒答
    - 政策题时间过期/未生效 → 剔除，全空 → 拒答
    - 最高语义分 < 0.35 → 拒答（防弱相关误导）
    """
    hits = detect_conflict([dict(h) for h in (hits or [])])
    if not hits:
        return [], "无检索证据"

    policy = is_policy_question(query)
    kept = hits

    if policy and extract_regions(query):
        kept = [h for h in kept if _hit_region_matches(query, h)]
        if not kept:
            return [], "地区不匹配"

    if policy:
        now = datetime.now(timezone.utc)
        valid = [h for h in kept if check_time_validity(h, now)[0]]
        if kept and not valid:
            return [], "证据过期"
        kept = valid or kept

    max_sem = max((float(h.get("semantic") or 0) for h in kept), default=0.0)
    if max_sem < 0.35:
        return [], "语义分过低"

    return kept, None


def format_kb_context(hits: list[dict]) -> str:
    """证据块格式化（带 [n] 编号、地区/日期/权威度元数据）。"""
    lines = []
    for i, h in enumerate(hits or [], 1):
        title = str(h.get("title") or "")
        region = h.get("region") or []
        if isinstance(region, str):
            region = [region]
        region_s = "、".join(str(r) for r in region if r) or "通用"
        date = str(h.get("updated_at") or h.get("date") or "")[:10] or "—"
        auth = h.get("authority") or []
        if isinstance(auth, str):
            auth = [auth]
        auth_s = "、".join(str(a) for a in auth if a) or "—"
        path = str(h.get("path") or h.get("source") or "")
        conflict = " ⚠冲突" if h.get("_conflict_region") else ""
        lines.append(
            f"[{i}] 《{title}》{conflict}\n"
            f"    地区: {region_s} | 日期: {date} | 权威: {auth_s}\n"
            f"    路径: {path}\n"
            f"    {h.get('snippet') or ''}"
        )
    return "\n\n".join(lines)


def format_kb_rules(has_evidence: bool) -> str:
    """系统提示词的知识库使用规则片段。"""
    if has_evidence:
        return """
【知识库资料使用规则】
- 资料片段带 [n] 编号；回答结论后紧跟引用编号，如 [1][3]。
- 回答末尾用「来源：」列出引用过的资料标题、路径与日期。
- 政策/电价/并网类问题：先核对资料的地区与时间是否与用户问题一致，再作答。
- 多份资料冲突时，在回答中明确列出冲突项，并优先采用官方/标准/论文/较新版本 [冲突]。
- 资料不足以支撑结论时，明确说「知识库暂无直接依据」，不得编造。"""
    return """
【知识库资料使用规则】
- 当前知识库暂无与问题直接相关的证据；若问题涉及政策/电价/地区标准，
  应明确说明「知识库暂无该信息，不足以回答」，不得凭记忆编造具体数值与政策条款。"""


def refusal_message(reason: str, query: str) -> str:
    """标准拒答语（不经过 LLM）。"""
    return (
        f"知识库暂无可靠证据回答「{query}」（原因：{reason}）。"
        f"我不掌握可引用的直接依据，不做推测性回答；"
        f"可尝试更换问题措辞，或补充地区/时间等限定后再问。"
    )
