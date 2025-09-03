# -*- coding: utf-8 -*-
from __future__ import annotations
import os, re, random, logging
from typing import Dict, List, Tuple, Optional

import pandas as pd

# -------- ملفات الخطة --------
EXCEL_PATH = os.path.join(os.path.dirname(__file__), "subjects+Notes.xlsx")

# خرائط التصنيف من نص عربي
CAT_MAP = {
    "متطلبات الجامعة الاجبارية": "university_required",
    "متطلبات الجامعة الإجباري": "university_required",
    "متطلبات الجامعة الاختيارية": "elective_requirements",
    "متطلبات الكلية الاجبارية": "college_required",
    "متطلبات التخصص الاجبارية": "major_required",
    "متطلبات التخصص الاختيارية": "major_optional",
    "مواد استدراكية": "Remedial materials",
}

# حدود الساعات حسب الفئات (سقف تجميعي ضمن التخصص)
CATEGORY_LIMITS = {
    "university_required": 18,
    "elective_requirements": 9,
    "college_required": 32,
    "major_required": 93,
    "major_optional": 9,
    "Remedial materials": 9,
}

# حد أدنى للساعات لبعض الأكواد (من الجامعة)
MIN_HOURS_BY_CODE: Dict[str, int] = {
    "ELE5467": 115, "ELE5455": 120, "ELE5559": 90,  "ELE5556": 90,
    "ELE5557": 90,  "ELE5558": 90,  "ELE5560": 90,  "ELE5561": 90,
    "ELE5562": 90,  "ELE5565": 90,  "ELE5555": 90,  "ELE5666": 90,
    "ELE5512": 90,  "ELE5527": 90,  "ELE5552": 90,  "ELE5553": 90,
}

# -------- سياق يُضبط من app.py --------
max_hours: int                 = 18
# offered: مفاتيحه = اسم المادة كما في الخطة (Arabic name)
# وقيمه = {code, hours, sections: [{dept, instructor, state, times[], time}], ...}
offered: Dict[str, dict]       = {}
# taken_courses: {اسم_المادة: {hours:int}}
taken_courses: Dict[str, dict] = {}

# -------- تحميل الخطة من Excel --------
def guess_category(text: str) -> str:
    if not isinstance(text, str): return ""
    for k, v in CAT_MAP.items():
        if k in text:
            return v
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

def load_plan_from_excel(path: str) -> Dict[str, dict]:
    df = pd.read_excel(path, sheet_name=0)
    df = df[df["اسم المادة"].notna()].copy()
    df["اسم المادة"] = df["اسم المادة"].astype(str).str.strip()

    names = df["اسم المادة"].tolist()
    plan: Dict[str, dict] = {}

    for _, row in df.iterrows():
        name = str(row.get("اسم المادة", "")).strip()
        if not name:
            continue

        hrs = row.get("عدد الساعات")
        try:
            hours = int(hrs) if not pd.isna(hrs) else 3
        except Exception:
            hours = 3

        category = guess_category(row.get("تصنيف المادة", ""))

        # استخراج المتطلبات كأسماء مواد تظهر في النص
        prereqs: List[str] = []
        pre_txt = row.get("متطلب لاختيار الماده", "")
        if isinstance(pre_txt, str) and pre_txt.strip():
            for other in names:
                other = str(other).strip()
                if other and other != name and other in pre_txt:
                    prereqs.append(other)

        # ساعات منجزة مطلوبة - من المتطلبات/الملاحظات
        min_hours = _parse_min_hours(str(pre_txt)) or _parse_min_hours(str(row.get("ملاحظات", "")))

        plan[name] = {
            "name": name,
            "category": category,
            "hours": hours,
            "prerequisites": sorted(set(prereqs)),
            "min_hours": int(min_hours) if min_hours else None,
        }
    return plan

logging.basicConfig(level=logging.INFO)
try:
    plan: Dict[str, dict] = load_plan_from_excel(EXCEL_PATH)
    logging.info(f"[engine] Loaded {len(plan)} subjects from {EXCEL_PATH}")
