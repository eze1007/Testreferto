"""Copia semplificata delle pagine di Sinfonia4You, ricostruita dagli screenshot (dati inventati)."""

from playwright.sync_api import Page, Route

BASE = "https://servizi.aia-figc.it/sinfonia4you/"

LOGIN = """<form method="POST" action="default.asp?action=accesso_sistema">
<input type="text" name="username" id="username" value="USERNAME">
<input type="password" name="password" id="password" value="PASSWORD">
<input type="submit" value="ACCEDI AL SISTEMA"></form>"""

HOME = """<h1>Benvenuto su Sinfonia4You</h1><a href="gestione_referti.asp">Gestione Referti</a>"""

GARE = """<table><tr><th>Data</th><th>Gara</th><th>Azioni</th></tr>
<tr><td>11/10/2026</td><td>SAN GIOVANNI ILARIONE<br>SAREGO LIONA ACADEMY</td>
    <td><a href="svolgimento.asp"><img alt="+" width="16" height="16"></a></td></tr>
<tr><td>04/10/2026</td><td>MONTECCHIO S.PIETRO<br>SAN VITALE 1995</td>
    <td><a href="altra.asp"><img alt="+" width="16" height="16"></a></td></tr></table>"""

SVOLGIMENTO = """<div><a href="#" onclick="this.className='scelto'">Disputata Regolarmente</a></div>
<div><a href="#">Sospesa</a></div><a href="sicurezza.asp" title="Prosegui"><img alt="Prosegui"></a>"""

SICUREZZA = """<a href="#">Adeguate con Forza Pubblica</a> <a href="#">Adeguate senza Forza Pubblica</a>
<a href="#">Presente</a> <a href="#">NON Presente</a><a href="liste.asp" title="Prosegui"><img alt="Prosegui"></a>"""

ARCHIVIO = [
    "ROSSI MARIO (01/01/2000 - ID 111)",
    "ROSSI MARIO (01/01/2000 - ID 222)",
    "BIANCHI LUCA (02/02/2001 - ID 333)",
    "DAL CERO ALESSANDRO (06/11/2004 - ID 444)",
    "VERDI ANNA (03/03/2003 - ID 555)",
]


def _colonna(lato: str) -> str:
    opzioni = "<option></option>" + "".join(f"<option>{o}</option>" for o in ARCHIVIO)
    numeri = "".join(f"<option>{n}</option>" for n in range(1, 41))

    def riga(n: int) -> str:
        return f"""<div class="riga"><select style="width:40px"><option>{n}</option>{numeri}</select>
          <select class="gioc {lato}" style="width:300px">{opzioni}</select>
          <select style="width:50px"><option></option><option>C</option><option>V</option></select></div>
          <div><select style="width:150px"><option>Carta d'identità</option><option>Passaporto</option></select>
          <input placeholder="Inserisci Numero Documento"></div>"""

    return (f"""<h2>{'S.LAZZARO SERENISSIMA' if lato == 'casa' else 'CA 30 CALCIO'}</h2>
      <a href="#" onclick="apri('{lato}')">AGGIUNGI PERSONA</a>
      <div>Lista dei Calciatori Titolari.</div>{''.join(riga(n) for n in range(1, 12))}
      <div>Lista dei Calciatori Riserve.</div>{''.join(riga(n) for n in range(12, 21))}""")


LISTE = f"""<table style="width:1000px"><tr>
<td style="width:500px;vertical-align:top">{_colonna('casa')}</td>
<td style="width:500px;vertical-align:top">{_colonna('ospite')}</td></tr></table>
<div id="dlg" style="display:none;position:absolute;top:100px;left:200px;background:#fff">
  <div>Aggiungi Tesserato</div>
  <table><tr><td>Matricola:</td><td><input id="m"></td></tr>
  <tr><td>Cognome *:</td><td><input id="c"></td></tr>
  <tr><td>Nome *:</td><td><input id="n"></td></tr>
  <tr><td>Data di Nascita *:</td><td><input id="d"> <input type="checkbox"> Sconosciuta</td></tr></table>
  <button onclick="conferma()">Conferma</button> <button>Annulla</button>
</div>
<script>
let lato = null, nuovi = 900;
function apri(l) {{ lato = l; document.getElementById('dlg').style.display = 'block'; }}
function conferma() {{
  const v = (id) => document.getElementById(id).value;
  const testo = `${{v('c')}} ${{v('n')}} (${{v('d')}} - ID ${{nuovi++}})`;
  document.querySelectorAll('select.gioc.' + lato).forEach((s) => s.add(new Option(testo)));
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
        route.fulfill(body=f"<html><body>{corpo}</body></html>", content_type="text/html")

    page.route(BASE + "**", gestisci)
