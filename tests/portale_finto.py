"""Copia semplificata delle pagine di Sinfonia4You, ricostruita dagli screenshot (dati inventati)."""

import json

from playwright.sync_api import Page, Route

BASE = "https://servizi.aia-figc.it/sinfonia4you/"

STILE = """<style>
body { margin:0; background:#2b5066; font:13px Verdana, sans-serif; color:#222; }
.pagina { width:1100px; margin:0 auto; background:#e8ebf0; min-height:100vh; padding:10px 16px; }
.testata { background:#fff; padding:10px; font-weight:bold; color:#1d3d7a; text-align:right; }
.box { background:#fff; border:1px solid #ccd; margin:10px 0; padding:10px; }
.titolo { background:#2b5066; color:#fff; padding:4px 8px; font-weight:bold; margin:-10px -10px 10px; }
.tabs a { display:inline-block; background:#f5a623; color:#fff; padding:5px 10px; margin-right:2px; text-decoration:none; }
.tabs a.on { background:#fff; color:#f5a623; }
.voce { display:block; padding:6px; border:1px solid #dde; margin:4px 0; color:#1f6fb5; text-decoration:none; font-weight:bold; }
.voce.scelto { background:#fff3cd; border-color:#f5a623; }
.barra { display:flex; justify-content:space-between; background:#fff; padding:8px; margin-top:10px; }
.barra a { border:1px solid #ccd; padding:8px 12px; color:#1f6fb5; font-weight:bold; text-decoration:none; }
.riga { margin-top:6px; } select, input { font-size:12px; }
.giallo { background:#fff3a0; padding:3px 6px; font-weight:bold; margin-top:8px; }
#dlg { border:2px solid #f5a623; padding:10px; box-shadow:0 4px 20px #0006; }
</style>"""


def _scegli(testo: str) -> str:
    return f"""<a href="#" class="voce" onclick="this.classList.add('scelto'); return false">{testo}</a>"""


# Come il portale, "Salva Tutto" salva in background con una richiesta a save.asp (qui in ritardo):
# se il browser si chiude subito dopo il clic, il salvataggio non arriva. Il server finto annota
# in SALVATAGGI ogni salvataggio ricevuto, con le righe delle sostituzioni della pagina.
SALVATAGGI: list[dict] = []

_SALVA_SUL_SERVER = """<script>
function salvaSulServer() {
  const righe = (c) => [...document.querySelectorAll(`#riepilogo_sostituzioni_${c} > tr`)]
    .map((tr) => [...tr.querySelectorAll('select')].map((s) => s.selectedOptions[0]?.dataset.numero || s.value))
    .filter((r) => r[2] && r[2] !== '0');
  fetch('save.asp', {method: 'POST', body: JSON.stringify({pagina: location.pathname.split('/').pop(),
                                                           casa: righe('casa'), ospite: righe('fuori')})});
}
</script>"""


def _barra(successivo: str) -> str:
    return _SALVA_SUL_SERVER + f"""<div class="barra"><a href="#">Precedente</a>
      <span><a href="#" title="Salva Scheda" onclick="salvatoScheda = true; return false">Salva Scheda</a>
      <a href="#" title="Salva Tutto" onclick="salvato = true; setTimeout(salvaSulServer, 1500); return false">Salva Tutto</a></span>
      <span><a href="#" title="Invia al G.S." onclick="inviato = true; return false">Invia al G.S.</a>
      <a href="#">Stampa</a></span><a href="{successivo}">Successivo</a></div>"""


def _schede(attiva: str) -> str:
    nomi = ["Svolgimento", "Sicurezza", "Liste Gara", "Durata", "Reti", "Disciplina", "Sostituzioni", "Note"]
    # Come nel portale: ogni scheda è un link "#tabs-..."; qui funziona solo quella delle Sostituzioni.
    return '<div class="tabs">' + "".join(
        f'<a href="#tabs-{n.replace(" ", "")}" class="{"on" if n == attiva else ""}" '
        f'onclick="return mostraScheda(this)">{n}</a>' for n in nomi) + "</div>"


# Scheda Sostituzioni: le tendine ESCE/ENTRA dipendono dalle Liste Gara salvate (qui fisse) e dalle
# righe precedenti, come nel portale. Chi è uscito può rientrare: compare in ENTRA come "* 6 - ...".
TITOLARI_SOST = {"casa": list(range(1, 12)), "ospite": [1, 2, 3, 4, 5, 6, 7, 8, 9, 13, 14]}
RISERVE_SOST = {"casa": list(range(12, 19)), "ospite": [15, 16, 17, 18, 10, 11]}


