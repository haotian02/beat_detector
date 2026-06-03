"""HTTP control panel for the beat detector. Zero extra dependencies."""

import json
import logging
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

if __package__:
    from .shared_state import SharedState
else:
    from shared_state import SharedState

logger = logging.getLogger(__name__)


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>Beat Detector Console</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font:14px/1.5 system-ui,sans-serif;background:#111;color:#eee;padding:12px;max-width:640px;margin:0 auto;
  -webkit-tap-highlight-color:transparent;user-select:none}
h1{font-size:20px;margin-bottom:6px;text-align:center}
.lang-bar{display:flex;justify-content:center;gap:8px;margin-bottom:14px}
.lang-btn{background:#2a2a4a;border:1px solid #444;color:#aaa;padding:4px 14px;border-radius:6px;cursor:pointer;
  font-size:12px;transition:.2s}
.lang-btn.active{background:#6c5ce7;border-color:#6c5ce7;color:#fff}
.card{background:#1a1a2e;border-radius:12px;padding:14px;margin-bottom:12px}
.row{display:flex;align-items:center;justify-content:space-between;margin:10px 0}
label{color:#aaa;font-size:13px}
.val{font-size:18px;font-weight:600;font-variant-numeric:tabular-nums}
.slider{width:100%;margin:4px 0;accent-color:#6c5ce7;height:24px}
input[type=text]{background:#2a2a4a;border:1px solid #444;color:#fff;padding:8px 10px;
  border-radius:8px;width:72px;text-align:center;font-size:18px}
canvas{width:100%;height:100px;background:#0a0a1a;border-radius:8px;display:block}
.stat-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.stat{text-align:center;padding:6px 0}
.stat .label{font-size:11px;color:#888}
.stat .num{font-size:20px;font-weight:700}
.flux-num{color:#6c5ce7}
.thr-num{color:#e17055}
.ratio-num{color:#fdcb6e}
.beat-num{color:#00b894}
.beat-row .val{color:#00b894}
.url-hint{text-align:center;font-size:12px;color:#555;margin-top:8px}
.url-hint span{color:#888}
.toggle-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.toggle-row .label{font-size:15px;font-weight:600;color:#eee}
.switch{position:relative;display:inline-block;width:52px;height:28px}
.switch input{opacity:0;width:0;height:0}
.slider-btn{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:#444;border-radius:28px;transition:.2s}
.slider-btn:before{position:absolute;content:"";height:22px;width:22px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.2s}
input:checked+.slider-btn{background:#00b894}
input:checked+.slider-btn:before{transform:translateX(24px)}

@media (max-width:480px){
  body{padding:8px}
  h1{font-size:18px;margin-bottom:4px}
  .lang-bar{margin-bottom:10px}
  .card{padding:12px;border-radius:10px}
  .stat .num{font-size:18px}
  .val{font-size:16px}
  canvas{height:80px}
  input[type=text]{font-size:16px;padding:8px}
  label{font-size:12px}
  .slider{height:28px;margin:6px 0}
  .row{margin:12px 0}
}
</style>
</head>
<body>
<h1 data-i18n="title">Beat Detector Console</h1>

<div class="lang-bar">
  <button class="lang-btn active" data-lang="zh">中文</button>
  <button class="lang-btn" data-lang="en">English</button>
</div>

<div class="card">
  <canvas id="canvas"></canvas>
</div>

<div class="card">
  <div class="stat-grid">
    <div class="stat"><span class="label" data-i18n="flux">Spectral Flux</span><div class="num flux-num" id="flux">--</div></div>
    <div class="stat"><span class="label" data-i18n="threshold">Threshold</span><div class="num thr-num" id="thr">--</div></div>
    <div class="stat"><span class="label" data-i18n="ratio">Ratio</span><div class="num ratio-num" id="ratio">--</div></div>
    <div class="stat"><span class="label" data-i18n="beats">Beat Count</span><div class="num beat-num" id="beats">0</div></div>
  </div>
</div>

<div class="card">
  <div class="toggle-row">
    <span class="label" id="toggle_label" data-i18n="detection">Detection</span>
    <label class="switch">
      <input type="checkbox" id="enabled" checked>
      <span class="slider-btn"></span>
    </label>
  </div>
</div>

<div class="card">
  <div class="row"><label data-i18n="sensitivity">Sensitivity</label><span class="val" id="sens_val">1.5</span></div>
  <input class="slider" id="sensitivity" type="range" min="0.1" max="5" step="0.05" value="1.5">

  <div class="row"><label data-i18n="noise_floor">Noise Floor</label><span class="val" id="noise_val">50</span></div>
  <input class="slider" id="noise_floor" type="range" min="0" max="300" step="5" value="50">

  <div class="row"><label data-i18n="min_interval">Min Interval (ms)</label><span class="val" id="int_val">50</span></div>
  <input class="slider" id="min_interval" type="range" min="20" max="500" step="5" value="50">

  <div class="row"><label data-i18n="hop_size">Hop Size</label><span class="val" id="hop_val">256</span></div>
  <input class="slider" id="hop_size" type="range" min="128" max="1024" step="128" value="256">

  <div class="row"><label data-i18n="keybind">Simulated Key</label>
    <input type="text" id="keybind" value="s" maxlength="1" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
  </div>
</div>

<div class="url-hint"><span data-i18n="lan_access">LAN Access</span>: <span id="lan_url">--</span></div>

<script>
// ── i18n ──────────────────────────────────────────────────────
const I18N={
  zh:{
    title:'鼓点检测控制台',
    flux:'频谱通量',
    threshold:'触发阈值',
    ratio:'比值',
    beats:'击中次数',
    detection:'检测开关',
    detection_on:'检测已开启',
    detection_off:'检测已关闭',
    sensitivity:'灵敏度',
    noise_floor:'噪声底线 (低于此值不触发)',
    min_interval:'最小间隔 (毫秒)',
    hop_size:'处理步长 (越大越省CPU)',
    keybind:'模拟按键',
    lan_access:'局域网访问'
  },
  en:{
    title:'Beat Detector Console',
    flux:'Spectral Flux',
    threshold:'Threshold',
    ratio:'Ratio',
    beats:'Beat Count',
    detection:'Detection',
    detection_on:'Detection ON',
    detection_off:'Detection OFF',
    sensitivity:'Sensitivity',
    noise_floor:'Noise Floor',
    min_interval:'Min Interval (ms)',
    hop_size:'Hop Size',
    keybind:'Simulated Key',
    lan_access:'LAN Access'
  }
};

let currentLang='zh';

function setLang(lang){
  currentLang=lang;
  document.documentElement.lang=lang;
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const key=el.getAttribute('data-i18n');
    if(I18N[lang] && I18N[lang][key]) el.textContent=I18N[lang][key];
  });
  // Update toggle label based on current enabled state
  const en=document.getElementById('enabled');
  const tl=document.getElementById('toggle_label');
  if(en && tl){
    tl.textContent=en.checked ? I18N[lang].detection_on : I18N[lang].detection_off;
  }
  // Update active button
  document.querySelectorAll('.lang-btn').forEach(b=>b.classList.toggle('active',b.getAttribute('data-lang')===lang));
  localStorage.setItem('beat_detector_lang',lang);
}

// Init language from localStorage
const savedLang=localStorage.getItem('beat_detector_lang')||'zh';
setLang(savedLang);

document.querySelectorAll('.lang-btn').forEach(btn=>{
  btn.addEventListener('click',function(){
    setLang(this.getAttribute('data-lang'));
  });
});

// ── Waveform Canvas ───────────────────────────────────────────
let history=[];
const canvas=document.getElementById('canvas'),ctx=canvas.getContext('2d');
function resize(){canvas.width=canvas.offsetWidth*2;canvas.height=canvas.offsetHeight*2}
resize();window.addEventListener('resize',resize);

function draw(){
  const w=canvas.width,h=canvas.height;
  ctx.clearRect(0,0,w,h);
  if(!history.length)return;
  const max=Math.max(...history,1);
  ctx.beginPath();
  ctx.strokeStyle='#6c5ce7';ctx.lineWidth=1.5;
  const step=w/history.length;
  history.forEach((v,i)=>{
    const x=i*step,y=h-(v/max)*h;
    i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
  });
  ctx.stroke();
  const thr=parseFloat(document.getElementById('thr').textContent)||0;
  if(thr>0){
    ctx.beginPath();ctx.strokeStyle='#e17055';ctx.lineWidth=1;
    ctx.setLineDash([4,4]);
    const y=h-(thr/max)*h;
    ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();
    ctx.setLineDash([]);
  }
}

// ── Config sync ───────────────────────────────────────────────
let lastSent={};
function send(k,v){
  if(lastSent[k]===v)return;
  lastSent[k]=v;
  fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({[k]:v})});
}
document.getElementById('enabled').addEventListener('change',function(){
  document.getElementById('toggle_label').textContent=this.checked?I18N[currentLang].detection_on:I18N[currentLang].detection_off;
  send('enabled',this.checked);
});
document.getElementById('sensitivity').addEventListener('input',function(){
  document.getElementById('sens_val').textContent=this.value;
  send('sensitivity',parseFloat(this.value));
});
document.getElementById('noise_floor').addEventListener('input',function(){
  document.getElementById('noise_val').textContent=this.value;
  send('noise_floor',parseFloat(this.value));
});
document.getElementById('min_interval').addEventListener('input',function(){
  document.getElementById('int_val').textContent=this.value;
  send('min_interval_ms',parseInt(this.value));
});
document.getElementById('hop_size').addEventListener('input',function(){
  document.getElementById('hop_val').textContent=this.value;
  send('hop_size',parseInt(this.value));
});
document.getElementById('keybind').addEventListener('change',function(){
  send('keybind',this.value||'s');
});

// ── Poll state ────────────────────────────────────────────────
async function poll(){
  try{
    const r=await fetch('/api/state');
    const s=await r.json();
    document.getElementById('flux').textContent=s.flux;
    document.getElementById('thr').textContent=s.threshold;
    document.getElementById('ratio').textContent=s.ratio.toFixed(2);
    document.getElementById('beats').textContent=s.beat_count;
    const cfg=s.config;
    const sens=document.getElementById('sensitivity');
    if(document.activeElement!==sens){sens.value=cfg.sensitivity;document.getElementById('sens_val').textContent=cfg.sensitivity;}
    const nf=document.getElementById('noise_floor');
    if(document.activeElement!==nf){nf.value=cfg.noise_floor;document.getElementById('noise_val').textContent=cfg.noise_floor;}
    const mi=document.getElementById('min_interval');
    if(document.activeElement!==mi){mi.value=cfg.min_interval_ms;document.getElementById('int_val').textContent=cfg.min_interval_ms;}
    const hop=document.getElementById('hop_size');
    if(document.activeElement!==hop){hop.value=cfg.hop_size;document.getElementById('hop_val').textContent=cfg.hop_size;}
    const kb=document.getElementById('keybind');
    if(document.activeElement!==kb)kb.value=cfg.keybind;
    const en=document.getElementById('enabled');
    if(en.checked!==cfg.enabled){en.checked=cfg.enabled;document.getElementById('toggle_label').textContent=cfg.enabled?I18N[currentLang].detection_on:I18N[currentLang].detection_off;}
    document.getElementById('lan_url').textContent='http://__LAN_IP__:'+location.port;
    history=s.history||[];
    draw();
  }catch(e){}
  setTimeout(poll,100);
}
poll();
</script>
</body>
</html>"""


class _Handler(BaseHTTPRequestHandler):
    server_state: SharedState = None

    def log_message(self, fmt, *args):
        pass

    def _json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            html = PAGE_HTML.replace("__LAN_IP__", _local_ip())
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/state":
            self._json(self.server.server_state.snapshot())
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/config":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length)) if length else {}
            cfg = self.server.server_state.config
            if "sensitivity" in data:
                cfg.sensitivity = float(data["sensitivity"])
            if "noise_floor" in data:
                cfg.noise_floor = float(data["noise_floor"])
            if "min_interval_ms" in data:
                cfg.min_interval_ms = int(data["min_interval_ms"])
            if "hop_size" in data:
                cfg.hop_size = int(data["hop_size"])
            if "keybind" in data:
                cfg.keybind = str(data["keybind"])[0].lower()
            if "enabled" in data:
                cfg.enabled = bool(data["enabled"])
            self._json({"ok": True})
        else:
            self.send_error(404)


class WebServer:
    def __init__(self, state: SharedState, port: int = 8080):
        self._state = state
        self._port = port

    def _run(self):
        server = HTTPServer(("0.0.0.0", self._port), _Handler)
        server.server_state = self._state
        ip = _local_ip()
        logger.info("Web control panel: http://localhost:%d", self._port)
        logger.info("LAN access: http://%s:%d", ip, self._port)
        try:
            server.serve_forever()
        except Exception:
            pass

    def start(self):
        t = threading.Thread(target=self._run, daemon=True, name="web-server")
        t.start()
