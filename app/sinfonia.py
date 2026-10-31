"""Compilazione delle Liste Gara su Sinfonia4You con Playwright.

Percorso: login -> Gestione Referti -> "+" sulla gara -> Svolgimento "Disputata Regolarmente"
-> Successivo -> Sicurezza "Adeguate senza Forza Pubblica" + Ambulanza "NON Presente"
-> Successivo -> Liste Gara.
Per ogni calciatore si imposta il numero e si sceglie il nominativo dalla tendina solo se cognome,
nome e data di nascita coincidono (non contano accenti, apostrofi, spazi e ordine; a parità si
prende il primo); altrimenti lo si crea
con "Aggiungi persona". Documenti e capitano non vengono toccati. Alla fine si preme
"Salva Tutto"; "Invia al G.S." non viene mai premuto.
"""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Locator, Page

from .schema import Giocatore

URL = "https://servizi.aia-figc.it/sinfonia4you/"
URL_REFERTI = URL + "area_utenti/area_tecnica/gestione_referti/default.asp"
TIMEOUT_MS = 20_000

# "COGNOME NOME (GG/MM/AAAA - ID 1234567)"
RE_OPZIONE = re.compile(r"^(?P<nome>.+?)\s*\((?P<data>\d{2}/\d{2}/\d{4})\s*-\s*ID\s*\d+\)\s*$")


def compatta(testo: str) -> str:
    """Solo le lettere, in maiuscolo e senza accenti: NICOLO' = NICOLÒ, D'ANGELO = D ANGELO = DANGELO."""
    senza_accenti = "".join(c for c in unicodedata.normalize("NFKD", testo) if not unicodedata.combining(c))
    return "".join(c for c in senza_accenti.upper() if c.isalpha())


@dataclass
class Scelta:
    stato: str  # "trovato", "nuovo", "da_verificare"
    indice: int | None = None
    motivo: str = ""


def scegli_opzione(g: Giocatore, opzioni: list[str]) -> Scelta:
    """Trova il calciatore tra le voci della tendina.

    Data di nascita e lettere di cognome e nome devono coincidere; non contano maiuscole, spazi,
    accenti, apostrofi e l'ordine (COGNOME NOME o NOME COGNOME). Una lettera diversa o mancante
    vuol dire un altro giocatore.
    """
    if not g.data_nascita:
        return Scelta("da_verificare", motivo="data di nascita mancante: impossibile cercarlo o crearlo")
    cercati = {compatta(g.cognome + g.nome), compatta(g.nome + g.cognome)}
    for i, testo in enumerate(opzioni):
        m = RE_OPZIONE.match(testo.strip())
        if m and compatta(m["nome"]) in cercati and m["data"] == g.data_nascita:
            return Scelta("trovato", i)  # il primo, anche se ci sono doppioni
    return Scelta("nuovo")


@dataclass
class Esito:
    giocatore: Giocatore
    stato: str  # "selezionato", "aggiunto", "da_verificare", "errore"
    dettaglio: str = ""


@dataclass
class Riga:
    numero: str  # selettore CSS della tendina del numero
    giocatore: str  # selettore CSS della tendina del nominativo


@dataclass
class Report:
    esiti: list[Esito] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)


# Parole che si scrivono tra i nomi delle squadre ma non compaiono nella lista gare.
PAROLE_IGNORATE = {"VS", "V", "CONTRO", "E", "CON", "GARA", "PARTITA", "DI", "DEL", "LA", "IL"}


def parole_gara(testo: str) -> list[str]:
    return [p for p in re.sub(r"[^A-Z0-9]+", " ", testo.upper()).split() if p not in PAROLE_IGNORATE]


def corrisponde(cercate: list[str], testo_riga: str) -> bool:
    """Ogni parola cercata deve essere l'inizio di una parola della riga: "TEZZE" trova
    "CALCIO TEZZE", "BRENDOL" trova "BRENDOLA"."""
    parole_riga = re.sub(r"[^A-Z0-9]+", " ", testo_riga.upper()).split()
    return all(any(p.startswith(c) for p in parole_riga) for c in cercate)


