"""Compilazione delle Liste Gara su Sinfonia4You con Playwright.

Percorso: login -> Gestione Referti -> "+" sulla gara -> Svolgimento "Disputata Regolarmente"
-> Successivo -> Sicurezza "Adeguate senza Forza Pubblica" + Ambulanza "NON Presente"
-> Successivo -> Liste Gara.
Per ogni calciatore si imposta il numero e si sceglie il nominativo dalla tendina solo se cognome,
nome e data di nascita coincidono (non contano accenti, apostrofi, spazi e ordine; a parità si
prende il primo); altrimenti lo si crea
con "Aggiungi persona". Documenti e capitano non vengono toccati. Alla fine si preme
"Salva Tutto"; "Invia al G.S." non viene mai premuto.

Sostituzioni (dal rapportino di fine gara): scheda "Sostituzioni" del referto, riaperto dopo il
salvataggio delle Liste Gara, perché le tendine ESCE/ENTRA si basano sulle liste salvate.
"""

import itertools
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Locator, Page

from .checks import completa, ordine_cronologico
from .schema import Giocatore, Sostituzione

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
class EsitoSostituzione:
    sostituzione: Sostituzione
    stato: str  # "inserita", "errore"
    dettaglio: str = ""


# Scheda Sostituzioni: righe della squadra e bottone "Aggiungi Sostituzione".
TABELLA_SOSTITUZIONI = {"casa": "#riepilogo_sostituzioni_casa", "ospite": "#riepilogo_sostituzioni_fuori"}
AGGIUNGI_SOSTITUZIONE = {"casa": "#btn_addsostituzione_casa", "ospite": "#btn_addsostituzione_fuori"}


@dataclass
class Riga:
    numero: str  # selettore CSS della tendina del numero
    giocatore: str  # selettore CSS della tendina del nominativo


@dataclass
class Report:
    esiti: list[Esito] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)


_contatore = itertools.count()

# Parole che si scrivono tra i nomi delle squadre ma non compaiono nella lista gare.
PAROLE_IGNORATE = {"VS", "V", "CONTRO", "E", "CON", "GARA", "PARTITA", "DI", "DEL", "LA", "IL"}


def parole_gara(testo: str) -> list[str]:
    return [p for p in re.sub(r"[^A-Z0-9]+", " ", testo.upper()).split() if p not in PAROLE_IGNORATE]


def corrisponde(cercate: list[str], testo_riga: str) -> bool:
    """Vale per qualsiasi squadra: ogni parola scritta deve trovarsi nella riga, anche solo come
    inizio di parola ("TEZZE" trova "CALCIO TEZZE", "BRENDOL" trova "BRENDOLA"). Le abbreviazioni
    con il punto valgono per la parola intera: "S.LAZZARO" corrisponde a "SAN LAZZARO"."""
    parole_riga = re.findall(r"[A-Z0-9]+\.?", testo_riga.upper())

    def trovata(c: str) -> bool:
        for p in parole_riga:
            abbreviata = p.endswith(".")
            p = p.rstrip(".")
            if p.startswith(c) or (abbreviata and c.startswith(p)):
                return True
        return False

    return all(trovata(c) for c in cercate)


