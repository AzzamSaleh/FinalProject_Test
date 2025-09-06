from __future__ import annotations
import os, threading, re
from typing import Dict
from flask import Flask, jsonify, request, send_from_directory

import engine

COURSE_BULLETIN_URL = "http://appserver.fet.edu.jo:7778/courses/index.jsp"

# -------------- static/frontend --------------
_here = os.path.dirname(__file__)
_front_candidates = [
    os.path.join(_here, "frontend"),
    os.path.abspath(os.path.join(_here, "..", "frontend")),
]
FRONTEND_DIR = next((p for p in _front_candidates if os.path.exists(os.path.join(p, "index.html"))),
                    _front_candidates[0])

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/")

@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.get("/healthz")
def healthz():
    return "ok", 200

# -------------- cache for offered --------------
_offered_cache: Dict[str, dict] = {}
_cache_lock = threading.Lock()

def ensure_offered_cached(refresh: bool = False):
    global _offered_cache
    with _cache_lock:
        if refresh or not _offered_cache:
            _offered_cache = engine.scrape_offered_courses(headless=True) or {}
    return _offered_cache

# --- NEW: استبدال أي كود داخل نص السبب باسم المادة من الخطة ---
def _prettify_reason_text(reason: str) -> str:
    """يستبدل أي كود مقرر مذكور في نص السبب باسم المادة من الخطة (من JSON)."""
    if not isinstance(reason, str) or not reason:
        return reason
    # جهّز قائمة الأكواد المتاحة في الخطة
    codes = sorted(engine.plan.keys(), key=len, reverse=True)
    if not codes:
        return reason
    pattern = re.compile(r"\b(" + "|".join(re.escape(c) for c in codes) + r")\b")

    def _rep(m):
        code = m.group(0)
        info = engine.plan.get(code) or {}
        return info.get("name", code)

    return pattern.sub(_rep, reason)

def _humanize_rejected(rejected_dict: dict) -> list[dict]:
    """يرجع قائمة مرتبة لعرضها في الواجهة، مع تحويل الأكواد داخل نص السبب إلى أسماء."""
    out = []
    for code, reason in rejected_dict.items():
        name = engine.plan.get(code, {}).get("name", code)
        pretty_reason = _prettify_reason_text(reason)
        out.append({"code": code, "name": name, "reason": pretty_reason})
    return out

# -------------- API: plan --------------
@app.get("/api/plan")
def api_plan():
    out = [
        {
            "code": code,
            "name": info.get("name", code),
            "hours": int(info.get("hours", 3)),
            "category": info.get("category", ""),
            "prerequisites": info.get("prerequisites", []),  # CODES
            "min_hours": info.get("min_hours", None),
        }
        for code, info in engine.plan.items()
    ]
    return jsonify(out)

# -------------- API: offered --------------
@app.get("/api/offered")
def api_offered():
    refresh = bool(request.args.get("refresh", ""))
    offered_all = ensure_offered_cached(refresh=refresh)

    eligible, rejected = engine.filter_offered_by_plan_and_taken(
        offered_all, engine.plan, engine.taken_courses
    )

    return jsonify({
        "ok": True,
        "count_raw": len(offered_all),
        "count_eligible": len(eligible),
        "rejected": list(rejected.items())[:40],
        "rejected_human": _humanize_rejected(rejected),  # واجهة تستخدم هذا
        "bulletin_url": COURSE_BULLETIN_URL,
        "offered": eligible,
    })

# -------------- API: recommend --------------
@app.post("/api/recommend")
def api_recommend():
    """
    Expected JSON from frontend:
    {
      "taken_codes": ["30202101","AEL101", ...],   // CODES
      "max_hours": 15,
      "use_offered": true | false,
      "refresh_offered": false
    }
    """
    p = request.get_json(force=True) or {}

    taken_codes = [str(c).upper() for c in (p.get("taken_codes") or [])]
    engine.max_hours = int(p.get("max_hours", 18) or 18)
    if engine.max_hours > 18:
        engine.max_hours = 18

    # build taken_courses from plan using the CODES
    engine.taken_courses = {
        c: {"hours": engine.plan.get(c, {}).get("hours", 3)}
        for c in taken_codes if c in engine.plan
    }

    use_offered = bool(p.get("use_offered", True))

    # ---- simple mode (checkbox OFF) ----
    if not use_offered:
        picked = engine.simple_recommendation(taken_codes)
        result = []
        for code in picked:
            info = engine.plan.get(code, {})
            result.append({
                "code": code,
                "name": info.get("name", code),
                "hours": int(info.get("hours", 3)),
                "time": "",
                "instructor": "",
                "category": info.get("category", "")
            })
        return jsonify({
            "ok": True,
            "total_hours": sum(x["hours"] for x in result),
            "courses": result,
            "mode": "simple"
        })

    # ---- GA mode (checkbox ON / default) ----
    offered_all = ensure_offered_cached(refresh=bool(p.get("refresh_offered", False)))
    eligible, rejected = engine.filter_offered_by_plan_and_taken(
        offered_all, engine.plan, engine.taken_courses
    )
    engine.offered = eligible

    if not eligible:
        return jsonify({
            "ok": False,
            "message": "لا توجد مواد متاحة الآن بعد تطبيق المتطلبات/الحدود.",
            "rejected": list(rejected.items())[:40],
            "rejected_human": _humanize_rejected(rejected),
            "mode": "ga"
        }), 200

    best = engine.genetic_algorithm(population_size=100, generations=150)
    total_hours = sum(eligible[c]["hours"] for c in best) if best else 0
    assignment = engine.assign_non_conflicting_sections(best, eligible) if best else None

    if not best or total_hours == 0 or total_hours > engine.max_hours:
        return jsonify({
            "ok": False,
            "message": "تعذر إيجاد توليفة مناسبة ضمن القيود الحالية.",
            "rejected": list(rejected.items())[:40],
            "rejected_human": _humanize_rejected(rejected),
            "mode": "ga"
        }), 200

    result = []
    for code in best:
        chosen = (assignment or {}).get(code) or {}
        times_str = chosen.get("time") or " | ".join(chosen.get("times", [])) if chosen else ""
        instr = chosen.get("instructor", "")
        hours = eligible[code]["hours"]
        name  = engine.plan.get(code, {}).get("name", eligible[code]["name"])
        category = engine.plan.get(code, {}).get("category", "")
        result.append({
            "code": code,
            "name": name,
            "hours": hours,
            "time": times_str,
            "instructor": instr,
            "category": category
        })

    while sum(x["hours"] for x in result) > engine.max_hours and result:
        result.pop()

    return jsonify({
        "ok": True,
        "total_hours": sum(x["hours"] for x in result),
        "courses": result,
        "rejected": list(rejected.items())[:20],
        "rejected_human": _humanize_rejected(rejected),
        "mode": "ga"
    })

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
