# -*- coding: utf-8 -*-
from __future__ import annotations
import os, re, random, logging, difflib
from typing import Dict, List, Tuple, Optional
import pandas as pd

EXCEL_PATH = os.path.join(os.path.dirname(__file__), "subjects+Notes.xlsx")

CAT_MAP = {
    "متطلبات الجامعة الاجبارية": "university_required",
    "متطلبات الجامعة الإجباري": "university_required",
    "متطلبات الجامعة الاختيارية": "elective_requirements",
    "متطلبات الكلية الاجبارية": "college_required",
    "متطلبات التخصص الاجبارية": "major_required",
    "متطلبات التخصص الاختيارية": "major_optional",
    "مواد استدراكية": "Remedial materials",
}

CATEGORY_LIMITS = {
    "university_required": 18,
    "elective_requirements": 9,
    "college_required": 32,
    "major_required": 93,
    "major_optional": 9,
    "Remedial materials": 9,
}

MIN_HOURS_BY_CODE: Dict[str, int] = {
    "ELE5467": 115, "ELE5455": 120, "ELE5559": 90,  "ELE5556": 90,
    "ELE5557": 90,  "ELE5558": 90,  "ELE5560": 90,  "ELE5561": 90,
    "ELE5562": 90,  "ELE5565": 90,  "ELE5555": 90,  "ELE5666": 90,
    "ELE5512": 90,  "ELE5527": 90,  "ELE5552": 90,  "ELE5553": 90,
}

# context set by app.py
max_hours: int = 18
offered: Dict[str, dict] = {}            # keys: plan-name; values: {code,hours,sections:[]...}
taken_courses: Dict[str, dict] = {}      # {plan-name: {hours}}
name_by_code: Dict[str, str] = {}        # filled if Excel has a code column

def guess_category(text: str) -> str:
    if not isinstance(text, str): return ""
    for k, v in CAT_MAP.items():
        if k in text: return v
    if "اجبار" in text:
        if "جامعة" in text: return "university_required"
        if "كلية"  in text: return "college_required"
        if "تخصص" in text: return "major_required"
    if "اختيار" in text:
        if "جامعة" in text: return "elective_requirements"
        if "تخصص" in text: return "major_optional"
    return ""

def _parse_min_hours(txt: str) -> Optional[int]:
    if not isinstance(txt, str): return None
    m = re.search(r"(\d+)\s*ساعة", txt)
    return int(m.group(1)) if m else None

def _norm_ar(s: str) -> str:
    if not isinstance(s, str): return ""
    s = s.strip()
    s = s.replace("ـ","").replace("–","-").replace("—","-")
    s = re.sub(r"[\u064B-\u0652\u0670]", "", s)
    s = s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    s = (s.replace("أ","ا").replace("إ","ا").replace("آ","ا")
           .replace("ى","ي").replace("ة","ه").replace("ؤ","و").replace("ئ","ي"))
    s = re.sub(r"[()\[\]{}،,:;|]+"," ", s)
    s = re.sub(r"\s+"," ", s)
    return s.strip()

def load_plan_from_excel(path: str) -> Dict[str, dict]:
    global name_by_code
    df = pd.read_excel(path, sheet_name=0)
    df = df[df["اسم المادة"].notna()].copy()
    df["اسم المادة"] = df["اسم المادة"].astype(str).str.strip()

    code_col = None
    for c in ["الكود", "code", "Code", "CODE", "كود", "رمز"]:
        if c in df.columns:
            code_col = c
            break

    names = df["اسم المادة"].tolist()
    plan: Dict[str, dict] = {}
    name_by_code = {}

    for _, row in df.iterrows():
        name = str(row.get("اسم المادة", "")).strip()
        if not name:
            continue
        hrs = row.get("عدد الساعات")
        try: hours = int(hrs) if not pd.isna(hrs) else 3
        except Exception: hours = 3

        category = guess_category(row.get("تصنيف المادة", ""))

        prereqs = []
        pre_txt = row.get("متطلب لاختيار الماده", "")
        if isinstance(pre_txt, str) and pre_txt.strip():
            for other in names:
                other = str(other).strip()
                if other and other != name and other in pre_txt:
                    prereqs.append(other)

        min_hours = _parse_min_hours(str(pre_txt)) or _parse_min_hours(str(row.get("ملاحظات", "")))

        code_val = None
        if code_col:
            v = row.get(code_col)
            if isinstance(v, str) and v.strip():
                code_val = re.sub(r"\s+", "", v.strip()).upper()
            elif pd.notna(v):
                code_val = str(v).strip().upper()
            if code_val:
                name_by_code[code_val] = name

        plan[name] = {
            "name": name,
            "code": code_val,
            "category": category,
            "hours": hours,
            "prerequisites": sorted(set(prereqs)),
            "min_hours": int(min_hours) if min_hours else None,
            "norm": _norm_ar(name),
        }
    return plan

