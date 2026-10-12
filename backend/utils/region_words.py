#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
region_words.py —— 地区关键词表（省份/直辖市/自治区全称与简称）

用于 M3.3 reranker 的地区匹配：查询提到某个地区时，
语料 region 元数据与查询中的地区一致则加分，不一致则惩罚。
"""
import re

_REGION_FULL = [
    "北京市", "天津市", "上海市", "重庆市",
    "河北省", "山西省", "辽宁省", "吉林省", "黑龙江省",
    "江苏省", "浙江省", "安徽省", "福建省", "江西省",
    "山东省", "河南省", "湖北省", "湖南省", "广东省",
    "海南省", "四川省", "贵州省", "云南省", "陕西省",
    "甘肃省", "青海省", "台湾省",
    "内蒙古自治区", "广西壮族自治区", "西藏自治区",
    "宁夏回族自治区", "新疆维吾尔自治区",
    "香港特别行政区", "澳门特别行政区",
]
# 省份简称（用于口语查询 "山东 电价"）
_REGION_ABBR = [
    "北京", "天津", "上海", "重庆",
    "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西",
    "山东", "河南", "湖北", "湖南", "广东",
    "海南", "四川", "贵州", "云南", "陕西",
    "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆",
    "香港", "澳门",
]

# GB/T 2260 行政区划代码前缀（城市级），例如 "山西 太原"
_CITY_PREFIX_RE = re.compile(
    r"(山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|"
    r"广东|海南|四川|贵州|云南|陕西|甘肃|青海|河北|内蒙古|广西|西藏|宁夏|新疆)"
)

REGION_TERMS: list = _REGION_FULL + _REGION_ABBR


def extract_regions(query: str) -> list:
    """从查询文本中提取地区关键词（按词表全称/简称匹配）。"""
    q = query or ""
    hits = []
    for term in REGION_TERMS:
        if term and term in q:
            # 避免 "海南省" 与 "海南" 重复
            if any(h in term for h in hits) or any(term in h for h in hits):
                merged = False
                for i, h in enumerate(hits):
                    if h in term:
                        hits[i] = term
                        merged = True
                        break
                    if term in h:
                        merged = True
                        break
                if not merged:
                    hits.append(term)
            else:
                hits.append(term)
    return hits