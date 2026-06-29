"""Vue 'live' de l'activite Operator : une fenetre (page HTML autonome) qui se
connecte au WebSocket de Jarvis (ws://127.0.0.1:8765) et affiche EN DIRECT le flux
d'activite (operator_step) comme une 'video' — une carte par mail / rdv / devis /
recherche, avec la categorie, l'action faite, et le POURQUOI (raison).

Ouverte par la commande vocale 'montre ce que tu as fait avec ma boite mail'
(intention activity_show). Page 100% autonome (CSS+JS inline), aucune dependance,
ouverte dans le navigateur par defaut. Le client est loopback -> il recoit les
broadcasts operator_* (restreints au loopback pour la confidentialite).
"""

from __future__ import annotations

import os
import tempfile
import webbrowser
from pathlib import Path

_HTML = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jarvis - Activite</title>
<style>
  :root{--bg:#070b14;--card:#0f1626;--bd:#1d2b44;--accent:#4be1ff;--txt:#dceaf3;--dim:#8aa0b6;}
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(ellipse at top,#0a101c,#04060c 70%);color:var(--txt);
       font:14px/1.5 system-ui,'Segoe UI',sans-serif;}
  header{position:sticky;top:0;z-index:2;background:rgba(7,11,20,.9);backdrop-filter:blur(6px);
         padding:14px 18px;border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:10px;}
  header h1{font-size:16px;margin:0;font-weight:600}
  .dot{width:9px;height:9px;border-radius:50%;background:#54627a}
  .on{background:#39d98a;box-shadow:0 0 8px #39d98a}
  .off{background:#e35a6b}
  #status{margin-left:auto;color:var(--dim);font-size:12px}
  #feed{max-width:760px;margin:0 auto;padding:16px;display:flex;flex-direction:column;gap:10px;}
  .card{background:var(--card);border:1px solid var(--bd);border-left:3px solid var(--accent);
        border-radius:10px;padding:10px 12px;animation:in .35s ease;}
  @keyframes in{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:none}}
  .top{display:flex;align-items:center;gap:8px}
  .badge{font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding:2px 8px;border-radius:999px;
         background:rgba(75,225,255,.14);color:var(--accent);font-weight:700}
  .ts{margin-left:auto;color:var(--dim);font-size:12px;font-variant-numeric:tabular-nums}
  .titre{font-weight:600;margin:4px 0 0}
  .detail{color:var(--dim)}
  .raison{margin-top:5px;font-style:italic;color:#b9cbe0;font-size:13px}
  .ok{border-left-color:#39d98a}
  .info{border-left-color:#4be1ff}
  .attente{border-left-color:#f3b13b}
  .erreur{border-left-color:#e35a6b}
  .empty{color:var(--dim);text-align:center;padding:48px 16px}
</style></head>
<body>
<header><span id="led" class="dot off"></span><h1>Jarvis - ce que je fais</h1><span id="status">connexion...</span></header>
<div id="feed"><div class="empty" id="empty">En attente d'activite...</div></div>
<script>
(function(){
  var feed=document.getElementById('feed'),led=document.getElementById('led'),
      st=document.getElementById('status'),empty=document.getElementById('empty');
  function esc(s){var d=document.createElement('div');d.textContent=(s==null?'':String(s));return d.innerHTML;}
  function card(ev){
    if(empty){empty.remove();empty=null;}
    var cat=esc(ev.categorie||ev.type||'info'),statut=esc(ev.statut||'info');
    var div=document.createElement('div');div.className='card '+statut;
    var raison=ev.raison?'<div class="raison">&#8627; '+esc(ev.raison)+'</div>':'';
    var detail=ev.detail?'<div class="detail">'+esc(ev.detail)+'</div>':'';
    div.innerHTML='<div class="top"><span class="badge">'+cat+'</span><span class="ts">'+esc(ev.ts||'')+'</span></div>'
      +'<div class="titre">'+esc(ev.titre||ev.detail||'')+'</div>'+detail+raison;
    feed.insertBefore(div,feed.firstChild);
    while(feed.children.length>200)feed.removeChild(feed.lastChild);
  }
  function connect(){
    var ws;
    try{ws=new WebSocket('ws://127.0.0.1:8765');}catch(e){setTimeout(connect,2000);return;}
    ws.onopen=function(){led.className='dot on';st.textContent='en direct';
      try{ws.send(JSON.stringify({type:'dash_operator_init'}));}catch(e){}};
    ws.onclose=function(){led.className='dot off';st.textContent='reconnexion...';setTimeout(connect,2000);};
    ws.onerror=function(){try{ws.close();}catch(e){}};
    ws.onmessage=function(m){
      var d;try{d=JSON.parse(m.data);}catch(e){return;}
      if(d.action==='operator_step'&&d.etape)card(d.etape);
      else if(d.action==='operator_activity'&&d.evenement)card(d.evenement);
      else if(d.action==='dash_operator_state'&&Array.isArray(d.activity))d.activity.forEach(card);
    };
  }
  connect();
})();
</script>
</body></html>
"""


def _dossier() -> Path:
    d = Path(tempfile.gettempdir()) / "jarvis_operator_live"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ecrire() -> str:
    """Ecrit la page HTML autonome et renvoie son chemin. Ne leve jamais."""
    p = _dossier() / "activite.html"
    p.write_text(_HTML, encoding="utf-8")
    return str(p)


def ouvrir() -> bool:
    """Ecrit la page et l'ouvre dans le navigateur (fenetre Jarvis). Best-effort."""
    try:
        path = ecrire()
        try:
            os.startfile(path)  # type: ignore[attr-defined]  # Windows
        except Exception:
            webbrowser.open("file:///" + path.replace(os.sep, "/"))
        return True
    except Exception as e:
        print(f"[OPERATOR-LIVE] Ouverture echouee : {e}")
        return False