logging.basicConfig(level=logging.INFO)
try:
    plan: Dict[str, dict] = load_plan_from_excel(EXCEL_PATH)
    logging.info(f"[engine] Loaded {len(plan)} subjects from {EXCEL_PATH}")
except Exception:
    logging.exception("[engine] Excel load failed; using minimal fallback")
    plan = {
        "لغة انجليزية تطبيقية ١": {"name":"لغة انجليزية تطبيقية ١","category":"university_required","hours":3,"prerequisites":[],"min_hours":None,"norm":_norm_ar("لغة انجليزية تطبيقية ١"),"code":None},
        "رياضيات 1": {"name":"رياضيات 1","category":"college_required","hours":3,"prerequisites":[],"min_hours":None,"norm":_norm_ar("رياضيات 1"),"code":None},
        "فيزياء 1": {"name":"فيزياء 1","category":"college_required","hours":3,"prerequisites":[],"min_hours":None,"norm":_norm_ar("فيزياء 1"),"code":None},
        "برمجة 1": {"name":"برمجة 1","category":"major_required","hours":3,"prerequisites":[],"min_hours":None,"norm":_norm_ar("برمجة 1"),"code":None},
        "برمجة 2": {"name":"برمجة 2","category":"major_required","hours":3,"prerequisites":["برمجة 1"],"min_hours":None,"norm":_norm_ar("برمجة 2"),"code":None},
    }

# ---- time/conflict helpers ----
AR_DIGITS   = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
DAY_MAP     = {"ح":0, "ن":1, "ث":2, "ر":3, "خ":4, "ج":5, "س":6}
DAY_PATTERN = re.compile(r"[حنثرخجس]")
TIME_PATTERN= re.compile(r"(\d{2}):(\d{2})")

def to_24h_minutes(hh: str, mm: str) -> int:
    h = int(hh); m = int(mm)
    if 1 <= h <= 7: h += 12
    return h * 60 + m

def _split_slots(v):
    if isinstance(v, list): slots = v
    else: slots = re.split(r"[|,\n،]+", str(v or ""))
    return [s.strip() for s in slots if s and s.strip()]

def slot_to_intervals(slot_str: str):
    s = str(slot_str or "").translate(AR_DIGITS)
    days  = DAY_PATTERN.findall(s)
    times = TIME_PATTERN.findall(s)
    if not days or len(times) < 2: return []
    start = to_24h_minutes(*times[0])
    end   = to_24h_minutes(*times[1])
    if end <= start: end += 12*60
    return [(DAY_MAP[d], start, end) for d in days]

def section_to_intervals(section: dict):
    slots = section.get("times") or _split_slots(section.get("time"))
    ivals = []
    for s in slots:
        ivals.extend(slot_to_intervals(s))
    return ivals

def intervals_overlap(a, b) -> bool:
    return a[0] == b[0] and a[1] < b[2] and b[1] < a[2]

def assign_non_conflicting_sections(course_names: List[str], offered_map: dict):
    used = []
    chosen = {}
    for n in course_names:
        meta = offered_map.get(n) or {}
        picked = None
        for sec in meta.get("sections", []):
            ivals = section_to_intervals(sec)
            if not ivals: continue
            ok = True
            for i in ivals:
                for u in used:
                    if intervals_overlap(i, u):
                        ok = False; break
                if not ok: break
            if ok:
                picked = sec
                used.extend(ivals)
                break
        if picked is None:
            return None
        chosen[n] = picked
    return chosen

def _total_completed_hours() -> int:
    return sum(int(v.get("hours", 0)) for v in taken_courses.values())

def _effective_min_hours_for(name: str) -> Optional[int]:
    base = plan.get(name, {}).get("min_hours")
    code = (offered.get(name, {}) or {}).get("code")
    by_code = MIN_HOURS_BY_CODE.get(code) if code else None
    vals = [v for v in (base, by_code) if v is not None]
    return max(vals) if vals else None

