"""Copia semplificata delle pagine di Sinfonia4You, ricostruita dagli screenshot (dati inventati)."""

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


def _barra(successivo: str) -> str:
    return f"""<div class="barra"><a href="#">Precedente</a>
      <span><a href="#" title="Salva Scheda" onclick="salvatoScheda = true; return false">Salva Scheda</a>
      <a href="#" title="Salva Tutto" onclick="salvato = true; return false">Salva Tutto</a></span>
      <span><a href="#" title="Invia al G.S." onclick="inviato = true; return false">Invia al G.S.</a>
      <a href="#">Stampa</a></span><a href="{successivo}">Successivo</a></div>"""


def _schede(attiva: str) -> str:
    nomi = ["Svolgimento", "Sicurezza", "Liste Gara", "Durata", "Reti", "Disciplina", "Sostituzioni", "Note"]
    return '<div class="tabs">' + "".join(
        f'<a class="{"on" if n == attiva else ""}">{n}</a>' for n in nomi) + "</div>"


LOGIN = """<div class="box"><div class="titolo">Credenziali di Accesso</div>
<form method="POST" action="default.asp?action=accesso_sistema">
UTENTE <input type="text" name="username" id="username" value="USERNAME"><br>
PASSWORD <input type="password" name="password" id="password" value="PASSWORD"><br>
<input type="submit" value="ACCEDI AL SISTEMA"></form></div>"""

HOME = """<div class="box"><div class="titolo">Benvenuto su Sinfonia4You</div>
<a href="gestione_referti.asp">Gestione Referti</a></div>"""

GARE = """<div class="box"><div class="titolo">Referti Da Compilare</div>
<table width="100%"><tr><th>Data</th><th>Gara</th><th>Azioni</th></tr>
<tr><td>11/10/2026</td><td>SAN GIOVANNI ILARIONE<br>SAREGO LIONA ACADEMY</td>
    <td><a href="svolgimento.asp"><img alt="+" width="16" height="16"></a></td></tr>
<tr><td>04/10/2026</td><td>MONTECCHIO S.PIETRO<br>SAN VITALE 1995</td>
    <td><a href="altra.asp"><img alt="+" width="16" height="16"></a></td></tr></table></div>"""

SVOLGIMENTO = f"""{_schede('Svolgimento')}<div class="box"><div class="titolo">Svolgimento della Gara</div>
{_scegli('Disputata Regolarmente')}{_scegli('Disputata Con Sospensioni')}{_scegli('Sospesa')}</div>
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
      <div class="giallo">Lista dei Calciatori Riserve.</div>{''.join(riga(n) for n in range(12, 21))}""")


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
function apri(l) {{ lato = l; document.getElementById('dlg').style.display = 'block'; }}
function conferma() {{
  const v = (id) => document.getElementById(id).value;
  const testo = `${{v('c')}} ${{v('n')}} (${{v('d')}} - ID ${{nuovi++}})`;
  document.querySelectorAll('select.gioc.' + lato).forEach((s) => s.add(new Option(testo)));
  ['c', 'n', 'd'].forEach((id) => document.getElementById(id).value = '');
  document.getElementById('dlg').style.display = 'none';
}}
</script>"""

PAGINE = {
    "": LOGIN, "default.asp?action=accesso_sistema": HOME, "gestione_referti.asp": GARE,
    "svolgimento.asp": SVOLGIMENTO, "sicurezza.asp": SICUREZZA, "liste.asp": LISTE,
}


def installa(page: Page) -> None:
    def gestisci(route: Route) -> None:
        percorso = route.request.url.removeprefix(BASE)
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