except Exception as e:
    logging.exception("[engine] Excel load failed; using minimal fallback")
    plan = {
        "لغة انجليزية تطبيقية ١": {"name":"لغة انجليزية تطبيقية ١","category":"university_required","hours":3,"prerequisites":[],"min_hours":None},
        "رياضيات 1": {"name":"رياضيات 1","category":"college_required","hours":3,"prerequisites":[],"min_hours":None},
        "فيزياء 1": {"name":"فيزياء 1","category":"college_required","hours":3,"prerequisites":[],"min_hours":None},
        "برمجة 1": {"name":"برمجة 1","category":"major_required","hours":3,"prerequisites":[],"min_hours":None},
        "برمجة 2": {"name":"برمجة 2","category":"major_required","hours":3,"prerequisites":["برمجة 1"],"min_hours":None},
    }

# -------- أدوات الوقت وفحص التعارض --------
AR_DIGITS   = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
DAY_MAP     = {"ح":0, "ن":1, "ث":2, "ر":3, "خ":4, "ج":5, "س":6}
DAY_PATTERN = re.compile(r"[حنثرخجس]")
TIME_PATTERN= re.compile(r"(\d{2}):(\d{2})")

def to_24h_minutes(hh: str, mm: str) -> int:
    h = int(hh); m = int(mm)
    # جداول الجامعة تُكتب 01..07 كمسائي (13..19)
    if 1 <= h <= 7:
        h += 12
    return h * 60 + m

def _split_slots(v):
    if isinstance(v, list): slots = v
    else: slots = re.split(r"[|,\n،]+", str(v or ""))
    return [s.strip() for s in slots if s and s.strip()]

def slot_to_intervals(slot_str: str):
    """
    مثال: 'ث خ 08:30 09:30' -> [(day, start, end), (day, start, end)]
    """
    s = str(slot_str or "").translate(AR_DIGITS)
    days  = DAY_PATTERN.findall(s)
    times = TIME_PATTERN.findall(s)
    if not days or len(times) < 2:
        return []
    start = to_24h_minutes(*times[0])
    end   = to_24h_minutes(*times[1])
    if end <= start:
        end += 12*60  # تمديد ضمن نفس اليوم
    return [(DAY_MAP[d], start, end) for d in days]

def section_to_intervals(section: dict):
    slots = section.get("times") or _split_slots(section.get("time"))
    ivals = []
    for s in slots:
        ivals.extend(slot_to_intervals(s))
    return ivals

def intervals_overlap(a, b) -> bool:
    # نفس اليوم وتداخل حقيقي (نصف مفتوح)
    return a[0] == b[0] and a[1] < b[2] and b[1] < a[2]

def assign_non_conflicting_sections(course_names: List[str], offered_map_by_planname: dict):
    """
    يحاول اختيار شعبة واحدة لكل مساق بدون تعارض.
    يعيد {اسم_المادة: section} أو None إذا تعذّر.
    """
    used_intervals = []
    chosen = {}
    for n in course_names:
        meta = (offered_map_by_planname.get(n) or {})
        picked = None
        for sec in meta.get("sections", []):
            ints = section_to_intervals(sec)
            if not ints:
                continue
            ok = True
            for i in ints:
                for u in used_intervals:
                    if intervals_overlap(i, u):
                        ok = False; break
                if not ok: break
            if ok:
                picked = sec
                used_intervals.extend(ints)
                break
        if picked is None:
            return None
        chosen[n] = picked
    return chosen

# -------- حسابات مشتركة --------
def _total_completed_hours() -> int:
    return sum(int(v.get("hours", 0)) for v in taken_courses.values())

def _effective_min_hours_for(name: str) -> Optional[int]:
    """
    الحد الأدنى المفعّل:
    - min_hours من الخطة (لو موجود)
    - وبوجود كود: MIN_HOURS_BY_CODE[code]
    نأخذ الأكبر.
    """
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
        if not cat or cat not in CATEGORY_LIMITS:
            continue
        hrs = int((offered.get(n, {}) or {}).get("hours") or info.get("hours") or 0)
        res[cat] += hrs
    return res

def _has_time_conflict(names: List[str]) -> bool:
    chosen = assign_non_conflicting_sections(names, offered)
    return chosen is None

# -------- GA --------
POP_SIZE    = 120
GENERATIONS = 120

def _fitness(ind: List[str]) -> float:
    if _has_time_conflict(ind):
        return -1e6

    total_completed = _total_completed_hours()
    score = 0.0
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
        score += 10

    if total > max_hours:
        return -1e6

    cat_hours = _compute_category_hours(ind)
    for cat, limit in CATEGORY_LIMITS.items():
        if cat_hours[cat] > limit:
            return -1e6

    score += total
    if total >= max_hours - 2:
        score += 20
    return score