def _compute_category_hours(names: List[str]) -> Dict[str,int]:
    res = {k:0 for k in CATEGORY_LIMITS}
    for n in names:
        info = plan.get(n, {})
        cat  = info.get("category")
        if cat in CATEGORY_LIMITS:
            hrs = int((offered.get(n, {}) or {}).get("hours") or info.get("hours") or 0)
            res[cat] += hrs
    return res

# ---- GA ----
POP_SIZE    = 120
GENERATIONS = 120

def _fitness(ind: List[str]) -> float:
    chosen = assign_non_conflicting_sections(ind, offered)
    if not chosen:
        return -1e6

    total_completed = _total_completed_hours()
    total = 0

    for n in ind:
        info = plan.get(n, {})
        if any(p not in taken_courses for p in info.get("prerequisites", [])):
            return -1e6
        min_req = _effective_min_hours_for(n)
        if min_req and total_completed < int(min_req):
            return -1e6
        hrs = int((offered.get(n, {}) or {}).get("hours") or info.get("hours") or 0)
        total += hrs

    if total > max_hours:
        return -1e6

    cat_hours = _compute_category_hours(ind)
    for cat, limit in CATEGORY_LIMITS.items():
        if cat_hours[cat] > limit:
            return -1e6

    score = 1000 + total
    if total >= max_hours - 2: score += 50
    return score

def _initial_population() -> List[List[str]]:
    pool = [n for n in offered.keys() if n in plan and n not in taken_courses]
    if not pool: return [[]]
    pop = []
    for _ in range(POP_SIZE):
        size = random.randint(1, min(len(pool), max(1, max_hours // 2)))
        pop.append(random.sample(pool, size))
    return pop

def _selection(pop: List[List[str]]) -> List[List[str]]:
    return sorted(pop, key=_fitness, reverse=True)[:12]

def _crossover(p1: List[str], p2: List[str]) -> List[str]:
    mid1, mid2 = len(p1)//2, len(p2)//2
    return list(dict.fromkeys(p1[:mid1] + p2[mid2:]))

def _mutate(ind: List[str]) -> List[str]:
    if not ind: return ind
    if random.random() < 0.3:
        pool = [n for n in offered.keys() if n not in taken_courses and n not in ind]
        if pool: ind[random.randrange(len(ind))] = random.choice(pool)
    return ind

def genetic_algorithm() -> tuple[List[str], Optional[dict]]:
    pop = _initial_population()
    if not pop: return [], None
    for _ in range(GENERATIONS):
        elite = _selection(pop)
        kids: List[List[str]] = []
        for i in range(len(elite)):
            for j in range(i+1, len(elite)):
                kids.append(_mutate(_crossover(elite[i], elite[j])))
        pop = elite + kids
    best = max(pop, key=_fitness) if pop else []
    if not best: return [], None

    def total_hrs(lst: List[str]) -> int:
        return sum(int((offered.get(n, {}) or {}).get("hours") or plan.get(n, {}).get("hours") or 0) for n in lst)

    while total_hrs(best) > max_hours and best:
        best.pop()

    chosen = assign_non_conflicting_sections(best, offered) if best else None
    return best, chosen

def greedy_fallback(offered_: dict, taken_names: List[str], max_hours_: int) -> Tuple[List[str], int]:
    picked, sumh, used_intervals = [], 0, []
    for n, meta in offered_.items():
        if n in taken_names: continue
        hrs = int(meta.get("hours") or plan.get(n, {}).get("hours", 0))
        if hrs <= 0 or sumh + hrs > max_hours_: continue

        sec_picked = None
        for sec in meta.get("sections", []):
            ivals = section_to_intervals(sec)
            if not ivals: continue
            ok = True
            for i in ivals:
                for u in used_intervals:
                    if intervals_overlap(i, u):
                        ok = False; break
                if not ok: break
            if ok:
                sec_picked = sec; break
        if not sec_picked: continue

        picked.append(n)
        used_intervals.extend(section_to_intervals(sec_picked))
        sumh += hrs
        if sumh >= max_hours_: break
    return picked, sumh

def simple_recommendation(taken_names: List[str], max_hours_: int) -> List[str]:
    pool = [n for n in plan if n not in taken_names]
    picked, s = [], 0
    for n in pool:
        h = int(plan[n].get("hours", 3))
        if s + h <= max_hours_:
            picked.append(n); s += h
        if s >= max_hours_: break
    return picked
