#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
대한민국 지역 x 성 x 연령 표본 할당표 생성기
==============================================

행정안전부 주민등록 인구통계(2025년 12월 기준) 스냅샷을 읽어
전국 n명(기본 10,000명) 표본을 지역 x 성별 x 연령대 셀에
인구 비례로 배분한다.

지역 구분 규칙 (요청 사양)
  - 특별시/광역시 : 자치구·군 단위 (예: 서울특별시 종로구, 부산광역시 기장군)
  - 도/특별자치도 : 시·군 단위     (예: 경기도 성남시  <- 수정/중원/분당구를 합산)
  - 세종특별자치시 : 단일 지역
  => 총 229개 기초 지역

배분 방식 (주변합 통제 반올림, controlled rounding)
  1) 목표치 계산 (모두 최대잔여법 / Hare quota)
       - 시도 목표치   : 17개 시도 인구비례            (합 = n)
       - 지역 목표치   : 각 시도 안에서 시군구 인구비례 (합 = 시도 목표치)
       - 성연령 목표치 : 전국 성 x 연령 인구비례        (합 = n)
  2) 1차 배분 : 각 지역의 배정량을 그 지역 고유의 성 x 연령 구성비로
                최대잔여법 배분 -> 지역 합계는 목표치와 정확히 일치
  3) 보정     : 전국 성연령 합계가 목표치에서 어긋난 만큼만,
                과잉 셀 -1 / 부족 셀 +1 을 같은 지역 안에서 맞교환한다.
                교환 대상은 이론값 대비 제곱오차 증가가 가장 작은 지역을 고른다.
                지역 합계는 교환이므로 그대로 유지된다.

  => 시도 합계, 229개 지역 합계, 전국 성 x 연령 합계가 모두 인구비례
     이론값과 +-1명 이내로 일치하고, 전체 합계는 정확히 n이 된다.

  셀 단위로 한 번만 최대잔여법을 적용하면 울릉군(이론값 1.7명)처럼 셀이
  잘게 쪼개진 소규모 지역이 0명이 되고, 보정 없이 지역별로만 배분하면
  전국 성연령 합계가 목표치에서 20명 이상 밀린다. 위 절차는 두 왜곡을
  모두 없애면서, 소규모 지역의 연령 구성도 그 지역 실제 구성비를 따르게 한다.

연령 기준 시나리오 (--schemes 로 선택, 기본은 전부)
  age14plus : 만 14세 이상 / 14-19세, 20대~60대, 70세 이상      (7구간)
  all_ages  : 전 연령       / 0-9세, 10대~70대, 80세 이상        (9구간)
  adults    : 만 20세 이상  / 20대~60대, 70세 이상               (6구간)

  원자료가 5세 단위이므로 만 14세는 밴드 경계와 맞지 않는다. '10-14세' 밴드
  안에서 균등분포를 가정하고 1/5을 만 14세 인구로 잡는다(지역 x 성별로 반올림).
  실제로는 출생아 수 감소 때문에 밴드 안에서 만 14세가 만 10세보다 조금 많아
  참값은 1/5보다 근소하게 크지만, 전체 모집단에서 차지하는 비중 차이는
  0.1%p 미만이라 배분 결과에는 사실상 영향이 없다.

사용법
  python3 scripts/build_sampling_quota.py [-n 10000] [--outdir data/sampling]
  python3 scripts/build_sampling_quota.py --schemes age14plus
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_SRC = os.path.join(ROOT, "data", "population", "pop_202512.json")
DEFAULT_OUT = os.path.join(ROOT, "data", "sampling")

# 원본 5세 단위 연령대 인덱스: 0='0-4', 1='5-9', ... 20='100+'
BAND_YEARS = 5