class Sinfonia:
    def __init__(self, page: Page, cartella_debug: Path | None = None):
        self.page = page
        self.page.set_default_timeout(TIMEOUT_MS)
        self.cartella_debug = cartella_debug
        self._passo = 0

    # --- utilità -------------------------------------------------------------------------

    def istantanea(self, nome: str) -> None:
        """Salva screenshot e HTML della pagina (per capire cosa è andato storto)."""
        if not self.cartella_debug:
            return
        self.cartella_debug.mkdir(parents=True, exist_ok=True)
        self._passo += 1
        base = self.cartella_debug / f"{self._passo:02d}-{nome}"
        self.page.screenshot(path=f"{base}.png", full_page=True)
        Path(f"{base}.html").write_text(self.page.content(), encoding="utf-8")

    def _clicca_testo(self, testo: str) -> None:
        self.page.get_by_text(testo, exact=True).first.click()
        self.page.wait_for_load_state()
        self.chiudi_finestre(500)

    def _clicca_bottone(self, parola: str) -> str:
        """Clicca il primo bottone/link/icona il cui testo, title, alt o value contiene `parola`.

        Restituisce l'etichetta cliccata. Esclude sempre l'invio del referto ("Invia al G.S.").
        """
        etichetta = """(el) => [...new Set([el.innerText, el.title, el.alt, el.value, el.getAttribute('aria-label'),
                                ...[...el.querySelectorAll('img')].flatMap((i) => [i.alt, i.title])]
                               .map((t) => (t || '').trim()).filter(Boolean))].join(' ')"""
        elementi = self.page.locator("a:visible, button:visible, input:visible, img:visible")
        for i in range(elementi.count()):
            el = elementi.nth(i)
            testo = el.evaluate(etichetta)
            if parola in testo.lower() and not re.search(r"invi|definitiv", testo, re.I):
                el.click()
                self.page.wait_for_load_state()
                return testo
        raise RuntimeError(f"Bottone '{parola}' non trovato")

    def _successivo(self) -> None:
        self._clicca_bottone("successivo")

    def salva(self) -> str:
        """Preme "Salva Tutto" (mai "Invia al G.S.")."""
        self.istantanea("prima-del-salvataggio")
        etichetta = self._clicca_bottone("salva tutto")
        self.istantanea("dopo-il-salvataggio")
        return etichetta

    # --- navigazione ---------------------------------------------------------------------

    def chiudi_finestre(self, attesa_ms: int = 3000) -> None:
        """Chiude le finestre modali del portale (es. "Benvenuto in Sinfonia4You") premendo Ok.

        Finché sono aperte coprono la pagina e bloccano ogni clic.
        """
        bottone = self.page.locator(".ui-dialog:visible .ui-dialog-buttonpane button").filter(
            has_text=re.compile(r"^\s*(ok|chiudi)\s*$", re.I))
        try:
            bottone.first.wait_for(state="visible", timeout=attesa_ms)
        except Exception:
            return  # nessuna finestra
        while bottone.count():
            bottone.first.click()
            self.page.wait_for_timeout(300)

    def _scrivi(self, selettore: str, valore: str) -> None:
        campo = self.page.locator(selettore)
        campo.click()  # il clic cancella il testo di esempio (USERNAME / PASSWORD)
        campo.fill(valore)
        if campo.input_value() != valore:
            campo.fill("")
            campo.press_sequentially(valore, delay=30)

    def login(self, utente: str, password: str, attesa_captcha_s: int = 0,
              avviso: Callable[[str], None] = lambda messaggio: None) -> None:
        """Accesso. Se compare un codice di sicurezza e attesa_captcha_s > 0, lo scrive l'arbitro
        nel browser visibile e preme Accedi: il programma aspetta e poi prosegue."""
        self.page.goto(URL)
        self.chiudi_finestre()
        self._scrivi("#username", utente)
        self._scrivi("#password", password)
        captcha = self.page.locator("input[class*='S4YCaptcha']:visible, input[name*='captcha' i]:visible")
        if captcha.count():
            if not attesa_captcha_s:
                self.istantanea("codice-sicurezza")
                raise RuntimeError("Il portale chiede un codice di sicurezza: avvia con BROWSER_VISIBILE=1 e scrivilo tu")
            avviso("Il portale chiede il codice di sicurezza: scrivilo nel browser e premi Accedi al sistema.")
            captcha.first.focus()
            self.page.locator("#password").wait_for(state="detached", timeout=attesa_captcha_s * 1000)
        else:
            self.page.locator("input[type=submit][value*='ACCEDI' i], input[type=submit]").first.click()
            self.page.wait_for_load_state()
        if self.page.locator("#password").count():
            self.istantanea("login-fallito")
            errore = " ".join(self.page.locator(".formError:visible").all_inner_texts()).strip()
            raise RuntimeError("Login non riuscito: controlla utente e password" + (f" ({errore})" if errore else ""))
        self.chiudi_finestre(1500)  # eventuali avvisi dopo l'accesso

    def _vai_a_gestione_referti(self) -> None:
        # "Gestione Referti" sta nel menu "Gestione Gare", chiuso: si apre direttamente la pagina.
        self.page.goto(URL_REFERTI)
        self.page.wait_for_load_state()
        self.chiudi_finestre(500)
        if self.page.get_by_text(re.compile("Referti Da Compilare|Gestione Referti", re.I)).count():
            return
        # Ripiego: dalla home, apri il menu e clicca la voce.
        self.page.goto(URL)
        self.chiudi_finestre(500)
        self.page.get_by_text("Gestione Gare", exact=True).first.click()
        self._clicca_testo("Gestione Referti")

    @staticmethod
    def _tipo_icona(descrizione: str) -> str:
        d = descrizione.lower()
        if re.search(r"nuovo_inserimento|aggiung|[^a-z]add|plus|nuov|inserisc|(^|\s)\+(\s|$)", d):
            return "nuovo"
        if re.search(r"modific|edit|matita|pencil", d):
            return "modifica"
        if re.search(r"pdf|stampa|print", d):
            return "pdf"
        if re.search(r"info|dettagl|visualizz", d):
            return "info"
        if re.search(r"mail|invia|busta|g\.s", d):
            return "invio"
        return "?"

    def _icona_da_premere(self, riga: Locator) -> Locator | None:
        """Nella riga: il "+" (nuovo referto) o la matita (referto già iniziato); mai "i", PDF o invio."""
        icone = riga.locator("a:visible, input[type=image]:visible")
        tipi = {}
        for i in range(icone.count()):
            descrizione = icone.nth(i).evaluate(
                """(el) => [el.getAttribute('href'), el.getAttribute('onclick'), el.title, el.alt, el.src,
                            ...[...el.querySelectorAll('img')].flatMap((m) => [m.src, m.alt, m.title])]
                           .filter(Boolean).join(' ')""")
            tipi.setdefault(self._tipo_icona(descrizione), icone.nth(i))
        return tipi.get("nuovo") or tipi.get("modifica")

    def apri_gara(self, gara: str) -> None:
        """Apre la gara indicata con una o più parole dei nomi delle squadre (es. "Tezze",
        "Tezze vs Brendola", "brendol"). Se ne corrispondono più di una, sceglie quella da refertare."""
        self._vai_a_gestione_referti()
        cercate = parole_gara(gara)
        if not cercate:
            raise RuntimeError("Scrivi almeno il nome di una squadra")
        righe = self.page.locator("tr:not(:has(tr))")
        trovate = []
        for i in range(righe.count()):
            riga = righe.nth(i)
            testo = riga.inner_text()
            if corrisponde(cercate, testo):
                trovate.append((riga, " - ".join(r.strip() for r in testo.splitlines() if r.strip())))
        if not trovate:
            self.istantanea("lista-gare")
            raise RuntimeError(f"Nessuna gara trovata con '{gara}': controlla il nome della squadra")
        da_refertare = [(r, t, icona) for r, t in trovate if (icona := self._icona_da_premere(r)) is not None]
        if not da_refertare:
            self.istantanea("lista-gare")
            raise RuntimeError(f"La gara '{gara}' non ha il '+' né la matita: è già refertata o non modificabile")
        if len(da_refertare) > 1:
            self.istantanea("lista-gare")
            elenco = "; ".join(t for _, t, _ in da_refertare[:4])
            raise RuntimeError(f"Più gare da refertare con '{gara}': {elenco}. Aggiungi il nome dell'altra squadra")
        da_refertare[0][2].click()
        self.page.wait_for_load_state()
        self.chiudi_finestre(500)
        self.istantanea("gara-aperta")

    def svolgimento_e_sicurezza(self) -> None:
        self._clicca_testo("Disputata Regolarmente")
        self._successivo()
        self._clicca_testo("Adeguate senza Forza Pubblica")
        self._clicca_testo("NON Presente")
        self._successivo()
        self.page.get_by_text(re.compile("Lista dei Calciatori Titolari", re.I)).first.wait_for()
        self.istantanea("liste-gara")

    # --- liste gara ----------------------------------------------------------------------

    def _righe(self, lato: str) -> tuple[list[Riga], list[Riga]]:
        """Individua le righe (titolari, riserve) di una squadra in base alla posizione.

        Ogni riga ha tre tendine sulla stessa altezza: numero, nominativo (la più larga),
        capitano. Le tendine del tipo documento stanno su una linea a parte e si escludono.
        La colonna di sinistra è la squadra di casa, quella di destra l'ospite.
        """
        dati = self.page.evaluate(
            """() => {
              const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
              const selects = [...document.querySelectorAll('select')].filter(vis);
              selects.forEach((s, i) => s.setAttribute('data-s4y', i));
              const intestazioni = [...document.querySelectorAll('body *')]
                .filter((el) => vis(el) && el.children.length === 0 &&
                        /Lista dei Calciatori (Titolari|Riserve)/i.test(el.textContent))
                .map((el) => { const r = el.getBoundingClientRect();
                  return {tipo: /Riserve/i.test(el.textContent) ? 'riserve' : 'titolari',
                          x: r.left + scrollX, y: r.top + scrollY}; });
              return {
                intestazioni,
                selects: selects.map((s, i) => { const r = s.getBoundingClientRect();
                  return {i, x: r.left + scrollX, y: r.top + scrollY, w: r.width,
                          documento: [...s.options].some((o) => /identit|passaporto|patente/i.test(o.text))}; }),
              };
            }"""
        )
        selects = [s for s in dati["selects"] if not s["documento"]]
        if not selects:
            raise RuntimeError("Nessuna tendina trovata in Liste Gara")
        meta = (min(s["x"] for s in selects) + max(s["x"] + s["w"] for s in selects)) / 2
        a_sinistra = lato == "casa"
        selects = [s for s in selects if (s["x"] < meta) == a_sinistra]

        gruppi: list[list[dict]] = []
        for s in sorted(selects, key=lambda s: (s["y"], s["x"])):
            if gruppi and abs(gruppi[-1][0]["y"] - s["y"]) < 8:
                gruppi[-1].append(s)
            else:
                gruppi.append([s])

        righe = []
        for g in gruppi:
            if len(g) < 2:
                continue
            numero = min(g, key=lambda s: s["x"])
            nominativo = max(g, key=lambda s: s["w"])
            righe.append((g[0]["y"], Riga(f"select[data-s4y='{numero['i']}']", f"select[data-s4y='{nominativo['i']}']")))

        y_riserve = [h["y"] for h in dati["intestazioni"]
                     if h["tipo"] == "riserve" and (h["x"] < meta) == a_sinistra]
        if y_riserve:
            titolari = [r for y, r in righe if y < y_riserve[0]]
            riserve = [r for y, r in righe if y > y_riserve[0]]
        else:
            titolari, riserve = [r for _, r in righe], []
        return titolari, riserve

    def _opzioni(self, selettore: str) -> list[str]:
        return self.page.locator(selettore).evaluate("(s) => [...s.options].map((o) => o.text)")

    def _aggiungi_persona(self, lato: str, g: Giocatore) -> None:
        self.page.get_by_text(re.compile(r"aggiungi persona", re.I)).nth(0 if lato == "casa" else 1).click()
        # Il contenitore più interno che ha titolo, campi e bottone Conferma.
        dialogo = self.page.locator(
            ":is(div, form, table):visible:has-text('Aggiungi Tesserato'):has-text('Conferma'):has(input)"
        ).last
        dialogo.wait_for()

        def campo(etichetta: str) -> Locator:
            return dialogo.locator(
                f"xpath=.//td[starts-with(normalize-space(.), '{etichetta}')]/following-sibling::td[1]//input[not(@type='checkbox')]"
            ).first

        campo("Cognome").fill(g.cognome)
        campo("Nome").fill(g.nome)
        data = campo("Data di Nascita")
        data.clear()
        data.press_sequentially(g.data_nascita or "", delay=50)  # digitata come a mano
        dialogo.get_by_text("Conferma", exact=True).click()
        self.page.get_by_text("Aggiungi Tesserato").first.wait_for(state="hidden")

    def compila_lista(self, giocatori: list[Giocatore], lato: str,
                      al_giocatore: Callable[[Esito], None] | None = None) -> Report:
        report = Report()
        titolari, riserve = self._righe(lato)
        unica_sezione = not riserve and any(g.riserva for g in giocatori)
        if unica_sezione:
            # Sezione riserve non distinguibile: le righe proseguono dopo i titolari.
            report.avvisi.append("Sezione riserve non individuata: riserve inserite dopo i titolari.")
            da_inserire = [("titolari", giocatori, len(titolari))]
        else:
            da_inserire = [
                ("titolari", [g for g in giocatori if not g.riserva], len(titolari)),
                ("riserve", [g for g in giocatori if g.riserva], len(riserve)),
            ]

        for sezione, elenco, n_righe in da_inserire:
            if len(elenco) > n_righe:
                report.avvisi.append(f"{sezione}: {len(elenco)} giocatori ma solo {n_righe} righe.")
            for k, g in enumerate(elenco[:n_righe]):
                # La riga si ritrova ogni volta: "Aggiungi persona" potrebbe ricaricare la pagina.
                def riga(sezione=sezione, k=k) -> Riga:
                    t, r = self._righe(lato)
                    return (t if sezione == "titolari" else r)[k]
                esito = self._compila_riga(g, riga, lato)
                report.esiti.append(esito)
                if al_giocatore:
                    al_giocatore(esito)
        self.istantanea(f"compilata-{lato}")
        return report

    def _compila_riga(self, g: Giocatore, riga, lato: str) -> Esito:
        try:
            r = riga()
            if g.numero is not None:
                self.page.select_option(r.numero, label=str(g.numero))
            scelta = scegli_opzione(g, self._opzioni(r.giocatore))
            if scelta.stato == "da_verificare":
                return Esito(g, "da_verificare", scelta.motivo)
            stato = "selezionato"
            if scelta.stato == "nuovo":
                self._aggiungi_persona(lato, g)
                r = riga()
                scelta = scegli_opzione(g, self._opzioni(r.giocatore))
                if scelta.stato != "trovato":
                    return Esito(g, "da_verificare", "aggiunto ma non trovato nella tendina")
                stato = "aggiunto"
            self.page.select_option(r.giocatore, index=scelta.indice)
            return Esito(g, stato)
        except Exception as e:  # una riga sbagliata non deve fermare le altre
            return Esito(g, "errore", str(e).splitlines()[0])
