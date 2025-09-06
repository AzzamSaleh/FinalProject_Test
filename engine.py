from __future__ import annotations
import os, re, json, random, logging
from typing import Dict, List, Optional

# -------------------- paths / globals --------------------
BASE_DIR = os.path.dirname(__file__)
PLAN_JSON_PATH = os.path.join(BASE_DIR, "full_plan_en_complete.json")

# will be mutated by app.py
max_hours: int = 18
plan: Dict[str, dict] = {}               # {CODE: {name,hours,prerequisites,category,min_hours?}}
offered: Dict[str, dict] = {}            # {CODE: {name,hours,sections:[{times|time,dept,instructor,state}]}}
taken_courses: Dict[str, dict] = {}      # {CODE: {hours}}

# -------------------- constants --------------------
minimum_hours_required = {
    "ELE5467": 115, "ELE5455": 120, "ELE5559": 90, "ELE5556": 90,
    "ELE5557": 90,  "ELE5558": 90,  "ELE5560": 90, "ELE5561": 90,
    "ELE5562": 90,  "ELE5565": 90,  "ELE5555": 90, "ELE5666": 90,
    "ELE5512": 90,  "ELE5527": 90,  "ELE5552": 90, "ELE5553": 90,
}

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
DAY_MAP = {"ح": 0, "ن": 1, "ث": 2, "ر": 3, "خ": 4, "ج": 5, "س": 6}
DAY_PATTERN  = re.compile(r"[حنثرخجس]")
TIME_PATTERN = re.compile(r"(\d{2}):(\d{2})")

category_limits = {
    "university_required": 18,
    "elective_requirements": 6,
    "college_required": 32,
    "major_required": 93,
    "major_optional": 9,
    "Remedial materials": 9
}

# -------------------- utils --------------------
def to_24h_minutes(hh: str, mm: str) -> int:
    h = int(hh); m = int(mm)
    if 1 <= h <= 7:
        h += 12
    return h * 60 + m

def slot_to_intervals(slot_str: str):
    s = str(slot_str or "").translate(AR_DIGITS)
    days = DAY_PATTERN.findall(s)
    times = TIME_PATTERN.findall(s)
    if not days or len(times) < 2:
        return []
    start = to_24h_minutes(*times[0])
    end   = to_24h_minutes(*times[1])
    if end <= start:
        end += 12 * 60
    return [(DAY_MAP[d], start, end) for d in days]

def _split_slots(v):
    if isinstance(v, list):
        slots = v
    else:
        slots = re.split(r"[|,\n،]+", str(v or ""))
    return [s.strip() for s in slots if s and s.strip()]

def section_to_intervals(section: dict):
    slots = section.get("times") or _split_slots(section.get("time"))
    intervals = []
    for s in slots:
        intervals.extend(slot_to_intervals(s))
    return intervals

def intervals_overlap(a, b) -> bool:
    return a[0] == b[0] and a[1] < b[2] and b[1] < a[2]

def norm_code(x):
    s = str(x or "").translate(AR_DIGITS)
    s = s.replace("–", "-").replace("—", "-").replace("−", "-")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^A-Za-z0-9-]", "", s)
    return s.upper()

