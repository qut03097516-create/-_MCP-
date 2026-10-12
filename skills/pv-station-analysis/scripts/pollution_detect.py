# -*- coding: utf-8 -*-
"""
pollution_detect.py - PVGIS-ERA5 时序数据 9 类污染检测

检测类别 (对应真实传感器失效模式):
  dropout             缺失块 (时间不连续)
  reconstructed       重建/插值标记 (Int != 0)
  stuck               卡死段 (值恒定而辐照变化)
  spike               尖峰 (P 超物理上限)
  drift               月效率漂移 (连续多月偏离基线)
  time_shift          时间平移 (P 与辐照峰值错位)
  night_phantom_power 夜间假功率 (G=0 但 P>0)
  attenuation         衰减段 (中午高辐照下效率异常低)
  noise               噪声 (P-G 残差 std 过大)

输入: PVGIS 导出的逐小时 CSV (含 time,P,Gb(i),Gd(i),Gr(i),H_sun,T2m,WS10m,Int 列;
      自动跳过元数据头部与尾部图例块)。
输出: 人类可读摘要 (stdout) + 结构化异常清单 JSON (--output 指定, 默认 stdout)。
判定三态: 硬性六类(含 noise)命中 → POLLUTED; 仅软性三类命中 → SUSPECTED
      (疑似, 需人工研判); 全部未命中 → clean。

仅使用 Python 标准库。阈值均可通过命令行参数覆盖, 默认值来自 30.542/101.948
站点 2005-2023 数据集上验证通过的基准。

用法:
  python pollution_detect.py input.csv
  python pollution_detect.py input.csv --output anomalies.json
  python pollution_detect.py input.csv --nominal-power-kwp 1.0 --spike-ratio 1.0
"""

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

HEADER_KEYS = ("Latitude", "Longitude", "Elevation", "Radiation", "Slope",
               "Azimuth", "Nominal", "System", "time,P")


def parse_csv(path):
    """解析 PVGIS CSV, 返回 [(datetime, time_str, [P,Gb,Gd,Gr,H_sun,T2m,WS10m,Int]), ...]"""
    rows = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith(HEADER_KEYS):
                continue
            if not line[0].isdigit() or len(line.split(",")) < 9:
                continue  # 尾部图例/版权文本
            parts = line.split(",")
            try:
                dt = datetime.strptime(parts[0], "%Y%m%d:%H%M")
                vals = [float(x) for x in parts[1:9]]
            except ValueError:
                continue
            rows.append((dt, parts[0], vals))
    rows.sort(key=lambda x: x[0])
    return rows


def linear_fit(xs, ys):
    """最小二乘 y = a*x + b, 返回 (a, b)"""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, my
    a = sxy / sxx
    return a, my - a * mx