def _initial_population() -> List[List[str]]:
    pool = [n for n in offered.keys() if n in plan and n not in taken_courses]
    if not pool:
        return [[]]
    pop: List[List[str]] = []
    for _ in range(POP_SIZE):
        max_courses = max(1, max_hours // 2)
        size = random.randint(1, min(len(pool), max_courses))
        pop.append(random.sample(pool, size))
    return pop

def _selection(pop: List[List[str]]) -> List[List[str]]:
    return sorted(pop, key=_fitness, reverse=True)[:12]

def _crossover(p1: List[str], p2: List[str]) -> List[str]:
    mid1, mid2 = len(p1)//2, len(p2)//2
    return list(dict.fromkeys(p1[:mid1] + p2[mid2:]))

def _mutate(ind: List[str]) -> List[str]:
    if not ind:
        return ind
    if random.random() < 0.3:
        pool = [n for n in offered.keys() if n not in taken_courses and n not in ind]
        if pool:
            ind[random.randrange(len(ind))] = random.choice(pool)
    return ind

def genetic_algorithm() -> tuple[List[str], Optional[dict]]:
    pop = _initial_population()
    if not pop:
        return [], None
    for _ in range(GENERATIONS):
        elite = _selection(pop)
        kids: List[List[str]] = []
        for i in range(len(elite)):
            for j in range(i+1, len(elite)):
                c = _mutate(_crossover(elite[i], elite[j]))
                kids.append(c)
        pop = elite + kids
        if not pop:
            break
    best = max(pop, key=_fitness) if pop else []
    chosen = assign_non_conflicting_sections(best, offered) if best else None
    return best, chosen

# -------- Greedy + Plan-only --------
def greedy_fallback(offered_: dict, taken_names: List[str], max_hours_: int) -> Tuple[List[str], int]:
    caps = CATEGORY_LIMITS.copy()
    used = {k:0 for k in caps}
    taken_set = set(taken_names)

    def priority(name: str):
        info = plan.get(name, {})
        cat  = info.get("category", "")
        cat_rank = {"major_required":0, "college_required":1, "university_required":2,
                    "major_optional":3, "elective_requirements":4, "Remedial materials":5}.get(cat, 9)
        hrs = int((offered_.get(name, {}) or {}).get("hours") or info.get("hours") or 0)
        return (cat_rank, -hrs, name)

    cand = [n for n in offered_.keys() if n in plan and n not in taken_set]
    cand.sort(key=priority)

    picked, sumh, used_intervals = [], 0, []
    for n in cand:
        info = plan.get(n, {})
        meta = offered_.get(n, {})
        hrs  = int(meta.get("hours") or info.get("hours") or 0)
        if hrs <= 0 or sumh + hrs > max_hours_:
            continue
        if any(p not in taken_set for p in info.get("prerequisites", [])):
            continue
        min_req = _effective_min_hours_for(n)
        if min_req and _total_completed_hours() < int(min_req):
            continue
        cat = info.get("category", "")
        if cat in caps and used[cat] + hrs > caps[cat]:
            continue

        # اختر شعبة لا تتعارض
        sec_picked = None
        for sec in meta.get("sections", []):
            ivals = section_to_intervals(sec)
            if not ivals:
                continue
            ok = True
            for i in ivals:
                for u in used_intervals:
                    if intervals_overlap(i, u):
                        ok = False; break
                if not ok: break
            if ok:
                sec_picked = sec
                break
        if not sec_picked:
            continue

        picked.append(n)
        used[cat] = used.get(cat, 0) + hrs
        used_intervals.extend(section_to_intervals(sec_picked))
        sumh += hrs
        if sumh >= max_hours_:
            break
    return picked, sumh

def simple_recommendation(taken_names: List[str], max_hours_: int) -> List[str]:
    """وضع الأسماء فقط: بدون أوقات/مدرّسين."""
    pool = [n for n in plan if n not in taken_names]
    pool.sort(key=lambda n: ({"major_required":0,"college_required":1,"university_required":2,
                              "major_optional":3,"elective_requirements":4,"Remedial materials":5}
                             .get(plan[n].get("category",""),9), -int(plan[n].get("hours",3))))
    picked, s = [], 0
    for n in pool:
        h = int(plan[n].get("hours",3))
        if s + h <= max_hours_:
            picked.append(n); s += h
        if s >= max_hours_:
            break
    return picked