def _tabella_sostituzioni(lato: str, corpo: str) -> str:
    riga = """<tr><td><button class="delsostituzione">x</button></td>
      <td>TEMPO <select name="tempo"><option value="0"></option><option value="1">1 Tempo</option>
        <option value="2">2 Tempo</option></select></td>
      <td>MINUTO <select name="minuto"><option value="0"></option>""" + "".join(
        f'<option value="{m}">{m} min.</option>' for m in range(1, 36)) + """</select></td>
      <td>ESCE <select name="esce"></select></td><td>ENTRA <select name="entra"></select></td></tr>"""
    return f"""<table><tbody id="riepilogo_sostituzioni_{corpo}">{riga * 7}</tbody>
      <tfoot><tr><td><button id="btn_addsostituzione_{corpo}">Aggiungi Sostituzione</button></td></tr></tfoot></table>
      <template id="riga_{corpo}">{riga}</template>"""


SOSTITUZIONI = f"""<div id="tabs-Sostituzioni" style="display:none" class="box">
<h2>CALCIO TEZZE</h2>{_tabella_sostituzioni('casa', 'casa')}
<h2>BRENDOLA</h2>{_tabella_sostituzioni('ospite', 'fuori')}</div>
<script>
const TITOLARI = {TITOLARI_SOST}, RISERVE = {RISERVE_SOST}, CORPO = {{casa: 'casa', ospite: 'fuori'}};
function mostraScheda(a) {{
  const scheda = document.getElementById(a.getAttribute('href').slice(1));
  if (scheda) scheda.style.display = 'block';
  return false;
}}
const opzione = (lato, n, rientro) => `<option value="${{lato === 'casa' ? 1000 + n : 2000 + n}}" data-numero="${{n}}">` +
  `${{rientro ? '* ' : ''}}${{n}} - GIOCATORE ${{n}}</option>`;
function aggiorna(lato) {{
  let campo = [...TITOLARI[lato]], panchina = [...RISERVE[lato]], usciti = [];
  for (const tr of document.querySelectorAll(`#riepilogo_sostituzioni_${{CORPO[lato]}} > tr`)) {{
    const esce = tr.querySelector('[name=esce]'), entra = tr.querySelector('[name=entra]');
    const prima = [esce.value, entra.value];
    esce.innerHTML = '<option value="0"></option>' + campo.map((n) => opzione(lato, n)).join('');
    entra.innerHTML = '<option value="0"></option>' + panchina.map((n) => opzione(lato, n)).join('')
                      + usciti.map((n) => opzione(lato, n, true)).join('');
    esce.value = [...esce.options].some((o) => o.value === prima[0]) ? prima[0] : '0';
    entra.value = [...entra.options].some((o) => o.value === prima[1]) ? prima[1] : '0';
    const e = Number(esce.selectedOptions[0].dataset.numero || 0), n = Number(entra.selectedOptions[0].dataset.numero || 0);
    tr.firstElementChild.style.borderLeft = e && n ? '3px solid rgb(0, 255, 0)' : '3px solid rgb(255, 0, 0)';
    if (e && n) {{
      campo = campo.filter((x) => x !== e).concat([n]);
      panchina = panchina.filter((x) => x !== n);
      usciti = usciti.filter((x) => x !== n).concat([e]);
    }}
  }}
}}
for (const lato of ['casa', 'ospite']) {{
  const corpo = document.getElementById('riepilogo_sostituzioni_' + CORPO[lato]);
  corpo.addEventListener('change', () => aggiorna(lato));
  document.getElementById('btn_addsostituzione_' + CORPO[lato]).addEventListener('click', () => {{
    if (corpo.children.length >= 7 && !confirm('ATTENZIONE! per questa categoria sono previste: 7 Sostituzioni al massimo.')) return;
    corpo.append(document.getElementById('riga_' + CORPO[lato]).content.cloneNode(true));
    aggiorna(lato);
  }});
  aggiorna(lato);
}}
// Una sostituzione rimasta da una prova precedente, da togliere.
(() => {{
  const tr = document.querySelector('#riepilogo_sostituzioni_casa > tr');
  tr.querySelector('[name=tempo]').value = '1'; tr.querySelector('[name=minuto]').value = '3';
  tr.querySelector('[name=esce]').value = '1002'; aggiorna('casa');
  tr.querySelector('[name=entra]').value = '1012'; aggiorna('casa');
}})();
</script>"""


_SVUOTA = ("onfocus=\"if(this.value==this.defaultValue){this.value='';}\" "
           "onblur=\"if(this.value==''){this.value=this.defaultValue;}\"")