def detect_dropout(rows, min_gap_hours=1):
    """缺失块: 相邻时间间隔 > min_gap_hours 小时"""
    gaps = []
    for i in range(1, len(rows)):
        delta = rows[i][0] - rows[i - 1][0]
        if delta != timedelta(hours=1):
            hours = int(delta.total_seconds() // 3600)
            if hours > min_gap_hours:
                gaps.append({
                    "from": rows[i - 1][1],
                    "to": rows[i][1],
                    "gap_hours": hours,
                })
    return {
        "blocks": len(gaps),
        "gap_hours_total": sum(g["gap_hours"] for g in gaps),
        "details": gaps,
    }


def detect_reconstructed(rows):
    """重建标记: Int 列 != 0"""
    found = [r for r in rows if r[2][7] != 0]
    return {
        "rows": len(found),
        "details": [
            {"time": r[1], "P": round(r[2][0], 2),
             "Gb": round(r[2][1], 2), "Gd": round(r[2][2], 2), "Gr": round(r[2][3], 2)}
            for r in found[:50]
        ],
    }


def detect_spike(rows, nominal_power_kwp=1.0, spike_ratio=1.0):
    """尖峰: P 超过 标称功率(W) * spike_ratio"""
    threshold = nominal_power_kwp * 1000.0 * spike_ratio
    found = [r for r in rows if r[2][0] > threshold]
    found_sorted = sorted(found, key=lambda r: -r[2][0])
    max_p = found_sorted[0][2][0] if found_sorted else 0.0
    p2500 = sum(1 for r in found if r[2][0] == 2500.0)
    return {
        "threshold_w": threshold,
        "rows": len(found),
        "max_p_w": max_p,
        "hard_cap_hits": p2500,
        "details": [
            {"time": r[1], "P": round(r[2][0], 1),
             "Gtot": round(r[2][1] + r[2][2] + r[2][3], 1)}
            for r in found_sorted[:50]
        ],
    }


def detect_stuck(rows, min_hours=6, day_start=7, day_end=18):
    """卡死: 白天时段 P 连续 min_hours 小时恒定 (值 > 1W), 且辐照有变化"""
    segs = []
    cur_start = None
    cur_start_idx = None
    cur_val = None
    cur_len = 0
    for i, (dt, ts, vals) in enumerate(rows):
        hour = dt.hour
        is_day = day_start <= hour <= day_end
        p = round(vals[0], 2)
        if p == cur_val and is_day and p > 1:
            cur_len += 1
        else:
            if cur_len >= min_hours and cur_start_idx is not None:
                j0, j1 = cur_start_idx, i - 1
                gg = [rows[j][2][1] + rows[j][2][2] + rows[j][2][3]
                      for j in range(j0, j1 + 1)]
                segs.append({
                    "from": cur_start,
                    "to": rows[j1][1],
                    "hours": cur_len,
                    "value_w": cur_val,
                    "g_range_wm2": round(max(gg) - min(gg), 1),
                })
            cur_start = ts
            cur_start_idx = i
            cur_val = p
            cur_len = 1
    if cur_len >= min_hours and cur_start_idx is not None:
        j0, j1 = cur_start_idx, len(rows) - 1
        gg = [rows[j][2][1] + rows[j][2][2] + rows[j][2][3]
              for j in range(j0, j1 + 1)]
        segs.append({
            "from": cur_start,
            "to": rows[j1][1],
            "hours": cur_len,
            "value_w": cur_val,
            "g_range_wm2": round(max(gg) - min(gg), 1),
        })
    return {
        "segments": len(segs),
        "rows": sum(s["hours"] for s in segs),
        "details": segs[:50],
    }


def detect_night_phantom(rows, g_threshold=0.05, p_threshold=5.0):
    """夜间假功率: 总辐照几乎为 0 而 P 残留 > p_threshold W"""
    found = []
    for r in rows:
        g = r[2][1] + r[2][2] + r[2][3]
        if g <= g_threshold and r[2][0] > p_threshold:
            found.append(r)
    pmax = max(found, key=lambda r: r[2][0]) if found else None
    buckets = Counter()
    for r in found:
        buckets[round(r[2][0] / 10) * 10] += 1
    return {
        "rows": len(found),
        "max_p_w": round(pmax[2][0], 2) if pmax else 0.0,
        "p_distribution_10w": dict(sorted(buckets.items())),
    }


def detect_attenuation(rows, eff_quantile=0.02, min_hours=3, hours=(11, 12, 13, 14),
                       min_g=600.0, min_p=100.0):
    """衰减段: 中午高辐照 (G>min_g, P>min_p) 下效率低于**同月份**动态分位阈值,
    连续 >=min_hours 小时。

    阈值按月份分位计算 (修复 v1.1.0 固定全局分位的过度告警): 冬季整月高效时
    基线随当月分布抬高, 不再用全年阈值把季节性效率差异误判为衰减;
    中午高辐照候选序列内, 被低辐照/云遮挡过滤掉的行不打断段 (衰减是持续现象)。
    """
    mid = []
    for i, (dt, ts, vals) in enumerate(rows):
        if dt.hour in hours:
            g = vals[1] + vals[2] + vals[3]
            if g > min_g and vals[0] > min_p and g < 1400.0:
                mid.append((i, dt.month, vals[0] / g))
    if not mid:
        return {"segments": 0, "rows": 0, "threshold": None,
                "threshold_range": None, "threshold_by_month": {}, "details": []}
    # 按月份分位动态基线: 每个日历月(跨年合并)独立取分位阈值
    by_month = defaultdict(list)
    for i, m, e in mid:
        by_month[m].append(e)
    thr_of = {}
    for m, es in by_month.items():
        es = sorted(es)
        idx = int(len(es) * eff_quantile)
        thr_of[m] = es[min(idx, len(es) - 1)]
    seg_set = []
    cur = []
    for i, m, e in mid:
        if e < thr_of[m]:
            cur.append((i, e))
        else:
            if len(cur) >= min_hours:
                seg_set.append(cur[:])
            cur = []
    if len(cur) >= min_hours:
        seg_set.append(cur[:])
    segs = []
    for s in seg_set:
        avg = statistics.mean(e for _, e in s)
        segs.append({
            "from": rows[s[0][0]][1],
            "to": rows[s[-1][0]][1],
            "hours": len(s),
            "eff_mean": round(avg, 3),
        })
    return {
        "segments": len(segs),
        "rows": sum(s["hours"] for s in segs),
        "threshold": round(statistics.mean(thr_of.values()), 4),
        "threshold_range": [round(min(thr_of.values()), 4),
                            round(max(thr_of.values()), 4)],
        "threshold_by_month": {str(m): round(thr_of[m], 4)
                               for m in sorted(thr_of)},
        "details": segs[:50],
    }


def detect_noise(rows, day_min_g=50.0, day_min_p=10.0, threshold_w=40.0):
    """噪声: 白天 (G>50, P>10) 的 P-G 线性拟合残差 std; 正常站点 < threshold_w"""
    idx = [i for i in range(len(rows))
           if rows[i][2][1] + rows[i][2][2] + rows[i][2][3] > day_min_g and rows[i][2][0] > day_min_p]
    if len(idx) < 20:
        return {"resid_std_w": None, "threshold_w": threshold_w, "abnormal": False}
    xs = [rows[i][2][1] + rows[i][2][2] + rows[i][2][3] for i in idx]
    ys = [rows[i][2][0] for i in idx]
    a, b = linear_fit(xs, ys)
    resid = [ys[j] - (a * xs[j] + b) for j in range(len(xs))]
    sd = statistics.pstdev(resid)
    # 按月残差std, 统计超过阈值 2.5 倍的异常月
    mstd = defaultdict(list)
    for j, i in enumerate(idx):
        mstd[rows[i][1][:6]].append(resid[j])
    abnormal_months = [m for m in sorted(mstd) if statistics.pstdev(mstd[m]) > threshold_w * 2.5]
    return {
        "resid_std_w": round(sd, 1),
        "threshold_w": threshold_w,
        "fit": {"a": round(a, 4), "b": round(b, 2)},
        "abnormal": sd > threshold_w,
        "abnormal_months": abnormal_months[:100],
        "abnormal_month_count": len(abnormal_months),
    }


def detect_drift(rows, dev_ratio=0.025, min_months=2, min_g=200.0, min_p=30.0):
    """漂移: 月均效率 (G>200, P>30 的行) 连续 >=min_months 个月偏离中位数 ±dev_ratio。

    季节判别 (修复 v1.1.0 过度告警): 11-2 月效率**高于**基线属冬季晴天的季节性
    高效, 不作漂移告警且不计入漂移段 (同时打断连续段); 负向偏离任何月份仍告警。
    """
    monthly = defaultdict(lambda: [0.0, 0])
    for r in rows:
        if r[2][1] + r[2][2] + r[2][3] > min_g and r[2][0] > min_p:
            monthly[r[1][:6]][0] += r[2][0]
            monthly[r[1][:6]][1] += r[2][1] + r[2][2] + r[2][3]
    base = [(m, s / g) for m, (s, g) in sorted(monthly.items()) if g > 0]
    if not base:
        return {"segments": 0, "median_eff": 0, "details": [],
                "seasonal_winter_high_excluded": 0, "seasonal_excluded_months": []}
    med = statistics.median(e for _, e in base)
    winter = {11, 12, 1, 2}
    runs = []
    cur = []
    seasonal_excluded = []
    for m, e in base:
        high = e > med * (1 + dev_ratio)
        low = e < med * (1 - dev_ratio)
        if high and int(m[4:6]) in winter:
            seasonal_excluded.append(m)  # 冬季高效豁免, 视为正常并打断连续段
            is_alarm = False
        else:
            is_alarm = low or high
        if is_alarm:
            cur.append((m, e))
        else:
            if len(cur) >= min_months:
                runs.append(cur[:])
            cur = []
    if len(cur) >= min_months:
        runs.append(cur[:])
    return {
        "median_eff": round(med, 4),
        "segments": len(runs),
        "seasonal_winter_high_excluded": len(seasonal_excluded),
        "seasonal_excluded_months": seasonal_excluded[:50],
        "details": [
            {"months": [m for m, _ in r], "eff_min": round(min(e for _, e in r), 4),
             "eff_max": round(max(e for _, e in r), 4)}
            for r in runs[:50]
        ],
    }


def detect_time_shift(rows, min_shift_hours=4, min_p_w=500.0, min_days=5):
    """时间平移: 逐日 P 峰值小时与辐照峰值小时同向偏差 >= min_shift_hours 小时,
    且连续 >= min_days 天 (单日/短期峰值错位多为正常天气波动;
    min_days 由 3 提至 5, 修复 v1.1.0 对孤立 3 天事件的过度告警)"""
    by_day = defaultdict(list)
    for i, (dt, ts, vals) in enumerate(rows):
        by_day[dt.date()].append(i)
    raw = []
    for d, idxs in sorted(by_day.items()):
        if len(idxs) < 12:
            continue
        pl = [(rows[i][2][0], i) for i in idxs]
        gl = [(rows[i][2][1] + rows[i][2][2] + rows[i][2][3], i) for i in idxs]
        p_max = max(pl, key=lambda x: x[0])
        g_max = max(gl, key=lambda x: x[0])
        if p_max[0] < min_p_w:
            continue
        diff_h = rows[p_max[1]][0].hour - rows[g_max[1]][0].hour
        if abs(diff_h) >= min_shift_hours:
            raw.append((d, diff_h, rows[p_max[1]][1], rows[g_max[1]][1],
                        round(p_max[0], 1)))
    # 合并连续同向段
    segs = []
    cur = []
    for d, dh, pt, gt, pw in raw:
        if not cur:
            cur.append((d, dh, pt, gt, pw))
        else:
            prev = cur[-1]
            same_run = (d == prev[0] + timedelta(days=1)
                        and (dh > 0) == (prev[1] > 0))
            if same_run:
                cur.append((d, dh, pt, gt, pw))
            else:
                segs.append(cur)
                cur = [(d, dh, pt, gt, pw)]
    if cur:
        segs.append(cur)
    days_hit = [item for seg in segs if len(seg) >= min_days for item in seg]
    return {
        "days": len(days_hit),
        "segments": sum(1 for seg in segs if len(seg) >= min_days),
        "details": [
            {"date": i[0].strftime("%Y-%m-%d"), "p_peak_time": i[2],
             "g_peak_time": i[3], "shift_hours": i[1], "p_peak_w": i[4]}
            for seg in segs if len(seg) >= min_days for i in seg
        ][:50],
    }


def run_all(path, args):
    rows = parse_csv(path)
    if not rows:
        return {"error": "empty csv"}, rows
    result = {
        "file": path,
        "rows": len(rows),
        "time_range": [rows[0][1], rows[-1][1]],
        "detections": {},
    }
    result["detections"]["dropout"] = detect_dropout(rows)
    result["detections"]["reconstructed"] = detect_reconstructed(rows)
    result["detections"]["spike"] = detect_spike(rows, args.nominal_power_kwp, args.spike_ratio)
    result["detections"]["stuck"] = detect_stuck(rows, args.stuck_hours)
    result["detections"]["night_phantom_power"] = detect_night_phantom(rows)
    if args.attenuation_quantile is not None:
        result["detections"]["attenuation"] = detect_attenuation(
            rows, eff_quantile=args.attenuation_quantile)
    else:
        result["detections"]["attenuation"] = {"segments": "skipped",
                                               "rows": "skipped", "details": []}
    result["detections"]["noise"] = detect_noise(rows, threshold_w=args.noise_std_threshold)
    result["detections"]["drift"] = detect_drift(rows)
    result["detections"]["time_shift"] = detect_time_shift(rows)

    # 汇总判定 (三态, 修复 v1.1.0 对干净数据集的过度告警):
    #   硬性六类 (含 noise 异常) 任一命中 → POLLUTED 需清洗;
    #   仅软性三类 (attenuation/drift/time_shift) 命中 → SUSPECTED 疑似, 需人工研判;
    #   全部未命中 → clean
    d = result["detections"]
    checks = {
        "dropout": d["dropout"]["blocks"] > 0,
        "reconstructed": d["reconstructed"]["rows"] > 0,
        "spike": d["spike"]["rows"] > 0,
        "stuck": d["stuck"]["segments"] > 0,
        "night_phantom_power": d["night_phantom_power"]["rows"] > 0,
        "attenuation": (isinstance(d["attenuation"].get("segments"), int)
                        and d["attenuation"]["segments"] > 0),
        "noise": d["noise"].get("abnormal", False),
        "drift": d["drift"]["segments"] > 0,
        "time_shift": d["time_shift"]["days"] > 0,
    }
    HARD_TYPES = ("dropout", "reconstructed", "spike", "stuck",
                  "night_phantom_power", "noise")
    SOFT_TYPES = ("attenuation", "drift", "time_shift")
    hard_hit = [k for k in HARD_TYPES if checks[k]]
    soft_hit = [k for k in SOFT_TYPES if checks[k]]
    if hard_hit:
        verdict = "POLLUTED (需清洗)"
    elif soft_hit:
        verdict = "SUSPECTED (疑似, 需人工研判)"
    else:
        verdict = "clean"
    result["summary"] = {
        "any_pollution": bool(hard_hit),
        "any_finding": bool(hard_hit) or bool(soft_hit),
        "verdict": verdict,
        "hard_detected": hard_hit,
        "soft_detected": soft_hit,
        "detected_types": hard_hit + soft_hit,
    }
    return result, rows


def print_summary(result):
    d = result["detections"]
    print("=" * 60)
    print("PVGIS 污染检测报告")
    print("=" * 60)
    print("文件:", result["file"])
    print("行数:", result["rows"], " 时间范围:", result["time_range"][0], "->", result["time_range"][1])
    print("-" * 60)
    print("dropout 缺失块      : %d 块 / %d h" % (d["dropout"]["blocks"], d["dropout"]["gap_hours_total"]))
    print("reconstructed 重建  : %d 行 (Int!=0)" % d["reconstructed"]["rows"])
    print("spike 尖峰          : %d 行 (阈值 %dW, 最大 %.0fW, 满量程2500W %d 次)"
          % (d["spike"]["rows"], d["spike"]["threshold_w"], d["spike"]["max_p_w"],
             d["spike"]["hard_cap_hits"]))
    print("stuck 卡死          : %d 段 / %d 行" % (d["stuck"]["segments"], d["stuck"]["rows"]))
    print("night_phantom_power : %d 行 (夜间假功率, 最大 %.1fW)"
          % (d["night_phantom_power"]["rows"], d["night_phantom_power"]["max_p_w"]))
    if isinstance(d["attenuation"].get("segments"), int):
        thr_range = d["attenuation"].get("threshold_range")
        thr_txt = ("%.4f~%.4f (按月)" % tuple(thr_range) if thr_range
                   else "%.4f" % (d["attenuation"].get("threshold") or 0))
        print("attenuation 衰减    : %d 段 / %d 行 (阈值 %s)"
              % (d["attenuation"]["segments"], d["attenuation"]["rows"], thr_txt))
    else:
        print("attenuation 衰减    : skipped")
    print("noise 噪声          : 残差std=%.1fW (阈值 %.0fW, %s, 异常月 %d 个)"
          % (d["noise"]["resid_std_w"] or 0, d["noise"]["threshold_w"],
             "异常" if d["noise"]["abnormal"] else "正常",
             d["noise"]["abnormal_month_count"]))
    drift_note = ""
    if d["drift"].get("seasonal_winter_high_excluded"):
        drift_note = ", 冬季高效豁免 %d 月" % d["drift"]["seasonal_winter_high_excluded"]
    print("drift 漂移          : %d 段 (月效率中位数 %.4f%s)"
          % (d["drift"]["segments"], d["drift"]["median_eff"], drift_note))
    print("time_shift 平移     : %d 天" % d["time_shift"]["days"])
    print("-" * 60)
    s = result["summary"]
    print("判定:", s["verdict"])
    print("  硬性/噪声 (→POLLUTED):", ", ".join(s["hard_detected"]) or "无",
          "| 软性 (→SUSPECTED):", ", ".join(s["soft_detected"]) or "无")


def main():
    ap = argparse.ArgumentParser(description="PVGIS-ERA5 时序数据 9 类污染检测")
    ap.add_argument("input", help="PVGIS CSV 文件路径")
    ap.add_argument("--output", "-o", default=None, help="异常清单 JSON 输出路径 (默认 stdout)")
    ap.add_argument("--nominal-power-kwp", type=float, default=1.0,
                    help="系统标称功率 kWp (默认 1.0)")
    ap.add_argument("--spike-ratio", type=float, default=1.0,
                    help="尖峰阈值 = 标称功率(W) * ratio (默认 1.0)")
    ap.add_argument("--stuck-hours", type=int, default=6,
                    help="卡死判定最小连续小时数 (默认 6)")
    ap.add_argument("--noise-std-threshold", type=float, default=40.0,
                    help="P-G 残差 std 告警阈值 W (默认 40)")
    ap.add_argument("--attenuation-quantile", type=float, default=0.02,
                    help="衰减段效率分位阈值 (默认 0.02; 传 0 关闭该项)")
    args = ap.parse_args()

    result, rows = run_all(args.input, args)
    if "error" in result:
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)
    print_summary(result)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2, default=str)
        print("\n清单已写入:", args.output)
    else:
        print("\n" + json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()