# -*- coding: utf-8 -*-
from __future__ import annotations
import os, threading, re
from typing import Dict

from flask import Flask, jsonify, request, send_from_directory
import engine



# --- add near the top of app.py ---
COURSE_BULLETIN_URL = "http://appserver.fet.edu.jo:7778/courses/index.jsp"

# يقدّم الواجهة من ../frontend (عدّل المسار حسب مشروعك)
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="/")

@app.get("/")
def index():
    return app.send_static_file("index.html")
# كاش لجريدة المواد (نتيجة السكربر)
_offered_cache: Dict[str, dict] = {}
_cache_lock = threading.Lock()

# -------- سكربر Placeholder (صِل سكربرك الحقيقي هنا) --------
def scrape_offered_courses_placeholder() -> Dict[str, dict]:
    """
    إذا لديك سكربر Selenium يعيد:
    { 'ELE1234': {'name': '...', 'hours': 3, 'sections': [
        {'dept':10,'instructor':'...','state':'...','times':['ث 10:00 11:00','ر 10:00 11:00'],'time':'ث 10:00 11:00 | ر 10:00 11:00'}
    ]}, ... }
    فاستبدل هذا بـ return من سكربرك.
    """
    return {}

def ensure_offered_cached(refresh: bool = False):
    """يشغّل السكربر مرة واحدة (أو عند طلب التحديث)."""
    global _offered_cache
    with _cache_lock:
        if refresh or not _offered_cache:
            try:
                _offered_cache = scrape_offered_courses_placeholder() or {}
            except Exception:
                _offered_cache = {}
    return _offered_cache

# -------- تطبيع ومطابقة أسماء العربية --------
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_ASCII_DIGITS  = "0123456789"
TRANS = str.maketrans({a:b for a,b in zip(_ARABIC_DIGITS, _ASCII_DIGITS)})

def _normalize_ar(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = name.translate(TRANS)        # توحيد الأرقام
    s = s.replace("ـ", "").replace("–", "-").replace("—", "-")
    # إزالة التشكيل
    s = "".join(ch for ch in s if not ("\u064b" <= ch <= "\u0652"))
    # إزالة رموز شائعة
    s = re.sub(r"[()\\[\\]{}،,:;|]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _map_offered_to_plan(offered_by_code: dict) -> dict:
    """
    يُرجع: قاموس مَفاتيحه = اسم المادة بالعربية كما في (engine.plan),
           وقيمه = {hours, code, sections:[...], time/instructor/state (سِطحيّة اختيارية)}
    مع مطابقة مرنة للأسماء.
    """
    offered_by_name = {}
    for code, meta in (offered_by_code or {}).items():
        nm = (meta.get("name") or "").strip()
        if not nm:
            continue
        offered_by_name[nm] = {
            "name": nm,
            "code": code,
            "hours": int(meta.get("hours", 0) or 0),
            "sections": meta.get("sections", []),
            "time": meta.get("time", ""),
            "instructor": meta.get("instructor", ""),
            "state": meta.get("state", ""),
        }

    plan_names = list(engine.plan.keys())
    plan_norm = { _normalize_ar(n): n for n in plan_names }

    mapped = {}
    for offered_name, meta in offered_by_name.items():
        on = _normalize_ar(offered_name)

        if on in plan_norm:
            mapped[ plan_norm[on] ] = meta
            continue

        candidates = [pn for pn_norm, pn in plan_norm.items() if on in pn_norm or pn_norm in on]
        if len(candidates) == 1:
            mapped[candidates[0]] = meta
            continue

        toks_on = set(on.split())
        best = None
        best_score = 0
        for pn_norm, pn in plan_norm.items():
            toks_pn = set(pn_norm.split())
            score = len(toks_on & toks_pn)
            if score > best_score:
                best_score = score
                best = pn
        if best and best_score >= 2:
            mapped[best] = meta

    return mapped

# -------- المسارات --------
@app.get("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.get("/api/plan")
def api_plan():
    # Optional: /api/plan?reload=1 لإعادة قراءة ملف Excel أثناء التطوير
    if request.args.get("reload") == "1":
        try:
            engine.plan = engine.load_plan_from_excel(engine.EXCEL_PATH)
        except Exception as e:
            return jsonify({"ok": False, "message": f"فشل تحميل الخطة من الإكسل: {e}"}), 500

    out = [
        {
            "code": name,  # FE يستخدمه كمُعرّف؛ اسم المادة ثابت وفريد
            "name": name,
            "category": info.get("category", ""),
            "hours": int(info.get("hours", 3)),
            "prerequisites": info.get("prerequisites", []),
        }
        for name, info in engine.plan.items()  # <-- كل المواد من الإكسل
    ]
    return jsonify(out)

@app.post("/api/recommend")
def api_recommend():
    p = request.get_json(force=True) or {}
    taken_names = p.get("taken_codes", []) or []
    max_hours   = int(p.get("max_hours", 18) or 18)
    use_offered = bool(p.get("use_offered", True))
    refresh     = bool(p.get("refresh_offered", False))
    if max_hours > 18:
        max_hours = 18

    # تجهيز offered بحسب الوضع
    if use_offered:
        raw = {}
        try:
            raw = ensure_offered_cached(refresh=refresh)  # {code: {... name, hours, sections:[...]}}
        except Exception:
            raw = {}
        offered_by_plan_name = _map_offered_to_plan(raw)
    else:
        # وضع الأسماء فقط (بدون أوقات/شعب)
        offered_by_plan_name = {
            name: {
                "name": name,
                "code": None,
                "hours": engine.plan.get(name, {}).get("hours", 3),
                "sections": [],
                "time": "",
                "instructor": "",
                "state": "",
            }
            for name in engine.plan.keys()
        }

    # مرّر السياق للمحرّك
    engine.max_hours = max_hours
    engine.offered = offered_by_plan_name            # مفاتيحها = اسم المادة كما في الخطة
    engine.taken_courses = {n: {"hours": engine.plan.get(n, {}).get("hours", 3)} for n in taken_names}

    # GA ثم Greedy ثم (وضع أسماء فقط)
    best, chosen = engine.genetic_algorithm()

    total = 0
    if best:
        for n in best:
            meta = offered_by_plan_name.get(n, {})
            total += int(meta.get("hours") or engine.plan.get(n, {}).get("hours", 0))

    if (not best) or total == 0:
        best, total = engine.greedy_fallback(offered_by_plan_name, taken_names, max_hours)
        chosen = engine.assign_non_conflicting_sections(best, offered_by_plan_name) if best else None

    if (not best) and (not use_offered):
        best  = engine.simple_recommendation(taken_names, max_hours)
        chosen = None  # لا أوقات
        total = sum(engine.plan.get(n, {}).get("hours", 0) for n in best)

    if not best:
        msg = "لم يتم العثور على توليفة مناسبة."
        if use_offered and not offered_by_plan_name:
            return jsonify({
                "ok": False,
                "message": msg + " (لم نتمكن من مطابقة/جلب جريدة المواد — جرّب التحديث أو افتح جريدة المواد)",
                "redirect_url": COURSE_BULLETIN_URL,
                "can_refresh": True
            })
        return jsonify({"ok": False, "message": msg})

    # بناء الرد (إن وُجد chosen استخدم وقته ومدرّسه بالضبط)
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

    # conflicts = [] لأننا اخترنا شعباً بلا تعارض
    return jsonify({"ok": True, "total_hours": int(total), "courses": result, "conflicts": []})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
