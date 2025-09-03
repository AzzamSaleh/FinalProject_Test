# -*- coding: utf-8 -*-
from __future__ import annotations
import os, threading, re, difflib, json, time
from typing import Dict, List, Tuple
from flask import Flask, jsonify, request, send_from_directory
import engine

COURSE_BULLETIN_URL = "http://appserver.fet.edu.jo:7778/courses/index.jsp"

_here = os.path.dirname(__file__)
_front_candidates = [
    os.path.join(_here, "frontend"),
    os.path.abspath(os.path.join(_here, "..", "frontend")),
]
FRONTEND_DIR = next((p for p in _front_candidates if os.path.exists(os.path.join(p, "index.html"))),
                    _front_candidates[0])

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/")

@app.get("/healthz")
def healthz():
    return "ok", 200

# -------- Selenium scraper (hardened) --------
from selenium import webdriver
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

def _find_chrome_and_driver():
    """
    Try multiple common locations so it works on Railway/Render/Fly and local.
    Returns (chrome_path or None, driver_path or None).
    """
    chrome_candidates = [
        os.environ.get("GOOGLE_CHROME_BIN"),
        os.environ.get("CHROME_BIN"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    driver_candidates = [
        os.environ.get("CHROMEDRIVER_PATH"),
        "/usr/bin/chromedriver",
        "/usr/local/bin/chromedriver",
    ]
    chrome = next((p for p in chrome_candidates if p and os.path.exists(p)), None)
    driver = next((p for p in driver_candidates if p and os.path.exists(p)), None)
    return chrome, driver

def _chrome_options():
    opts = Options()
    if os.environ.get("HEADLESS", "1") == "1":
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--remote-debugging-port=9222")
    chrome_bin, _ = _find_chrome_and_driver()
    if chrome_bin:
        opts.binary_location = chrome_bin
    return opts

def _make_driver():
    chrome_bin, driver_path = _find_chrome_and_driver()
    opts = _chrome_options()
    if driver_path:
        service = Service(executable_path=driver_path)
        return webdriver.Chrome(service=service, options=opts), {"chrome": chrome_bin, "driver": driver_path}
    # fallback: let Selenium find it on PATH
    return webdriver.Chrome(options=opts), {"chrome": chrome_bin, "driver": None}

def scrape_offered_courses(departments: List[str] | None = None, debug: bool = False) -> Tuple[Dict[str, dict], dict]:
    """
    Returns (offered, diagnostics)
    offered = { CODE: { name, hours, sections:[{dept,instructor,state,times[],time}], ... } }
    diagnostics contains details about driver init and page checks.
    """
    di = {"phase": "init", "errors": [], "chrome_info": {}}

    if departments is None:
        departments = ["الهندسة الكهربائية", "العلوم الاساسية العلمية", "العلوم الاساسية الانسانية"]

    try:
        driver, info = _make_driver()
        di["chrome_info"] = info
    except Exception as e:
        di["errors"].append(f"driver_init: {e}")
        return {}, di

    wait = WebDriverWait(driver, 25)
    offered = {}

    try:
        di["phase"] = "open"
        driver.get(COURSE_BULLETIN_URL)
        wait.until(EC.presence_of_element_located((By.ID, "department")))
        dept_select = Select(driver.find_element(By.ID, "department"))
        search_btn  = driver.find_element(By.XPATH, "//input[@type='button' and contains(@onclick,'doSearch')]")

        # pick department options
        options = [opt for opt in dept_select.options if any(d in opt.text for d in departments)]
        if not options:
            options = dept_select.options
            di["note"] = "No filtered departments found; scanning all."

        def add_section(code, name, hours, dept_num, raw_time, instructor, state):
            times = [t.strip() for t in (raw_time or "").splitlines() if t.strip()]
            sec = {
                "dept": dept_num,
                "instructor": (instructor or "").strip(),
                "state": (state or "").strip(),
                "times": times,
                "time": " | ".join(times),
            }
            if code not in offered:
                offered[code] = {"name": (name or "").strip(), "hours": int(hours or 0), "sections": [sec]}
            else:
                offered[code]["sections"].append(sec)

        di["phase"] = "scrape"
        total_rows = 0
        for opt in options:
            dept_select.select_by_visible_text(opt.text)
            search_btn.click()
            wait.until(EC.presence_of_element_located((By.XPATH, "//table[@border='1']//tr")))

            while True:
                rows = driver.find_elements(By.XPATH, "//table[@border='1']//tr")
                if not rows:
                    di["errors"].append("table_not_found_on_page")
                    break
                if len(rows) <= 1 and debug:
                    di["errors"].append("no_data_rows_this_page")

                for row in rows[1:]:
                    tds = row.find_elements(By.TAG_NAME, "td")
                    if len(tds) < 8:
                        continue
                    code = (tds[0].text or "").translate(AR_DIGITS).strip().upper()
                    name = tds[1].text
                    hrs  = int((tds[2].text or "0").translate(AR_DIGITS) or "0")
                    dept = int((tds[3].text or "0").translate(AR_DIGITS) or "0")
                    time_txt = tds[4].text
                    inst = tds[5].text
                    st   = tds[7].text
                    if "ملغ" in (st or ""):
                        continue
                    add_section(code, name, hrs, dept, time_txt, inst, st)
                    total_rows += 1

                # pagination
                try:
                    next_btn = driver.find_element(By.LINK_TEXT, "التالي")
                except Exception:
                    break
                cls = (next_btn.get_attribute("class") or "").lower()
                if "disabled" in cls:
                    break
                anchor = rows[0]
                next_btn.click()
                WebDriverWait(driver, 10).until(EC.staleness_of(anchor))

        di["rows"] = total_rows
        di["codes"] = len(offered)

    except Exception as e:
        di["errors"].append(f"scrape_error: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return offered, di

# ---- cache & helpers ----
_offered_cache: Dict[str, dict] = {}
_diag_cache: dict = {}
_cache_lock = threading.Lock()

def ensure_offered_cached(refresh: bool = False, debug: bool = False):
    global _offered_cache, _diag_cache
    with _cache_lock:
        if refresh or not _offered_cache:
            offered, di = scrape_offered_courses(debug=debug)
            _offered_cache = offered or {}
            _diag_cache = di or {}
    return _offered_cache, _diag_cache

# ---- mapping bulletin -> plan ----
def _normalize_ar(name: str) -> str:
    if not isinstance(name, str): return ""
    s = name.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩","0123456789"))
    s = s.replace("ـ","").replace("–","-").replace("—","-")
    s = "".join(ch for ch in s if not ("\u064b" <= ch <= "\u0652"))
    s = (s.replace("أ","ا").replace("إ","ا").replace("آ","ا")
           .replace("ى","ي").replace("ة","ه").replace("ؤ","و").replace("ئ","ي"))
    s = re.sub(r"[()\[\]{}،,:;|]+"," ", s)
    s = re.sub(r"\s+"," ", s)
    return s.strip()

def _map_offered_to_plan(offered_by_code: dict) -> Tuple[dict, dict]:
    plan_norm_to_name = { engine.plan[n]["norm"]: n for n in engine.plan.keys() if "norm" in engine.plan[n] }
    mapped, unmatched = {}, []
    plan_norm_list = list(plan_norm_to_name.keys())

    for code, meta in (offered_by_code or {}).items():
        nm = (meta.get("name") or "").strip()
        if not nm:
            unmatched.append({"code": code, "name": nm}); continue

        # 1) match by code if Excel has it
        if code in engine.name_by_code:
            pn = engine.name_by_code[code]
            mapped[pn] = {
                "name": pn, "code": code,
                "hours": int(meta.get("hours", 0) or 0),
                "sections": meta.get("sections", []),
                "time": meta.get("time",""),
                "instructor": meta.get("instructor",""),
                "state": meta.get("state",""),
            }
            continue

        on = _normalize_ar(nm)

        if on in plan_norm_to_name:
            pn = plan_norm_to_name[on]
            mapped[pn] = {
                "name": pn, "code": code,
                "hours": int(meta.get("hours", 0) or 0),
                "sections": meta.get("sections", []),
                "time": meta.get("time",""),
                "instructor": meta.get("instructor",""),
                "state": meta.get("state",""),
            }
            continue

        candidates = [pn for pn_norm, pn in plan_norm_to_name.items() if on in pn_norm or pn_norm in on]
        if len(candidates) == 1:
            pn = candidates[0]
            mapped[pn] = {
                "name": pn, "code": code,
                "hours": int(meta.get("hours", 0) or 0),
                "sections": meta.get("sections", []),
                "time": meta.get("time",""),
                "instructor": meta.get("instructor",""),
                "state": meta.get("state",""),
            }
            continue

        toks_on = set(on.split())
        best, best_score = None, 0
        for pn_norm, pn in plan_norm_to_name.items():
            score = len(toks_on & set(pn_norm.split()))
            if score > best_score:
                best, best_score = pn, score
        if best and best_score >= 2:
            mapped[best] = {
                "name": best, "code": code,
                "hours": int(meta.get("hours", 0) or 0),
                "sections": meta.get("sections", []),
                "time": meta.get("time",""),
                "instructor": meta.get("instructor",""),
                "state": meta.get("state",""),
            }
            continue

        close = difflib.get_close_matches(on, plan_norm_list, n=1, cutoff=0.60)
        if close:
            pn = plan_norm_to_name[close[0]]
            mapped[pn] = {
                "name": pn, "code": code,
                "hours": int(meta.get("hours", 0) or 0),
                "sections": meta.get("sections", []),
                "time": meta.get("time",""),
                "instructor": meta.get("instructor",""),
                "state": meta.get("state",""),
            }
        else:
            unmatched.append({"code": code, "name": nm})

    return mapped, {"unmatched": unmatched}

# -------- routes --------
@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.get("/api/plan")
def api_plan():
    if request.args.get("reload") == "1":
        try:
            engine.plan = engine.load_plan_from_excel(engine.EXCEL_PATH)
        except Exception as e:
            return jsonify({"ok": False, "message": f"فشل تحميل الخطة من الإكسل: {e}"}), 500
    out = [
        {"code": name, "name": name,
         "category": info.get("category", ""), "hours": int(info.get("hours", 3)),
         "prerequisites": info.get("prerequisites", [])}
        for name, info in engine.plan.items()
    ]
    return jsonify(out)

@app.get("/api/offered")
def api_offered():
    refresh = bool(request.args.get("refresh"))
    debug   = bool(request.args.get("debug"))
    raw, di = ensure_offered_cached(refresh=refresh, debug=debug)
    mapped, diag = _map_offered_to_plan(raw)
    return jsonify({
        "ok": True,
        "count_raw": len(raw),
        "count_mapped": len(mapped),
        "unmatched": diag.get("unmatched", [])[:20],
        "diagnostics": di,
        "bulletin_url": COURSE_BULLETIN_URL
    })

@app.post("/api/recommend")
def api_recommend():
    p = request.get_json(force=True) or {}
    taken_names = p.get("taken_codes", []) or []
    max_hours   = int(p.get("max_hours", 18) or 18)
    use_offered = bool(p.get("use_offered", True))
    refresh     = bool(p.get("refresh_offered", False))
    if max_hours > 18:
        max_hours = 18

    if use_offered:
        raw, _ = ensure_offered_cached(refresh=refresh)
        offered_by_plan_name, diag = _map_offered_to_plan(raw)

        # synthesize if too few mapped but raw exists
        if len(offered_by_plan_name) < 3 and len(raw) > 0:
            for code, meta in raw.items():
                if any(v.get("code")==code for v in offered_by_plan_name.values()):
                    continue
                synth_name = meta.get("name","").strip()
                if not synth_name: continue
                if synth_name not in engine.plan:
                    engine.plan[synth_name] = {
                        "name": synth_name, "code": code, "category": "major_required",
                        "hours": int(meta.get("hours", 3) or 3), "prerequisites": [],
                        "min_hours": None, "norm": engine._norm_ar(synth_name) if hasattr(engine,"_norm_ar") else synth_name,
                    }
                offered_by_plan_name[synth_name] = {
                    "name": synth_name, "code": code, "hours": int(meta.get("hours", 3) or 3),
                    "sections": meta.get("sections", []), "time": meta.get("time",""),
                    "instructor": meta.get("instructor",""), "state": meta.get("state",""),
                }
    else:
        offered_by_plan_name = {
            name: {"name": name, "code": engine.plan.get(name, {}).get("code"),
                   "hours": engine.plan.get(name, {}).get("hours", 3),
                   "sections": [], "time": "", "instructor": "", "state": ""}
            for name in engine.plan.keys()
        }

    engine.max_hours = max_hours
    engine.offered = offered_by_plan_name
    engine.taken_courses = {n: {"hours": engine.plan.get(n, {}).get("hours", 3)} for n in taken_names}

    best, chosen = engine.genetic_algorithm()

    def total_hrs(names: List[str]) -> int:
        s = 0
        for n in names:
            m = offered_by_plan_name.get(n, {}) or {}
            s += int(m.get("hours") or engine.plan.get(n, {}).get("hours", 0))
        return s

    total = total_hrs(best) if best else 0

    if (not best) or total == 0:
        best, total = engine.greedy_fallback(offered_by_plan_name, taken_names, max_hours)
        chosen = engine.assign_non_conflicting_sections(best, offered_by_plan_name) if best else None

    if (not best) and (not use_offered):
        best  = engine.simple_recommendation(taken_names, max_hours)
        chosen = None
        total = total_hrs(best)

    if not best:
        return jsonify({
            "ok": False,
            "message": "لم يتم العثور على توليفة مناسبة. لا توجد بيانات جريدة مواد متاحة للتخطيط.",
            "redirect_url": COURSE_BULLETIN_URL,
            "can_refresh": True
        })

    result = []
    for name in best:
        meta   = offered_by_plan_name.get(name, {}) or {}
        pinfo  = engine.plan.get(name, {}) or {}
        sec    = (chosen or {}).get(name) or {}
        times  = sec.get("time") or " | ".join(sec.get("times", [])) if sec else meta.get("time", "")
        instr  = sec.get("instructor", "") if sec else meta.get("instructor", "")
        result.append({
            "code": name,
            "name": name,
            "hours": int(meta.get("hours") or pinfo.get("hours", 3)),
            "time": times,
            "instructor": instr,
            "category": pinfo.get("category", ""),
        })

    # enforce hard cap
    while sum(x["hours"] for x in result) > max_hours and result:
        result.pop()

    return jsonify({"ok": True, "total_hours": sum(x["hours"] for x in result),
                    "courses": result, "conflicts": []})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