LOGIN = f"""<div class="box"><div class="titolo">Credenziali di Accesso</div>
<form method="POST" action="default.asp?action=accesso_sistema">
UTENTE <input type="text" name="username" id="username" value="USERNAME" {_SVUOTA}><br>
PASSWORD <input type="password" name="password" id="password" value="PASSWORD" {_SVUOTA}><br>
<input type="submit" value="ACCEDI AL SISTEMA"></form></div>
<!-- Finestra modale come quella di jQuery UI: copre la pagina finché non si preme Ok -->
<div id="velo" style="position:fixed;inset:0;background:#0006"></div>
<div class="ui-dialog" style="position:fixed;top:120px;left:300px;width:500px;background:#fff;padding:10px">
  <div class="titolo">Benvenuto in Sinfonia4You</div><p>Per accedere ed operare sul sistema digita…</p>
  <div class="ui-dialog-buttonpane"><button type="button"
    onclick="document.getElementById('velo').remove(); this.closest('.ui-dialog').remove()">Ok</button></div>
</div>"""

# Il menu "Gestione Gare" è chiuso: "Gestione Referti" non si vede finché non lo si apre.
HOME = """<div class="box"><div class="titolo">Benvenuto su Sinfonia4You</div>
<a href="#" onclick="document.getElementById('sotto').style.display='block'; return false">Gestione Gare</a>
<div id="sotto" style="display:none"><a href="area_utenti/area_tecnica/gestione_referti/default.asp">Gestione Referti</a></div>
</div>"""

_ICONA = '<img src="{}" width="16" height="16">'
GARE = f"""<div class="box"><div class="titolo">Gestione Referti</div>
<table width="100%"><tr><th>Data</th><th>Gara</th><th>Azioni</th></tr>
<tr><td>11/10/2026</td><td>SAN GIOVANNI ILARIONE<br>SAREGO LIONA ACADEMY</td>
    <td><a href="dettaglio.asp"><img src="/img/info.png" width="16" height="16"></a>
        <a href="nuovo_inserimento/default.asp">{_ICONA.format('/img/ico_add.png')}</a></td></tr>
<tr><td>31/10/2026</td><td>CALCIO TEZZE<br>BRENDOLA</td>
    <td><img src="/img/ico_verde_32.png" width="16" height="16" style="cursor:pointer"
         onclick="location.href='nuovo_inserimento/default.asp'"></td></tr>
<tr><td>17/10/2026</td><td>CALCIO TEZZE<br>ALTAVILLA</td>
    <td><a href="dettaglio.asp">{_ICONA.format('/img/info.png')}</a>
        <a href="stampa.asp">{_ICONA.format('/img/pdf.png')}</a></td></tr>
<tr><td>04/10/2026</td><td>MONTECCHIO S.PIETRO<br>SAN VITALE 1995</td>
    <td><a href="dettaglio.asp">{_ICONA.format('/img/info.png')}</a>
        <a href="stampa.asp">{_ICONA.format('/img/pdf.png')}</a></td></tr></table></div>"""

SVOLGIMENTO = f"""{_schede('Svolgimento')}<div class="box"><div class="titolo">Svolgimento della Gara</div>
{_scegli('Disputata Regolarmente')}{_scegli('Disputata Con Sospensioni')}{_scegli('Sospesa')}</div>
{SOSTITUZIONI}
<script>let salvato = false, salvatoScheda = false, inviato = false;</script>
{_barra('sicurezza.asp')}"""

SICUREZZA = f"""{_schede('Sicurezza')}<div class="box"><div class="titolo">Misure d'Ordine</div>
{_scegli('Adeguate con Forza Pubblica')}{_scegli('Adeguate senza Forza Pubblica')}
{_scegli('Inadeguate con Forza Pubblica')}</div>
<div class="box"><div class="titolo">Ambulanza</div>{_scegli('Presente')}{_scegli('NON Presente')}</div>
{_barra('liste.asp')}"""

ARCHIVIO = [
    "ROSSI MARIO (01/01/2000 - ID 111)",
    "ROSSI MARIO (01/01/2000 - ID 222)",
    "BIANCHI LUCA (02/02/2001 - ID 333)",
    "DAL CERO ALESSANDRO (06/11/2004 - ID 444)",
    "VERDI ANNA (03/03/2003 - ID 555)",
    "ANDREOLLI NICOLÒ (04/04/2009 - ID 666)",
]


def _colonna(lato: str) -> str:
    opzioni = "<option></option>" + "".join(f"<option>{o}</option>" for o in ARCHIVIO)
    numeri = "".join(f"<option>{n}</option>" for n in range(1, 41))

    def riga(n: int) -> str:
        return f"""<div class="riga"><select style="width:45px"><option>{n}</option>{numeri}</select>
          <select class="gioc {lato}" style="width:330px">{opzioni}</select>
          <select style="width:45px"><option></option><option>C</option><option>V</option></select></div>
          <div><select style="width:150px"><option>Carta d'identità</option><option>Passaporto</option></select>
          <input placeholder="Inserisci Numero Documento"></div>"""

    return (f"""<div class="titolo">{'S.LAZZARO SERENISSIMA' if lato == 'casa' else 'CA 30 CALCIO'}</div>
      <a href="#" onclick="apri('{lato}'); return false">+ AGGIUNGI PERSONA</a>
      <div class="giallo">Lista dei Calciatori Titolari.</div>{''.join(riga(n) for n in range(1, 12))}
      <div class="giallo">Lista dei Calciatori di Riserva.</div>{''.join(riga(n) for n in range(12, 21))}""")