# 시나리오별 연령 그룹 정의: (그룹명, 밴드 명세)
#   밴드 명세는 5세 밴드 인덱스의 리스트이며, 밴드 일부만 쓸 때는
#   (인덱스, 가중치) 튜플로 적는다. 예) (2, 0.2) = '10-14세' 밴드의 1/5 = 만 14세
SCHEMES = OrderedDict()
SCHEMES["age14plus"] = {
    "label": "만 14세 이상",
    "note": "만 14세 인구는 '10-14세' 밴드의 1/5로 추정",
    "groups": [
        ("14-19세", [(2, 0.2), 3]),
        ("20대", [4, 5]),
        ("30대", [6, 7]),
        ("40대", [8, 9]),
        ("50대", [10, 11]),
        ("60대", [12, 13]),
        ("70세 이상", [14, 15, 16, 17, 18, 19, 20]),
    ],
}
SCHEMES.update({
    "all_ages": {
        "label": "전 연령(0세 이상)",
        "groups": [
            ("0-9세", [0, 1]),
            ("10대", [2, 3]),
            ("20대", [4, 5]),
            ("30대", [6, 7]),
            ("40대", [8, 9]),
            ("50대", [10, 11]),
            ("60대", [12, 13]),
            ("70대", [14, 15]),
            ("80세 이상", [16, 17, 18, 19, 20]),
        ],
    },
    "adults": {
        "label": "만 20세 이상 성인",
        "groups": [
            ("20대", [4, 5]),
            ("30대", [6, 7]),
            ("40대", [8, 9]),
            ("50대", [10, 11]),
            ("60대", [12, 13]),
            ("70세 이상", [14, 15, 16, 17, 18, 19, 20]),
        ],
    },
})

SEXES = [("남성", "m"), ("여성", "f")]


def load_regions(src):
    """원본 JSON에서 시도명 맵과 229개 기초지역을 뽑아낸다.

    name 필드의 들여쓰기가 계층을 나타낸다.
      공백 0칸 = 전국 / 시도, 1칸 = 시군구(기초), 2칸 = 일반구(성남시 분당구 등)
    일반구는 상위 시에 이미 합산되어 있으므로 제외하고,
    인구 0인 출장소(경기 북부출장소, 강원 동해출장소)도 제외한다.
    """
    with open(src, encoding="utf-8") as fp:
        raw = json.load(fp)

    regions = raw["regions"]
    sido = {code: v["name"].strip() for code, v in regions.items() if len(code) == 2 and code != "00"}

    base = []
    for code, v in sorted(regions.items()):
        if len(code) != 5:
            continue
        indent = len(v["name"]) - len(v["name"].lstrip())
        if indent != 1:          # 일반구 제외
            continue
        if v["total"] <= 0:      # 출장소 제외
            continue
        base.append(
            {
                "code": code,
                "sido_code": code[:2],
                "sido": sido[code[:2]],
                "sgg": v["name"].strip(),
                "m": v["m"],
                "f": v["f"],
                "total": v["total"],
            }
        )
    return raw["meta"], sido, base


def verify(meta, regions_raw_path, sido, base):
    """229개 기초지역 합계가 시도/전국 원본과 정확히 일치하는지 검증."""
    with open(regions_raw_path, encoding="utf-8") as fp:
        regions = json.load(fp)["regions"]

    problems = []
    by_sido = {}
    for r in base:
        acc = by_sido.setdefault(r["sido_code"], [0] * 42)
        for i in range(21):
            acc[i] += r["m"][i]
            acc[i + 21] += r["f"][i]

    national = [0] * 42
    for code, acc in by_sido.items():
        ref = regions[code]["m"] + regions[code]["f"]
        if acc != ref:
            problems.append("시도 불일치: %s %s" % (code, sido[code]))
        for i in range(42):
            national[i] += acc[i]

    ref_nat = regions["00"]["m"] + regions["00"]["f"]
    if national != ref_nat:
        problems.append("전국 불일치")
    return problems


def cell_populations(base, scheme):
    """(지역, 성, 연령그룹) 셀 목록과 인구를 만든다."""
    cells = []
    for r in base:
        for sex_label, key in SEXES:
            bands = r[key]
            for group_label, spec in scheme["groups"]:
                pop = int(round(sum(
                    bands[i] * w for i, w in
                    ((b if isinstance(b, tuple) else (b, 1.0)) for b in spec)
                )))
                cells.append(
                    {
                        "code": r["code"],
                        "sido": r["sido"],
                        "sgg": r["sgg"],
                        "sex": sex_label,
                        "age": group_label,
                        "pop": pop,
                    }
                )
    return cells


