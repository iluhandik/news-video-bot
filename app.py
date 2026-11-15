<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>News Studio · 365</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800;900&display=swap" rel="stylesheet">
<style>
:root { --bg: #06070D; --card: rgba(20, 26, 38, 0.7); --border: rgba(255,255,255,0.08); --txt: #EAF0FF; --txt-dim: #8A97AC; --blue: #2AABEE; --red: #FF3B4E; --gold: #FFC847; --green: #2EE07A; }
* { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
body { background: var(--bg); color: var(--txt); min-height: 100vh; overflow-x: hidden; }
body::before { content: ''; position: fixed; inset: -20%; background: radial-gradient(900px 700px at 15% 15%, rgba(42, 171, 238, 0.18), transparent 60%), radial-gradient(800px 600px at 85% 20%, rgba(180, 40, 200, 0.13), transparent 60%), var(--bg); z-index: -1; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 30px 20px 60px; }
header { text-align: center; margin-bottom: 36px; }
h1 { font-size: clamp(26px, 4vw, 40px); font-weight: 900; background: linear-gradient(120deg, #fff, #8CC7FF, #FFBEE9); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px; }
.subtitle { color: var(--txt-dim); font-size: 15px; font-weight: 500; line-height: 1.5; }
.box { background: var(--card); border: 1px solid var(--border); border-radius: 24px; padding: 28px; backdrop-filter: blur(24px); box-shadow: 0 20px 80px rgba(0,0,0,0.4); }
textarea { width: 100%; height: 170px; background: rgba(0,0,0,0.35); border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; color: var(--txt); font-size: 15px; resize: vertical; outline: none; transition: .2s; font-family: inherit; }
textarea:focus { border-color: var(--blue); box-shadow: 0 0 0 4px rgba(42, 171, 238, 0.15); }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 18px; background: rgba(0,0,0,0.25); padding: 14px 20px; border-radius: 14px; border: 1px solid var(--border); margin: 16px 0; }
label.opt { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; font-size: 14px; font-weight: 600; padding: 8px 16px; border-radius: 10px; border: 1px solid var(--border); background: rgba(255,255,255,0.03); transition: .2s; }
label.opt:has(input:checked) { background: rgba(42,171,238,0.2); border-color: var(--blue); color: #fff; }
label.opt input { display: none; }
.drop { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; border: 2px dashed rgba(42, 171, 238, 0.5); border-radius: 16px; padding: 24px; cursor: pointer; text-align: center; background: rgba(42,171,238,0.05); margin: 16px 0; transition: .2s; }
.drop.dragover { border-color: var(--blue); background: rgba(42,171,238,0.15); transform: scale(1.02); }
.drop-icon { font-size: 28px; } .drop-text { font-size: 14px; font-weight: 600; } .drop-hint { font-size: 12px; color: var(--txt-dim); }
#mTxt { color: var(--blue); font-weight: 700; margin-top: 6px; font-size: 13px; }
.btn-go { width: 100%; padding: 18px; font-size: 16px; font-weight: 800; border: none; border-radius: 14px; cursor: pointer; color: #fff; background: linear-gradient(135deg, var(--blue), #7B3DD1); box-shadow: 0 12px 40px rgba(42, 171, 238, 0.35); transition: .3s; margin-top: 8px; }
.btn-go:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.1); }
.btn-go:disabled { opacity: 0.6; cursor: not-allowed; }
.progress-wrap { display: none; margin-top: 20px; background: rgba(0,0,0,0.4); border-radius: 10px; padding: 16px; }
#st { display: flex; justify-content: space-between; font-size: 14px; font-weight: 700; color: var(--gold); margin-bottom: 10px; }
.bar-bg { width: 100%; height: 8px; background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden; }
#bar-fill { height: 100%; width: 0%; background: linear-gradient(90deg, var(--blue), var(--gold)); transition: width 0.4s ease; border-radius: 4px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 32px; }
@media (max-width: 860px) { .grid { grid-template-columns: 1fr; } }
.card { background: rgba(12, 17, 26, 0.85); border: 1px solid var(--border); border-radius: 20px; padding: 20px; display: none; animation: slideUp .4s ease-out; }
.card.show { display: block; }
.card.full { border-color: rgba(42, 171, 238, 0.35); }
.card.bait { border-color: rgba(255, 59, 78, 0.35); }
@keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 10px; font-size: 13px; font-weight: 800; margin-bottom: 14px; }
.badge.full { background: rgba(42, 171, 238, 0.15); color: var(--blue); border: 1px solid rgba(42, 171, 238, 0.3); }
.badge.bait { background: rgba(255, 59, 78, 0.15); color: #FF6B7E; border: 1px solid rgba(255, 59, 78, 0.3); }
video { width: 100%; max-height: 500px; border-radius: 14px; background: #000; border: 1px solid var(--border); display: block; }
.seo { background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 12px; padding: 14px; margin-top: 14px; }
.seo-head { display: flex; justify-content: space-between; font-size: 12px; font-weight: 800; color: var(--gold); margin-bottom: 10px; }
.copy-btn { background: rgba(255,255,255,0.06); border: 1px solid var(--border); color: var(--txt); padding: 6px 12px; border-radius: 8px; font-size: 12px; cursor: pointer; font-weight: 700; transition: .2s; }
.copy-btn:hover { background: rgba(255,255,255,0.15); }
.copy-btn.copied { background: var(--green); color: #000; }
.seo-text { font-size: 13px; color: #C8D2E2; white-space: pre-wrap; line-height: 1.6; }
.btn-dl { display: flex; align-items: center; justify-content: center; text-decoration: none; background: linear-gradient(135deg, var(--green), #1FB863); color: #051A0C; padding: 14px; border-radius: 12px; font-weight: 800; font-size: 14px; margin-top: 14px; box-shadow: 0 8px 24px rgba(46, 224, 122, 0.25); transition: .2s; }
.btn-dl:hover { transform: translateY(-1px); filter: brightness(1.1); }
#toast { position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%) translateY(100px); padding: 14px 24px; border-radius: 12px; font-weight: 800; font-size: 14px; opacity: 0; transition: .3s; z-index: 9999; pointer-events: none; }
#toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
#toast.err { background: var(--red); color: #fff; } #toast.ok { background: var(--green); color: #000; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🎬 News Studio · 365</h1>
    <p class="subtitle">Створення унікальних відео для двох акаунтів за один клік.</p>
  </header>
  <div class="box">
    <textarea id="pTxt" placeholder="Вставте сюди текст новини..." autofocus></textarea>
    <div class="row">
      <span style="font-size:13px; font-weight:700; color:var(--txt-dim);">ГОЛОС:</span>
      <label class="opt"><input type="radio" name="voice" value="uk-UA-PolinaNeural" checked> 👩 Поліна</label>
      <label class="opt"><input type="radio" name="voice" value="uk-UA-OstapNeural"> 👨 Остап</label>
    </div>
    
    <div class="drop" id="dropZone" onclick="document.getElementById('mFile').click()">
      <div class="drop-icon">📹</div>
      <div class="drop-text"><b>Перетягніть відео або фото</b></div>
      <div class="drop-hint">Не обов'язково. Якщо пусто — буде брендовий фон.</div>
      <input type="file" id="mFile" accept="video/*,image/*" style="display:none;" onchange="showF(this)">
      <div id="mTxt"></div>
    </div>

    <button class="btn-go" id="btn" onclick="genBoth()">🚀 Змонтувати 2 відео</button>
    
    <div class="progress-wrap" id="progWrap">
      <div id="st">Ініціалізація... <span id="progTxt">0%</span></div>
      <div class="bar-bg"><div id="bar-fill"></div></div>
    </div>

    <div class="grid">
      <div class="card full" id="cardFull">
        <span class="badge full">📰 Акаунт 1 · Повна новина</span>
        <video id="vidFull" controls playsinline></video>
        <a id="dlFull" class="btn-dl" download>⬇ Скачати MP4</a>
        <div class="seo"><div class="seo-head"><span>🔥 SEO-опис</span><button class="copy-btn" onclick="copyText('seoFull', this)">📋 Копіювати</button></div><div class="seo-text" id="seoFull"></div></div>
        <div class="seo"><div class="seo-head" style="color:var(--blue);"><span>💬 Коментар</span><button class="copy-btn" onclick="copyText('comFull', this)">📋 Копіювати</button></div><div class="seo-text" id="comFull"></div></div>
      </div>
      <div class="card bait" id="cardBait">
        <span class="badge bait">🔥 Акаунт 2 · Перелив у ТГ</span>
        <video id="vidBait" controls playsinline></video>
        <a id="dlBait" class="btn-dl" download>⬇ Скачати MP4</a>
        <div class="seo"><div class="seo-head"><span>🔥 SEO-опис</span><button class="copy-btn" onclick="copyText('seoBait', this)">📋 Копіювати</button></div><div class="seo-text" id="seoBait"></div></div>
        <div class="seo"><div class="seo-head" style="color:#FF8A99;"><span>💬 Коментар</span><button class="copy-btn" onclick="copyText('comBait', this)">📋 Копіювати</button></div><div class="seo-text" id="comBait"></div></div>
      </div>
    </div>
  </div>
</div>
<div id="toast"></div>
<script>
let selectedFile = null;
const dz = document.getElementById('dropZone');

['dragenter', 'dragover'].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); dz.classList.add('dragover'); }));
['dragleave', 'drop'].forEach(e => dz.addEventListener(e, ev => { ev.preventDefault(); dz.classList.remove('dragover'); }));
dz.addEventListener('drop', ev => {
  const files = ev.dataTransfer.files;
  if(files.length > 0) {
    document.getElementById('mFile').files = files;
    showF(document.getElementById('mFile'));
  }
});

function toast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'show ' + type;
  clearTimeout(t._timer); t._timer = setTimeout(() => t.className = '', 3500);
}

function showF(i) {
  if (i.files && i.files[0]) {
    selectedFile = i.files[0];
    document.getElementById('mTxt').innerText = '✓ ' + selectedFile.name;
  }
}

async function genBoth() {
  const btn = document.getElementById('btn'), pWrap = document.getElementById('progWrap');
  const txt = document.getElementById('pTxt').value.trim(), voice = document.querySelector('input[name="voice"]:checked').value;
  if (!txt) { toast('Введіть текст!', 'err'); return; }

  btn.disabled = true;
  document.getElementById('cardFull').classList.remove('show'); document.getElementById('cardBait').classList.remove('show');
  pWrap.style.display = 'block';
  document.getElementById('bar-fill').style.width = '5%';
  document.getElementById('st').innerHTML = '⏳ Підготовка... <span id="progTxt">5%</span>';

  try {
    const fd = new FormData(); fd.append('text', txt); fd.append('voice', voice);
    if (selectedFile) fd.append('media_file', selectedFile);

    const startRes = await fetch('/api/start_both', { method: 'POST', body: fd });
    if (!startRes.ok) throw new Error('Помилка старту');
    const { job_id } = await startRes.json();

    let shownFull = false, shownBait = false;

    while (true) {
      await new Promise(r => setTimeout(r, 1500));
      const pollRes = await fetch('/api/job/' + job_id);
      const job = await pollRes.json();

      if (job.progress !== undefined) document.getElementById('bar-fill').style.width = job.progress + '%';
      document.getElementById('st').innerHTML = (job.step || 'Монтую...') + ` <span id="progTxt">${job.progress || 0}%</span>`;

      if (job.full && !shownFull) {
        shownFull = true;
        document.getElementById('vidFull').src = job.full.video_url;
        document.getElementById('dlFull').href = job.full.video_url;
        document.getElementById('seoFull').textContent = job.full.seo_desc;
        document.getElementById('comFull').textContent = job.full.ready_comment;
        document.getElementById('cardFull').classList.add('show');
      }
      if (job.bait && !shownBait) {
        shownBait = true;
        document.getElementById('vidBait').src = job.bait.video_url;
        document.getElementById('dlBait').href = job.bait.video_url;
        document.getElementById('seoBait').textContent = job.bait.seo_desc;
        document.getElementById('comBait').textContent = job.bait.ready_comment;
        document.getElementById('cardBait').classList.add('show');
      }
      if (job.error) throw new Error(job.error);
      if (job.done) { toast('✅ Готово!', 'ok'); pWrap.style.display = 'none'; break; }
    }
  } catch (e) {
    toast('❌ ' + e.message, 'err'); pWrap.style.display = 'none';
  } finally { btn.disabled = false; }
}

function copyText(id, btn) {
  navigator.clipboard.writeText(document.getElementById(id).textContent).then(() => {
    const orig = btn.textContent; btn.textContent = '✓ Готово'; btn.classList.add('copied');
    setTimeout(() => { btn.textContent = orig; btn.classList.remove('copied'); }, 1500);
  });
}
</script>
</body>
</html>