LISTE = f"""{_schede('Liste Gara')}<table style="width:100%"><tr>
<td class="box" style="width:50%;vertical-align:top">{_colonna('casa')}</td>
<td class="box" style="width:50%;vertical-align:top">{_colonna('ospite')}</td></tr></table>
{_barra('durata.asp')}
<div id="dlg" style="display:none;position:fixed;top:150px;left:300px;background:#fff">
  <div class="titolo" style="margin:0 0 8px;background:#f5a623">Aggiungi Tesserato</div>
  <table><tr><td>Matricola:</td><td><input id="m"></td></tr>
  <tr><td>Cognome *:</td><td><input id="c"></td></tr>
  <tr><td>Nome *:</td><td><input id="n"></td></tr>
  <tr><td>Data di Nascita *:</td><td><input id="d"> <input type="checkbox"> Sconosciuta</td></tr></table>
  <button onclick="conferma()">Conferma</button> <button>Annulla</button>
</div>
<script>
let lato = null, nuovi = 900, salvato = false, salvatoScheda = false, inviato = false;
// Come il portale (caso peggiore): lo stesso giocatore non può stare in due righe della stessa squadra.
document.addEventListener('change', (e) => {{
  const s = e.target;
  if (!s.classList.contains('gioc') || !s.value) return;
  const squadra = s.classList.contains('casa') ? 'casa' : 'ospite';
  const doppio = [...document.querySelectorAll('select.gioc.' + squadra)].some((o) => o !== s && o.value === s.value);
  if (doppio) {{ alert('Giocatore già inserito'); s.selectedIndex = 0; }}
}});
function apri(l) {{ lato = l; document.getElementById('dlg').style.display = 'block'; }}
function conferma() {{
  const v = (id) => document.getElementById(id).value;
  const testo = `${{v('c')}} ${{v('n')}} (${{v('d')}} - ID ${{nuovi++}})`;
  document.querySelectorAll('select.gioc.' + lato).forEach((s) => s.add(new Option(testo)));
  // Come una ricarica della pagina: le scelte non ancora salvate si perdono.
  document.querySelectorAll('select').forEach((s) => {{ s.selectedIndex = 0; }});
  ['c', 'n', 'd'].forEach((id) => document.getElementById(id).value = '');
  document.getElementById('dlg').style.display = 'none';
}}
</script>"""

_REFERTI = "area_utenti/area_tecnica/gestione_referti/"
PAGINE = {
    "": LOGIN, "default.asp?action=accesso_sistema": HOME, _REFERTI + "default.asp": GARE,
    _REFERTI + "nuovo_inserimento/default.asp": SVOLGIMENTO, _REFERTI + "nuovo_inserimento/sicurezza.asp": SICUREZZA,
    _REFERTI + "nuovo_inserimento/liste.asp": LISTE,
}


def installa(page: Page, captcha: bool = False) -> None:
    def gestisci(route: Route) -> None:
        percorso = route.request.url.removeprefix(BASE)
        if percorso.endswith("save.asp") and route.request.method == "POST":
            SALVATAGGI.append(json.loads(route.request.post_data or "{}"))
            return route.fulfill(body="OK", content_type="text/plain")
        if captcha and percorso == "":
            campo = '<input type="text" name="captcha" class="validate[required,custom[S4YCaptcha]]">'
            return route.fulfill(body=f"<html><body>{LOGIN.replace('</form>', campo + '</form>')}</body></html>",
                                 content_type="text/html")
        if route.request.method == "POST" and percorso.startswith("default.asp"):
            if "password=segreta" not in (route.request.post_data or ""):
                return route.fulfill(body=LOGIN, content_type="text/html")
        corpo = PAGINE.get(percorso)
        if corpo is None:
            return route.fulfill(status=404, body="non trovata")
        html = f"""<html><head><meta charset="utf-8">{STILE}</head><body><div class="pagina">
          <div class="testata">ASSOCIAZIONE ITALIANA ARBITRI — Sinfonia4You (COPIA DI PROVA)</div>{corpo}</div></body></html>"""
        route.fulfill(body=html, content_type="text/html")

    page.route(BASE + "**", gestisci)