def _largest_remainder(pops, n):
    """인구 벡터 pops를 합이 정확히 n인 정수 벡터로 배분(최대잔여법)."""
    total = sum(pops)
    if total <= 0 or n <= 0:
        return [0] * len(pops), [0.0] * len(pops)
    exact = [n * p / total for p in pops]
    alloc = [int(e) for e in exact]
    leftover = n - sum(alloc)
    order = sorted(range(len(pops)), key=lambda i: (-(exact[i] - alloc[i]), -pops[i]))
    for i in order[:leftover]:
        alloc[i] += 1
    assert sum(alloc) == n
    return alloc, exact


def allocate(cells, n):
    """지역 합계와 전국 성x연령 합계를 함께 통제하는 반올림 배분."""
    total_pop = sum(c["pop"] for c in cells)
    if total_pop <= 0:
        raise ValueError("모집단 인구가 0입니다.")

    idx_by_region = OrderedDict()
    sexage_keys = []
    for i, c in enumerate(cells):
        idx_by_region.setdefault(c["code"], []).append(i)
        key = (c["sex"], c["age"])
        if key not in sexage_keys:
            sexage_keys.append(key)

    codes = list(idx_by_region)
    col_of = {key: j for j, key in enumerate(sexage_keys)}
    n_cols = len(sexage_keys)

    # --- 1) 목표치 : 시도 -> 시군구, 그리고 전국 성연령 ---------------------
    region_pop = [sum(cells[i]["pop"] for i in idx_by_region[code]) for code in codes]
    region_exact = [n * p / total_pop for p in region_pop]

    sido_rows = OrderedDict()
    for r, code in enumerate(codes):
        sido_rows.setdefault(code[:2], []).append(r)
    sido_n, _ = _largest_remainder([sum(region_pop[r] for r in rs) for rs in sido_rows.values()], n)

    region_n = [0] * len(codes)
    for rs, sn in zip(sido_rows.values(), sido_n):
        alloc, _ = _largest_remainder([region_pop[r] for r in rs], sn)
        for r, a in zip(rs, alloc):
            region_n[r] = a

    sexage_pop = [0] * n_cols
    for c in cells:
        sexage_pop[col_of[(c["sex"], c["age"])]] += c["pop"]
    sexage_n, _ = _largest_remainder(sexage_pop, n)

    # --- 2) 1차 배분 : 지역 내부를 그 지역 구성비로 -------------------------
    grid = {}
    for r, code in enumerate(codes):
        idxs = idx_by_region[code]
        alloc, _ = _largest_remainder([cells[i]["pop"] for i in idxs], region_n[r])
        for i, a in zip(idxs, alloc):
            cells[i]["exact"] = n * cells[i]["pop"] / total_pop
            cells[i]["n"] = a
            cells[i]["region_n"] = region_n[r]
            cells[i]["region_exact"] = region_exact[r]
            grid[(r, col_of[(cells[i]["sex"], cells[i]["age"])])] = i

    # --- 3) 보정 : 성연령 주변합을 지역 내 맞교환으로 맞춘다 ----------------
    dev = [sum(cells[grid[(r, j)]]["n"] for r in range(len(codes))) - sexage_n[j]
           for j in range(n_cols)]
    swaps = 0
    while any(dev):
        hi = max(range(n_cols), key=lambda j: dev[j])   # 과잉 열 (-1 할 곳)
        lo = min(range(n_cols), key=lambda j: dev[j])   # 부족 열 (+1 할 곳)
        best, best_cost = None, None
        for r in range(len(codes)):
            src, dst = cells[grid[(r, hi)]], cells[grid[(r, lo)]]
            if src["n"] <= 0:
                continue
            # 제곱오차 증가분: (n-1-e)^2-(n-e)^2 = 1-2(n-e), (n+1-e)^2-(n-e)^2 = 1+2(n-e)
            cost = (1 - 2 * (src["n"] - src["exact"])) + (1 + 2 * (dst["n"] - dst["exact"]))
            if best_cost is None or cost < best_cost:
                best, best_cost = r, cost
        if best is None:
            raise RuntimeError("성연령 주변합 보정 실패: 교환 가능한 지역이 없습니다.")
        cells[grid[(best, hi)]]["n"] -= 1
        cells[grid[(best, lo)]]["n"] += 1
        dev[hi] -= 1
        dev[lo] += 1
        swaps += 1

    # --- 검증 ---------------------------------------------------------------
    assert sum(c["n"] for c in cells) == n
    for r, code in enumerate(codes):
        assert sum(cells[i]["n"] for i in idx_by_region[code]) == region_n[r]
    for j in range(n_cols):
        assert sum(cells[grid[(r, j)]]["n"] for r in range(len(codes))) == sexage_n[j]
    for rs, sn in zip(sido_rows.values(), sido_n):
        assert sum(region_n[r] for r in rs) == sn

    return total_pop, swaps


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(header)
        w.writerows(rows)