def norm_ar(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", s)
    s = (s.replace("أ","ا").replace("إ","ا").replace("آ","ا")
           .replace("ى","ي").replace("ة","ه").replace("ؤ","و").replace("ئ","ي"))
    s = re.sub(r"\s+", " ", s).strip()
    return s

# -------------------- plan I/O --------------------
def load_plan_from_json(path: str = PLAN_JSON_PATH) -> Dict[str, dict]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    plan_by_code = {}
    for code, info in raw.items():
        c = norm_code(code)
        plan_by_code[c] = {
            "name": info.get("name", c),
            "hours": int(info.get("hours", 3) or 3),
            "prerequisites": [norm_code(x) for x in info.get("prerequisites", [])],
            "category": info.get("category", ""),
            "min_hours": info.get("min_hours", None),
        }
    return plan_by_code

# -------------------- scraper --------------------
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

def _chrome_opts():
    opts = Options()
    if os.environ.get("HEADLESS", "1") == "1":
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    return opts

def scrape_offered_courses(departments=None, headless=True) -> Dict[str, dict]:
    if departments is None:
        departments = ["الهندسة الكهربائية", "العلوم الاساسية العلمية", "العلوم الاساسية الانسانية"]
    chrome_opts = _chrome_opts()
    if headless:
        chrome_opts.add_argument("--headless=new")

    driver = webdriver.Chrome(options=chrome_opts)
    wait = WebDriverWait(driver, 25)
    driver.get("http://appserver.fet.edu.jo:7778/courses/index.jsp")

    wait.until(EC.presence_of_element_located((By.ID, "department")))
    dept_select = Select(driver.find_element(By.ID, "department"))
    target_norm = [norm_ar(d) for d in departments]
    wanted = [opt for opt in dept_select.options if any(t in norm_ar(opt.text) for t in target_norm)]
    if not wanted:
        driver.quit()
        return {}

    search_btn = driver.find_element(By.XPATH, "//input[@type='button' and contains(@onclick,'doSearch')]")

    out = {}
    def add_section(code: str, course_name: str, hours: int, dept_num: int,
                    raw_time: str, instructor: str, state: str):
        times = [t.strip() for t in (raw_time or "").splitlines() if t.strip()]
        section = {
            "dept": dept_num,
            "instructor": (instructor or "").strip(),
            "state": (state or "").strip(),
            "times": times,
            "time": " | ".join(times),
        }
        if code not in out:
            out[code] = {
                "name": (course_name or "").strip(),
                "hours": int((hours or 0)),
                "sections": [section],
            }
        else:
            out[code]["sections"].append(section)

    for opt in wanted:
        dept_select.select_by_visible_text(opt.text)
        search_btn.click()
        wait.until(EC.presence_of_element_located((By.XPATH, "//table[@border='1']//tr")))
        while True:
            rows = driver.find_elements(By.XPATH, "//table[@border='1']//tr")
            for row in rows[1:]:
                cells = row.find_elements(By.TAG_NAME, "td")
                if len(cells) >= 8:
                    code = norm_code(cells[0].text)
                    name = cells[1].text
                    hours = int((cells[2].text or "0").translate(AR_DIGITS) or "0")
                    dept_num = int((cells[3].text or "0").translate(AR_DIGITS) or "0")
                    raw_time = cells[4].text
                    instructor = cells[5].text
                    state = cells[7].text
                    if "ملغ" in (state or ""):
                        continue
                    add_section(code, name, hours, dept_num, raw_time, instructor, state)

            try:
                next_button = driver.find_element(By.LINK_TEXT, "التالي")
            except Exception:
                break
            cls = (next_button.get_attribute("class") or "").lower()
            if "disabled" in cls:
                break
            anchor = rows[0]
            next_button.click()
            WebDriverWait(driver, 10).until(EC.staleness_of(anchor))

    driver.quit()
    return out

# -------------------- eligibility / filtering --------------------
def get_total_completed_hours(taken: dict) -> int:
    return sum(int(c.get("hours", 0)) for c in taken.values())

def get_min_hours_required(code: str, info_from_plan: dict):
    mh = info_from_plan.get("min_hours")
    if mh is None:
        mh = minimum_hours_required.get(code)
    if isinstance(mh, str):
        try:
            mh = int(re.sub(r"[^\d]", "", mh) or 0)
        except:
            mh = None
    return mh

def filter_offered_by_plan_and_taken(offered_all: dict, plan_: dict, taken: dict):
    total_completed = get_total_completed_hours(taken)
    eligible_offered, rejected = {}, {}

    # تطبيع الأكواد المُنجزة لمطابقة سريعة
    taken_norm = set(norm_code(t) for t in taken.keys())

    for code, data in offered_all.items():
        c = norm_code(code)

        # 1) already taken
        if c in taken_norm:
            rejected[c] = "already_taken"
            continue

        # 2) must exist in plan JSON
        info = plan_.get(c)
        if info is None:
            rejected[c] = "not_in_plan"
            continue

        # 3) prerequisites (CODES) + إظهار الأسماء في السبب
        prereqs = [norm_code(p) for p in info.get("prerequisites", [])]
        missing = [p for p in prereqs if p not in taken_norm]
        if missing:
            missing_names = [ (plan_.get(p) or {}).get("name", p) for p in missing ]
            rejected[c] = f"لا بد من إنهاء: {', '.join(missing_names)}"
            continue

        # 4) min-hours
        mh = get_min_hours_required(c, info)
        if mh and total_completed < mh:
            rejected[c] = f"min_hours:{mh}, have:{total_completed}"
            continue

        # 5) sections with valid times and not canceled
        valid_sections = []
        for sec in data.get("sections", []):
            state = str(sec.get("state", "")).strip()
            times = _split_slots(sec.get("times") or sec.get("time"))
            if not times:
                continue
            if "ملغ" in state:
                continue
            valid_sections.append({**sec, "times": times, "time": " | ".join(times)})

        if not valid_sections:
            rejected[c] = "no_valid_sections"
            continue

        eligible_offered[c] = {
            "name": data.get("name", (plan_.get(c) or {}).get("name", c)),
            "hours": int(data.get("hours", (plan_.get(c) or {}).get("hours", 3))),
            "sections": valid_sections,
        }

    return eligible_offered, rejected

# -------------------- category helpers --------------------
def taken_category_hours_map(taken_: dict, plan_: dict):
    acc = {cat: 0 for cat in category_limits}
    for code, c in taken_.items():
        cat = plan_.get(code, {}).get("category")
        if cat in acc:
            hours = int(c.get("hours", plan_.get(code, {}).get("hours", 0)) or 0)
            acc[cat] += hours
    return acc

def compute_taken_cat_hours():
    return taken_category_hours_map(taken_courses, plan)

# -------------------- GA --------------------
def assign_non_conflicting_sections(individual, offered_map):
    used_intervals = []
    chosen = {}
    for code in individual:
        picked = None
        for sec in offered_map[code].get("sections", []):
            ints = section_to_intervals(sec)
            if not ints:
                continue
            ok = True
            for i in ints:
                for u in used_intervals:
                    if intervals_overlap(i, u):
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                picked = sec
                used_intervals.extend(ints)
                break
        if picked is None:
            return None
        chosen[code] = picked
    return chosen

def has_conflict(selected_courses, offered_map):
    return assign_non_conflicting_sections(selected_courses, offered_map) is None

def fitness(individual, TAKEN_CAT_HOURS):
    if has_conflict(individual, offered):
        return -1000

    total_hours_sum = 0
    total_completed_hours = sum(course.get("hours", 0) for course in taken_courses.values())

    for code in individual:
        info = plan.get(code, {})
        prereqs = info.get("prerequisites", [])
        if any(p not in taken_courses for p in prereqs):
            return -1000
        mh = get_min_hours_required(code, info)
        if mh and total_completed_hours < mh:
            return -1000

        total_hours_sum += offered[code]["hours"]

    if total_hours_sum > max_hours:
        return -1000

    new_cat = {cat: 0 for cat in category_limits}
    for code in individual:
        cat = plan.get(code, {}).get("category")
        if cat in new_cat:
            new_cat[cat] += offered[code]["hours"]

    for cat, limit in category_limits.items():
        if TAKEN_CAT_HOURS.get(cat, 0) + new_cat.get(cat, 0) > limit:
            return -1000

    score = total_hours_sum
    if total_hours_sum >= max_hours - 2:
        score += 20
    return score

def eligible_course_list():
    return list(offered.keys())

def create_initial_population(population_size, TAKEN_CAT_HOURS):
    course_list = eligible_course_list()
    population = []
    for _ in range(population_size):
        random.shuffle(course_list)
        total = 0
        individual = []
        for code in course_list:
            h = offered[code]["hours"]
            if code not in individual and total + h <= max_hours:
                if offered[code].get("sections"):
                    individual.append(code)
                    total += h
            if total >= max_hours:
                break
        if not individual and course_list:
            individual = [random.choice(course_list)]
        population.append(individual)
    return population

def selection(population, TAKEN_CAT_HOURS):
    return sorted(population, key=lambda ind: fitness(ind, TAKEN_CAT_HOURS), reverse=True)[:10]

def crossover(parent1, parent2):
    return list(set(parent1[:len(parent1)//2] + parent2[len(parent2)//2:]))

def mutate(individual):
    if not individual:
        return individual
    if random.random() < 0.3:
        available = [c for c in eligible_course_list() if c not in individual]
        if available:
            individual[random.randint(0, len(individual)-1)] = random.choice(available)
    return individual

def genetic_algorithm(population_size=100, generations=150):
    TAKEN_CAT_HOURS = compute_taken_cat_hours()
    population = create_initial_population(population_size, TAKEN_CAT_HOURS)
    for _ in range(generations):
        selected = selection(population, TAKEN_CAT_HOURS)
        new_generation = selected[:]
        for i in range(len(selected)):
            for j in range(i + 1, len(selected)):
                child = crossover(selected[i], selected[j])
                child = mutate(child)
                new_generation.append(child)
        population = new_generation
    best = max(population, key=lambda ind: fitness(ind, TAKEN_CAT_HOURS))
    return best

# -------------------- SIMPLE (no offered) --------------------
def simple_recommendation(taken_codes: List[str]) -> List[str]:
    total_completed_hours = sum(taken_courses.get(c, {}).get("hours", plan.get(c, {}).get("hours", 0))
                                for c in taken_codes)

    taken_cat = compute_taken_cat_hours()
    picked, sumh = [], 0

    priority = {"major_required": 0, "college_required": 1, "university_required": 2,
                "major_optional": 3, "elective_requirements": 4, "Remedial materials": 5, "": 9}

    for code, info in sorted(plan.items(), key=lambda kv: priority.get(kv[1].get("category",""), 9)):
        if code in taken_codes:
            continue

        # تحقق المتطلبات
        prereqs = info.get("prerequisites", [])
        if any(p not in taken_codes for p in prereqs):
            continue

        # تحقق min_hours
        mh = get_min_hours_required(code, info)
        if mh and total_completed_hours < mh:
            continue

        h = int(info.get("hours", 3) or 0)
        if h <= 0 or sumh + h > max_hours:
            continue

        # تحقق حدود التصنيف
        cat = info.get("category", "")
        if cat in category_limits:
            if taken_cat.get(cat, 0) + h > category_limits[cat]:
                continue

        picked.append(code)
        sumh += h
        if cat in category_limits:
            taken_cat[cat] = taken_cat.get(cat, 0) + h
        if sumh >= max_hours:
            break

    return picked

# -------------------- boot plan once --------------------
logging.basicConfig(level=logging.INFO)
try:
    plan = load_plan_from_json(PLAN_JSON_PATH)
    logging.info(f"[engine] loaded plan (codes): {len(plan)}")
except Exception:
    logging.exception("[engine] FAILED to load full_plan_en_complete.json")
    plan = {}
