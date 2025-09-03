// ====== الحالة العامة ======
let PLAN_DATA = [];
const selected = new Set();
const groupsOrder = [
  'major_required','major_optional','college_required','university_required','elective_requirements','Remedial materials','other'
];
const labels = {
  major_required: 'متطلبات التخصص الإجباريّة',
  major_optional: 'متطلبات التخصص الاختياريّة',
  college_required: 'متطلبات الكلية الإجباريّة',
  university_required: 'متطلبات الجامعة الإجباريّة',
  elective_requirements: 'متطلبات الجامعة الاختياريّة',
  'Remedial materials': 'مواد استدراكية',
  other: 'أخرى'
};

// ====== أدوات مساعدة ======
const qs = (s, el=document)=> el.querySelector(s);
const qsa = (s, el=document)=> [...el.querySelectorAll(s)];
const toast = (msg)=>{ const t=qs('#toast'); t.textContent=msg; t.classList.remove('hidden'); setTimeout(()=>t.classList.add('hidden'), 2400); };
const byArabic = (a,b)=> (a||'').localeCompare(b||'', 'ar');

function setPage(n){
  qs('#page1').classList.toggle('hidden', n!==1);
  qs('#page2').classList.toggle('hidden', n!==2);
  qsa('.step').forEach((el,i)=> el.classList.toggle('current', i===n-1));
}
function updateSelectedCount(){ qs('#selectedCount').textContent = selected.size; }

function unmetPrereqsFor(item){
  // backend may return prerequisites as 'prerequisites' or 'prereqs'
  const prereqs = Array.isArray(item.prerequisites) ? item.prerequisites
                    : Array.isArray(item.prereqs) ? item.prereqs : [];
  return prereqs.filter(p => !selected.has(p));
}

// ====== رسم المواد بالمجموعات ======
function renderSubjects(filterText=''){
  const box = qs('#subjectsBox');
  box.innerHTML = '';
  const groups = {};
  PLAN_DATA.forEach(it=>{ const cat = it.category || 'other'; (groups[cat] ||= []).push(it); });

  const compact = qs('#uiMode')?.value === 'compact';

  groupsOrder.forEach(cat=>{
    if(!groups[cat]) return;
    const arr = groups[cat].slice().sort((a,b)=> byArabic(a.name,b.name));
    const filtered = filterText ? arr.filter(x =>
      (x.name && x.name.includes(filterText)) || (x.code && x.code.includes(filterText)) ) : arr;

    const d = document.createElement('details'); d.open = !compact; d.style.background='#fff';
    const s = document.createElement('summary'); s.textContent = `${labels[cat]||cat} (${filtered.length})`;
    const list = document.createElement('div'); list.className = 'chiplist';

    filtered.forEach(it=>{
      const unmet = unmetPrereqsFor(it);
      const disabled = unmet.length > 0;
      const span = document.createElement('span');
      span.className = 'chip' + (selected.has(it.code) ? ' selected' : '') + (disabled ? ' disabled' : '');
      span.dataset.code = it.code; 
      const hrs = (it.hours!=null && it.hours!=='') ? ` • ${it.hours}س` : '';
      span.textContent = (it.name || it.code) + hrs;
      span.title = disabled && unmet.length ? `لا بد من إنهاء: ${unmet.join('، ')}` : (it.code || '');
      span.onclick = () => { 
        if(disabled){ toast(span.title || 'هذه المادة لها متطلب سابق'); return; }
        span.classList.toggle('selected');
        if(span.classList.contains('selected')) selected.add(it.code); else selected.delete(it.code);
        updateSelectedCount();
        renderSubjects(qs('#search').value.trim()); // تحديث حالات التعطيل
      };
      list.appendChild(span);
    });
    if(!filtered.length){ const empty=document.createElement('div'); empty.className='muted'; empty.style.padding='8px 12px'; empty.textContent='لا توجد عناصر.'; list.appendChild(empty); }
    d.appendChild(s); d.appendChild(list); box.appendChild(d);
  });

  if(!box.children.length){ const empty=document.createElement('div'); empty.className='muted'; empty.style.padding='10px'; empty.textContent='لا توجد بيانات خطة.'; box.appendChild(empty); }
}

// ====== تحميل الخطة من الخادم ======
async function loadPlan(){
  const loader = qs('#planLoader'); loader?.classList.remove('hidden');
  try{
    const r = await fetch('/api/plan', {cache:'no-store'});
    if(!r.ok) throw new Error('تعذّر تحميل الخطة');
    PLAN_DATA = await r.json();
    renderSubjects();
  }catch(e){ toast('خطأ في تحميل الخطة'); console.error(e); }
  finally{ loader?.classList.add('hidden'); }
}

// ====== توليد الجدول وإظهار النتيجة في نفس الصفحة ======
async function generate(){
  const max = parseInt(qs('#hoursSelect').value, 10) || 18;
  const use_offered = !!qs('#useOffered')?.checked;
  const body = JSON.stringify({ taken_codes: Array.from(selected), max_hours: max, use_offered });
  qs('#genText').textContent = 'جارِ التوليد…'; qs('#genSpin').classList.remove('hidden');

  // تفريغ النتائج السابقة
  qs('#summary').textContent = '';
  qs('#kpiHours').textContent = '0';
  qs('#kpiCount').textContent = '0';
  qs('#kpiConflicts').textContent = '0';
  qs('#resultTable tbody').innerHTML = '';

  try{
    const r = await fetch('/api/recommend', { method:'POST', headers:{'Content-Type':'application/json'}, body });
    const data = await r.json();

    if(!data.ok){
      qs('#summary').textContent = data.message || 'تعذّر توليد الجدول.';
      qs('#results').classList.remove('hidden');
      return;
    }

    (data.courses||[]).forEach(c=>{
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${c.name||c.code||''}</td>
        <td>${c.hours??''}</td>
        <td>${c.time??''}</td>
        <td>${c.instructor??''}</td>
        <td>${c.category??''}</td>`;
      qs('#resultTable tbody').appendChild(tr);
    });

    qs('#kpiHours').textContent = data.total_hours||0;
    qs('#kpiCount').textContent = (data.courses||[]).length;
    qs('#kpiConflicts').textContent = data.conflicts?.length||0;
    qs('#summary').textContent = `عدد الساعات: ${(data.total_hours||0)} / ${max}` + (use_offered ? '' : ' — (وضع بدون أوقات)');
    qs('#results').classList.remove('hidden');
  }catch(e){ toast('فشل التوليد، تحقّق من الخادم'); console.error(e); }
  finally{ qs('#genText').textContent = 'توليد الجدول'; qs('#genSpin').classList.add('hidden'); }
}

// ====== تهيئة الصفحة ======
window.addEventListener('DOMContentLoaded', ()=>{
  // الانتقال من صفحة التخصص إلى صفحة المواد
  qs('#toSubjects').onclick = ()=>{ setPage(2); if(!PLAN_DATA.length) loadPlan(); };

  // البحث + مسح التحديد
  qs('#search').addEventListener('input', e=> renderSubjects(e.target.value.trim()));
  qs('#clearSel').onclick = ()=>{ selected.clear(); qsa('.chip.selected').forEach(c=>c.classList.remove('selected')); updateSelectedCount(); renderSubjects(qs('#search').value.trim()); };

  // واجهة العرض تؤثر على فتح/طيّ المجموعات
  qs('#uiMode').addEventListener('change', ()=> renderSubjects(qs('#search').value.trim()));

  // توليد
  qs('#genBtn').onclick = generate;

  // صفحة البداية
  setPage(1);
});