def build(scheme_key, base, n, outdir, meta):
    scheme = SCHEMES[scheme_key]
    cells = cell_populations(base, scheme)
    total_pop, swaps = allocate(cells, n)

    group_labels = [g[0] for g in scheme["groups"]]
    sex_labels = [s[0] for s in SEXES]

    # --- 1) 셀 단위 롱 포맷 -------------------------------------------------
    long_rows = [
        [c["code"], c["sido"], c["sgg"], c["sex"], c["age"], c["pop"],
         round(c["pop"] / total_pop * 100, 6), round(c["exact"], 4), c["n"]]
        for c in cells
    ]
    write_csv(
        os.path.join(outdir, "quota_%s_cells_n%d.csv" % (scheme_key, n)),
        ["행정구역코드", "시도", "시군구", "성별", "연령대", "인구", "인구비중(%)", "이론표본", "배정표본"],
        long_rows,
    )

    # --- 2) 지역 x (성별,연령대) 와이드 포맷 --------------------------------
    order = OrderedDict()
    for c in cells:
        key = (c["code"], c["sido"], c["sgg"])
        slot = order.setdefault(key, {"pop": 0, "n": 0, "exact": c["region_exact"], "cells": {}})
        slot["pop"] += c["pop"]
        slot["n"] += c["n"]
        slot["cells"][(c["sex"], c["age"])] = c["n"]

    wide_header = ["행정구역코드", "시도", "시군구", "인구", "인구비중(%)", "이론표본", "표본계"]
    for sex in sex_labels:
        for age in group_labels:
            wide_header.append("%s %s" % (sex, age))

    wide_rows = []
    for (code, sido, sgg), slot in order.items():
        row = [code, sido, sgg, slot["pop"], round(slot["pop"] / total_pop * 100, 4),
               round(slot["exact"], 2), slot["n"]]
        for sex in sex_labels:
            for age in group_labels:
                row.append(slot["cells"][(sex, age)])
        wide_rows.append(row)
    write_csv(os.path.join(outdir, "quota_%s_by_region_n%d.csv" % (scheme_key, n)), wide_header, wide_rows)

    # --- 3) 시도 요약 -------------------------------------------------------
    sido_acc = OrderedDict()
    for c in cells:
        slot = sido_acc.setdefault(c["sido"], {"pop": 0, "n": 0, "regions": set(), "cells": {}})
        slot["pop"] += c["pop"]
        slot["n"] += c["n"]
        slot["regions"].add(c["code"])
        k = (c["sex"], c["age"])
        slot["cells"][k] = slot["cells"].get(k, 0) + c["n"]

    sido_rows = []
    for sido, slot in sido_acc.items():
        row = [sido, len(slot["regions"]), slot["pop"],
               round(slot["pop"] / total_pop * 100, 4), slot["n"]]
        for sex in sex_labels:
            for age in group_labels:
                row.append(slot["cells"].get((sex, age), 0))
        sido_rows.append(row)
    write_csv(
        os.path.join(outdir, "quota_%s_by_sido_n%d.csv" % (scheme_key, n)),
        ["시도", "지역수", "인구", "인구비중(%)", "표본계"]
        + ["%s %s" % (s, a) for s in sex_labels for a in group_labels],
        sido_rows,
    )

    # --- 4) 전국 성연령 요약 ------------------------------------------------
    nat = {}
    natpop = {}
    for c in cells:
        k = (c["sex"], c["age"])
        nat[k] = nat.get(k, 0) + c["n"]
        natpop[k] = natpop.get(k, 0) + c["pop"]
    nat_rows = [
        [s, a, natpop[(s, a)], round(natpop[(s, a)] / total_pop * 100, 4), nat[(s, a)]]
        for s in sex_labels for a in group_labels
    ]
    write_csv(
        os.path.join(outdir, "quota_%s_by_sexage_n%d.csv" % (scheme_key, n)),
        ["성별", "연령대", "인구", "인구비중(%)", "표본"],
        nat_rows,
    )

    return {
        "scheme": scheme_key,
        "label": scheme["label"],
        "n": n,
        "total_pop": total_pop,
        "regions": len(order),
        "cells": len(cells),
        "empty_cells": sum(1 for c in cells if c["n"] == 0),
        "swaps": swaps,
        "sido_rows": sido_rows,
        "nat_rows": nat_rows,
        "wide_header": wide_header,
        "wide_rows": wide_rows,
        "group_labels": group_labels,
        "sex_labels": sex_labels,
        "meta": meta,
    }