class Sinfonia:
    def __init__(self, page: Page, cartella_debug: Path | None = None):
        self.page = page
        self.page.set_default_timeout(TIMEOUT_MS)
        self.cartella_debug = cartella_debug
        self._passo = 0
        self._icone_viste: list[str] = []
        # Gli avvisi del portale (es. "giocatore già inserito") vengono annotati e chiusi.
        self.messaggi_portale: list[str] = []
        # Di norma le richieste di conferma si annullano; si accettano solo dove serve
        # (es. "Aggiungi Sostituzione" oltre il massimo della categoria).
        self.accetta_conferme = False
        page.on("dialog", self._dialogo)

    def _dialogo(self, d) -> None:
        if d.type == "beforeunload":  # "lasciare la pagina?": si esce solo dopo aver salvato
            d.accept()
            return
        self.messaggi_portale.append(d.message.strip())
        d.accept() if self.accetta_conferme else d.dismiss()

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
        """Nella cella Azioni (l'ultima della riga): il "+" (nuovo referto) o la matita (referto già
        iniziato); mai "i", PDF o invio. Le icone possono essere link, bottoni o immagini cliccabili:
        se non si riconosce il tipo ma l'icona è l'unica della cella, è il "+" delle gare da refertare."""
        celle = riga.locator("td")
        cella = celle.last if celle.count() else riga
        segno = f"i{next(_contatore)}"
        descrizioni = cella.evaluate(
            """(cella, segno) => {
                const visibile = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
                const tutti = [...cella.querySelectorAll('a, button, input[type=image], img, [onclick]')].filter(visibile);
                const icone = tutti.filter((el) => !tutti.some((altro) => altro !== el && altro.contains(el)));
                return icone.map((el, i) => {
                    el.setAttribute('data-s4y-icona', segno + '-' + i);
                    return [el.getAttribute('href'), el.getAttribute('onclick'), el.title, el.alt, el.src, el.className,
                            ...[...el.querySelectorAll('img')].flatMap((m) => [m.src, m.alt, m.title])]
                           .filter(Boolean).join(' ');
                });
            }""", segno)
        self._icone_viste = descrizioni
        tipi = [self._tipo_icona(d) for d in descrizioni]
        icona = lambda i: cella.locator(f"[data-s4y-icona='{segno}-{i}']")
        for voluto in ("nuovo", "modifica"):
            if voluto in tipi:
                return icona(tipi.index(voluto))
        if len(tipi) == 1 and tipi[0] == "?":
            return icona(0)
        return None

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
            icone = " | ".join(self._icone_viste) or "nessuna"
            raise RuntimeError(f"La gara '{gara}' non ha il '+' né la matita: è già refertata o non modificabile "
                               f"(icone viste nell'ultima riga: {icone[:300]})")
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
        """Crea il tesserato con la finestra "Aggiungi Tesserato": cognome, nome, data di nascita."""
        bottoni = [b for b in self.page.get_by_text(re.compile(r"aggiungi\s+persona", re.I)).all() if b.is_visible()]
        if not bottoni:
            raise RuntimeError("Bottone 'Aggiungi persona' non trovato")
        bottoni.sort(key=lambda b: (b.bounding_box() or {"x": 0})["x"])  # sinistra = casa, destra = ospite
        (bottoni[0] if lato == "casa" else bottoni[-1]).click()

        titolo = self.page.get_by_text(re.compile(r"aggiungi\s+tesserato", re.I))
        try:
            titolo.first.wait_for(state="visible", timeout=10_000)
        except Exception:
            self.istantanea("aggiungi-persona-non-aperta")
            raise RuntimeError("La finestra 'Aggiungi Tesserato' non si è aperta")
        # Il contenitore più interno che ha titolo, campi e bottone Conferma.
        dialogo = self.page.locator(
            ":is(div, form, table):visible:has-text('Tesserato'):has-text('Conferma'):has(input)").last

        def campo(etichetta: str, nome_campo: str) -> Locator:
            esclusi = "not(@type='checkbox') and not(@type='hidden') and not(@type='button') and not(@type='submit')"
            candidati = [
                # etichetta in una cella, campo nella cella accanto
                f"xpath=.//td[starts-with(normalize-space(.), '{etichetta}')]/following-sibling::td[1]//input[{esclusi}]",
                # etichetta in qualsiasi elemento (label, th, span, div...), primo campo che la segue
                f"xpath=.//*[starts-with(normalize-space(text()), '{etichetta}')]/following::input[{esclusi}][1]",
            ]
            for c in candidati:
                loc = dialogo.locator(c).first
                if loc.count() and loc.is_visible():
                    return loc
            per_nome = dialogo.locator(f"input[name*='{nome_campo}' i], input[id*='{nome_campo}' i]")
            if nome_campo == "nome":
                per_nome = dialogo.locator("input[name*='nome' i]:not([name*='cognome' i]), "
                                           "input[id*='nome' i]:not([id*='cognome' i])")
            return per_nome.first

        try:
            campo("Cognome", "cognome").fill(g.cognome)
            campo("Nome", "nome").fill(g.nome)
            data = campo("Data di Nascita", "nascita")
            data.click()
            data.fill("")
            data.press_sequentially(g.data_nascita or "", delay=50)  # digitata come a mano
            data.press("Tab")  # chiude l'eventuale calendario, che coprirebbe il bottone Conferma
            dialogo.locator("button, input[type=button], input[type=submit], a").filter(
                has_text=re.compile(r"^\s*conferma\s*$", re.I)).first.click()
            titolo.first.wait_for(state="hidden", timeout=15_000)
        except Exception as e:
            self.istantanea(f"aggiungi-persona-{g.cognome}")
            errori = " ".join(t.strip() for t in dialogo.locator(".formError:visible, .ui-state-error:visible")
                              .all_inner_texts() if t.strip()) if dialogo.count() else ""
            raise RuntimeError(f"Aggiungi persona non riuscito{f' ({errori})' if errori else ''}: "
                               f"{str(e).splitlines()[0][:150]}")
        self.page.wait_for_load_state()
        self.chiudi_finestre(500)

    def _assegnazioni(self, giocatori: list[Giocatore], lato: str) -> tuple[list[tuple[Giocatore, Callable[[], Riga]]], list[str]]:
        """Abbina ogni giocatore alla sua riga del portale: i titolari alle righe dei titolari, le
        riserve a quelle delle riserve, nell'ordine della lista. La riga si ritrova ogni volta che
        serve, perché il portale potrebbe ricaricare la pagina."""
        titolari, riserve = self._righe(lato)
        avvisi = []
        if not riserve and any(g.riserva for g in giocatori):
            avvisi.append("Sezione riserve non individuata: riserve inserite dopo i titolari.")
            gruppi = [("titolari", giocatori, len(titolari))]
        else:
            gruppi = [("titolari", [g for g in giocatori if not g.riserva], len(titolari)),
                      ("riserve", [g for g in giocatori if g.riserva], len(riserve))]
        abbinati = []
        for sezione, elenco, n_righe in gruppi:
            if len(elenco) > n_righe:
                fuori = ", ".join(f"{g.cognome} {g.nome}" for g in elenco[n_righe:])
                avvisi.append(f"{sezione}: {len(elenco)} giocatori ma solo {n_righe} righe; non inseriti: {fuori}.")
            for k, g in enumerate(elenco[:n_righe]):
                def riga(sezione=sezione, k=k) -> Riga:
                    t, r = self._righe(lato)
                    return (t if sezione == "titolari" else r)[k]
                abbinati.append((g, riga))
            for k in range(len(elenco), n_righe):  # righe in più: vanno lasciate vuote
                def riga(sezione=sezione, k=k) -> Riga:
                    t, r = self._righe(lato)
                    return (t if sezione == "titolari" else r)[k]
                abbinati.append((None, riga))
        return abbinati, avvisi

    def _svuota(self, selettore: str) -> None:
        """Riporta la tendina del nominativo sulla voce vuota (toglie dati rimasti da prove precedenti)."""
        vuota = self.page.locator(selettore).evaluate(
            "(s) => [...s.options].findIndex((o) => o.text.trim() === '')")
        corrente = self.page.locator(selettore).evaluate("(s) => s.selectedIndex")
        if vuota >= 0 and corrente != vuota:
            self.page.select_option(selettore, index=vuota)

    def _scelto(self, selettore: str) -> str:
        return self.page.locator(selettore).evaluate(
            "(s) => s.selectedIndex >= 0 ? s.options[s.selectedIndex].text : ''")

    def libera_righe_sbagliate(self, giocatori: list[Giocatore], lato: str) -> int:
        """Fase 0: toglie i giocatori che stanno nella riga sbagliata (es. salvati da una prova
        precedente, un titolare finito tra le riserve) e svuota le righe in più. Così poi ognuno
        può essere messo al suo posto, anche se il portale non accetta lo stesso giocatore in due
        righe. Restituisce quante righe sono state liberate."""
        liberate = 0
        abbinati, _ = self._assegnazioni(giocatori, lato)
        for g, riga in abbinati:
            try:
                r = riga()
                scelto = self._scelto(r.giocatore)
                if scelto.strip() and (g is None or scegli_opzione(g, [scelto]).stato != "trovato"):
                    self._svuota(r.giocatore)
                    liberate += 1
            except Exception:
                continue
        return liberate

    def _nominativi_colonna(self, lato: str) -> list[str]:
        """Tutte le voci delle tendine della colonna, comprese quelle già scelte nelle righe
        (il portale potrebbe non mostrare in una tendina i giocatori già scelti altrove)."""
        titolari, riserve = self._righe(lato)
        voci: list[str] = []
        for r in titolari + riserve:
            for testo in self._opzioni(r.giocatore):
                if testo not in voci:
                    voci.append(testo)
        return voci

    def aggiungi_mancanti(self, giocatori: list[Giocatore], lato: str) -> set[int]:
        """Fase 1: crea in archivio, con "Aggiungi persona", i giocatori che non sono nella tendina.
        Si fa prima di scegliere i nominativi, così un'eventuale ricarica della pagina non cancella
        scelte già fatte. Restituisce gli id dei giocatori aggiunti."""
        titolari, riserve = self._righe(lato)
        if not titolari and not riserve:
            return set()
        voci = self._nominativi_colonna(lato)
        aggiunti = set()
        for g in giocatori:
            if scegli_opzione(g, voci).stato != "nuovo":
                continue
            try:
                self._aggiungi_persona(lato, g)
                aggiunti.add(id(g))
                voci = self._nominativi_colonna(lato)
            except Exception:
                pass  # se ne riparla in fase 2: il giocatore risulterà da verificare
        return aggiunti

    def compila_lista(self, giocatori: list[Giocatore], lato: str,
                      al_giocatore: Callable[[Esito], None] | None = None,
                      aggiunti: set[int] = frozenset()) -> Report:
        """Fase 2: numero e nominativo di ogni giocatore nella sua riga."""
        report = Report()
        abbinati, report.avvisi = self._assegnazioni(giocatori, lato)
        for g, riga in abbinati:
            if g is None:
                try:
                    self._svuota(riga().giocatore)
                except Exception:
                    pass
                continue
            esito = self._compila_riga(g, riga, lato, aggiunto=id(g) in aggiunti)
            report.esiti.append(esito)
            if al_giocatore:
                al_giocatore(esito)
        self.istantanea(f"compilata-{lato}")
        return report

    def verifica_e_ripara(self, giocatori: list[Giocatore], lato: str) -> int:
        """Fase 3: rilegge ogni riga e rimette le scelte sparite (es. dopo una ricarica della pagina).
        Restituisce quante righe sono state ripristinate."""
        riparate = 0
        abbinati, _ = self._assegnazioni(giocatori, lato)
        for g, riga in abbinati:
            if g is None:
                continue
            try:
                r = riga()
                scelto = self.page.locator(r.giocatore).evaluate(
                    "(s) => s.selectedIndex >= 0 ? s.options[s.selectedIndex].text : ''")
                numero = self.page.locator(r.numero).evaluate(
                    "(s) => s.selectedIndex >= 0 ? s.options[s.selectedIndex].text.trim() : ''")
                giusto = scegli_opzione(g, [scelto]).stato == "trovato"
                numero_giusto = g.numero is None or numero == str(g.numero)
                if not (giusto and numero_giusto) and scegli_opzione(g, self._opzioni(r.giocatore)).stato == "trovato":
                    if self._compila_riga(g, riga, lato).stato == "selezionato":
                        riparate += 1
            except Exception:
                continue
        return riparate

    # --- sostituzioni -------------------------------------------------------------------

    def apri_scheda(self, ancora: str) -> None:
        """Passa a una scheda del referto (es. "tabs-Sostituzioni") senza salvare nulla."""
        self.page.locator(f"a[href='#{ancora}']").first.click()
        self.page.locator(f"#{ancora}").wait_for(state="visible")
        self.chiudi_finestre(300)

    def _scegli_in_riga(self, riga: Locator, nome: str, valore: str | None = None,
                        numero: int | None = None) -> None:
        """Sceglie un'opzione della tendina `nome` della riga: per valore (tempo, minuto) o per
        numero di maglia (esce, entra: l'attributo data-numero, anche per i rientri "* 6 - ...")."""
        tendina = riga.locator(f"select[name={nome}]")
        opzioni = tendina.evaluate(
            "(s) => [...s.options].map((o) => [o.value, o.dataset.numero || '', o.text.trim()])")
        if numero is not None:
            valore = next((v for v, n, _ in opzioni if n == str(numero)), None)
            if valore is None:
                disponibili = ", ".join(n for v, n, _ in opzioni if n and n != "0") or "nessuno"
                verbo = "uscire" if nome == "esce" else "entrare"
                raise ValueError(f"il n. {numero} non può {verbo} in quel momento (possibili: {disponibili})")
        elif valore not in [v for v, _, _ in opzioni]:
            raise ValueError(f"{nome} {valore} non disponibile nel portale")
        tendina.select_option(valore)
        if tendina.input_value() != valore:
            raise ValueError(f"il portale non ha accettato {nome} {numero if numero is not None else valore}")

    def compila_sostituzioni(self, sostituzioni: list[Sostituzione], lato: str) -> list[EsitoSostituzione]:
        """Scheda Sostituzioni di una squadra. Le tendine ESCE/ENTRA dipendono dalle Liste Gara
        salvate e dalle sostituzioni delle righe precedenti, quindi le righe si compilano in ordine
        di tempo. Le righe già compilate (es. da una prova precedente) prima si svuotano. Una
        sostituzione che il portale non accetta resta fuori e viene segnalata."""
        self.apri_scheda("tabs-Sostituzioni")
        righe = self.page.locator(f"{TABELLA_SOSTITUZIONI[lato]} > tr")
        righe.first.locator("select[name=esce]").wait_for()
        for k in reversed(range(righe.count())):  # dall'ultima, così le tendine restano coerenti
            for nome in ("entra", "esce"):
                tendina = righe.nth(k).locator(f"select[name={nome}]")
                if tendina.input_value() not in ("", "0"):
                    tendina.select_option("0")

        esiti: dict[int, EsitoSostituzione] = {}
        k = 0
        for i in ordine_cronologico(sostituzioni):
            s = sostituzioni[i]
            if not completa(s):
                esiti[i] = EsitoSostituzione(s, "errore", "dati incompleti: non inserita")
                continue
            if k >= righe.count():
                self.accetta_conferme = True  # "per questa categoria sono previste al massimo..."
                try:
                    self.page.locator(AGGIUNGI_SOSTITUZIONE[lato]).click()
                    self.page.wait_for_function(
                        "([sel, n]) => document.querySelectorAll(sel).length > n",
                        arg=[f"{TABELLA_SOSTITUZIONI[lato]} > tr", k], timeout=5_000)
                except Exception:
                    esiti[i] = EsitoSostituzione(s, "errore", "impossibile aggiungere una riga nel portale")
                    continue
                finally:
                    self.accetta_conferme = False
            riga = righe.nth(k)
            prima = {n: riga.locator(f"select[name={n}]").input_value() for n in ("tempo", "minuto")}
            try:
                self._scegli_in_riga(riga, "tempo", valore=str(s.tempo))
                self._scegli_in_riga(riga, "minuto", valore=str(s.minuto))
                self._scegli_in_riga(riga, "esce", numero=s.esce)
                self._scegli_in_riga(riga, "entra", numero=s.entra)
                esiti[i] = EsitoSostituzione(s, "inserita")
                k += 1
            except Exception as e:
                # La riga torna com'era, libera per la sostituzione successiva.
                for nome, valore in (("entra", "0"), ("esce", "0"), *prima.items()):
                    try:
                        riga.locator(f"select[name={nome}]").select_option(valore)
                    except Exception:
                        pass
                esiti[i] = EsitoSostituzione(s, "errore", str(e).splitlines()[0])
        self.istantanea(f"sostituzioni-{lato}")
        return [esiti[i] for i in range(len(sostituzioni))]

    def _compila_riga(self, g: Giocatore, riga, lato: str, aggiunto: bool = False) -> Esito:
        try:
            r = riga()
            scelto = self.page.locator(r.giocatore).evaluate(
                "(s) => s.selectedIndex >= 0 ? s.options[s.selectedIndex].text : ''")
            if scelto.strip() and scegli_opzione(g, [scelto]).stato != "trovato":
                self._svuota(r.giocatore)  # c'era un altro giocatore (es. da una prova precedente)
            if g.numero is not None:
                self.page.select_option(r.numero, label=str(g.numero))
            scelta = scegli_opzione(g, self._opzioni(r.giocatore))
            if scelta.stato == "da_verificare":
                return Esito(g, "da_verificare", scelta.motivo)
            if scelta.stato == "nuovo":
                # Non aggiunto in fase 1 (o aggiunta non riuscita): si riprova qui.
                self._aggiungi_persona(lato, g)
                aggiunto = True
                r = riga()
                if g.numero is not None:
                    self.page.select_option(r.numero, label=str(g.numero))
                scelta = scegli_opzione(g, self._opzioni(r.giocatore))
                if scelta.stato != "trovato":
                    return Esito(g, "da_verificare", "aggiunto ma non trovato nella tendina")
            prima = len(self.messaggi_portale)
            self.page.select_option(r.giocatore, index=scelta.indice)
            if scegli_opzione(g, [self._scelto(riga().giocatore)]).stato != "trovato":
                messaggio = " ".join(self.messaggi_portale[prima:]) or "la scelta non è rimasta"
                return Esito(g, "errore", f"il portale ha rifiutato la scelta: {messaggio}")
            return Esito(g, "aggiunto" if aggiunto else "selezionato")
        except Exception as e:  # una riga sbagliata non deve fermare le altre
            return Esito(g, "errore", str(e).splitlines()[0])