def main():
    ap = argparse.ArgumentParser(description="지역 x 성 x 연령 표본 할당표 생성")
    ap.add_argument("-n", "--size", type=int, default=10000, help="총 표본 수 (기본 10000)")
    ap.add_argument("--src", default=DEFAULT_SRC, help="주민등록 인구 JSON 경로")
    ap.add_argument("--outdir", default=DEFAULT_OUT, help="CSV 출력 디렉터리")
    ap.add_argument("--schemes", nargs="+", choices=list(SCHEMES), default=list(SCHEMES),
                    help="생성할 연령 기준 시나리오 (기본: 전부)")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    meta, sido, base = load_regions(args.src)

    problems = verify(meta, args.src, sido, base)
    if problems:
        raise SystemExit("데이터 검증 실패:\n  " + "\n  ".join(problems))

    print("기준 시점 : %s (%s)" % (meta["date"], meta["source"]))
    print("기초 지역 : %d개 (시도 %d개)" % (len(base), len(sido)))
    print("검증      : 229개 지역 합계 = 시도 합계 = 전국 합계 (성/5세연령 전 셀 일치)")

    summaries = {}
    for key in args.schemes:
        s = build(key, base, args.size, args.outdir, meta)
        summaries[key] = s
        print()
        print("[%s] 모집단 %s명 -> 표본 %s명, 셀 %d개(%d x %d x %d), 0명 셀 %d개, 보정교환 %d회"
              % (s["label"], format(s["total_pop"], ","), format(s["n"], ","),
                 s["cells"], s["regions"], len(s["sex_labels"]), len(s["group_labels"]),
                 s["empty_cells"], s["swaps"]))
        print("  시도별 표본:")
        for row in s["sido_rows"]:
            print("    %-10s %6.3f%%  %5d명" % (row[0], row[3], row[4]))

    summary_path = os.path.join(args.outdir, "summary_n%d.json" % args.size)
    merged = {}
    if os.path.exists(summary_path):
        with open(summary_path, encoding="utf-8") as fp:
            merged = json.load(fp)
    with open(summary_path, "w", encoding="utf-8") as fp:
        merged.update(
            {
                k: {
                    "label": v["label"], "n": v["n"], "total_pop": v["total_pop"],
                    "regions": v["regions"], "cells": v["cells"], "empty_cells": v["empty_cells"],
                    "sex_labels": v["sex_labels"], "group_labels": v["group_labels"],
                    "sido_header": ["시도", "지역수", "인구", "인구비중(%)", "표본계"]
                    + ["%s %s" % (s, a) for s in v["sex_labels"] for a in v["group_labels"]],
                    "sido_rows": v["sido_rows"],
                    "sexage_rows": v["nat_rows"],
                    "region_header": v["wide_header"],
                    "region_rows": v["wide_rows"],
                }
                for k, v in summaries.items()
            }
        )
        json.dump(OrderedDict((k, merged[k]) for k in SCHEMES if k in merged),
                  fp, ensure_ascii=False)
    print("\nCSV 출력 완료 -> %s" % args.outdir)


if __name__ == "__main__":
    main()
