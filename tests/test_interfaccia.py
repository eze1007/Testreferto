"""Test della pagina web nel browser: carica le due distinte, Prosegui, tabelle (dati inventati)."""

import glob
import json
import os
import socket
import threading
import time

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from app import main
from app.schema import Distinta, Giocatore, Rapportino, Sostituzione

from . import portale_finto

CHROMIUM = os.environ.get("CHROMIUM_PATH") or next(iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")), None)


def g(n, cognome, nome, data, riserva=False, dubbi=()):
    return Giocatore(testo_originale=f"{cognome} {nome}", numero=n, cognome=cognome, nome=nome,
                     data_nascita=data, riserva=riserva, dubbi=list(dubbi))


LETTURE = {
    "casa.jpg": Distinta(giocatori=[g(1, "ROSSI", "MARIO", "01/01/2000"),
                                    g(12, "BIANCHI", "LUCA", "02/02/2001", riserva=True)], note_generali=[]),
    "ospite.jpg": Distinta(giocatori=[g(9, "VERDI", "ANNA", "03/03/2003", dubbi=["nome poco leggibile"]),
                                      g(10, "NUOVO", "GIOCATORE", "05/05/2005")], note_generali=[]),
}


def sost(tempo, minuto, esce, entra, dubbi=()):
    return Sostituzione(tempo=tempo, minuto=minuto, esce=esce, entra=entra, dubbi=list(dubbi))


RAPPORTINO = Rapportino(casa=[sost(1, 20, 1, 12), sost(2, 5, 1, 13)],
                        ospite=[sost(2, 3, 9, 10, dubbi=["minuto 3 o 8"])], note_generali=[])


# Quali file sono stati mandati alla lettura: si devono leggere solo quelli che servono.
LETTURE_FATTE: list[str] = []


def finto_rapportino(dati: bytes, content_type: str) -> Rapportino:
    LETTURE_FATTE.append("rapportino")
    if dati == b"rotta":
        raise main.LetturaFallita("rapportino illeggibile")
    return RAPPORTINO.model_copy(deep=True)


def _jpeg(colore: str) -> bytes:
    import io

    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (900, 1200), colore).save(out, format="JPEG")
    return out.getvalue()


# Foto vere (per gli allegati): la lettura finta le riconosce come le distinte di prova.
FOTO = {"casa.jpg": _jpeg("white"), "ospite.jpg": _jpeg("lightgray")}


def finta_lettura(dati: bytes, content_type: str) -> Distinta:
    LETTURE_FATTE.append("distinta")
    if dati == b"rotta":
        raise main.LetturaFallita("foto illeggibile")
    chiave = next((nome for nome, contenuto in FOTO.items() if contenuto == dati), None) or dati.decode()
    return LETTURE[chiave].model_copy(deep=True)


@pytest.fixture(scope="module")
def server():
    os.environ.update(APP_USER="arbitro", APP_PASSWORD="segreta",
                      SINFONIA_USER="arbitro123", SINFONIA_PASSWORD="segreta")
    if CHROMIUM:
        os.environ.setdefault("CHROMIUM_PATH", CHROMIUM)
    originale, main.estrai_distinta = main.estrai_distinta, finta_lettura
    originale_rapportino, main.estrai_rapportino = main.estrai_rapportino, finto_rapportino
    main.PREPARA_PAGINA = portale_finto.installa  # il server compila la copia finta del portale
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=porta, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{porta}/"
    srv.should_exit = True
    main.estrai_distinta = originale
    main.estrai_rapportino = originale_rapportino
    main.PREPARA_PAGINA = None


@pytest.fixture
def page(server):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM)
        ctx = browser.new_context(http_credentials={"username": "arbitro", "password": "segreta"}, accept_downloads=True)
        pagina = ctx.new_page()
        pagina.goto(server)
        yield pagina
        browser.close()


def carica(page, lato, nome, contenuto):
    page.set_input_files(f"#caricamento .card[data-lato={lato}] input[type=file]",
                         files=[{"name": nome, "mimeType": "image/jpeg", "buffer": contenuto}])


def test_flusso_completo(page):
    assert page.locator("#prosegui").is_disabled()
    carica(page, "casa", "casa.jpg", b"casa.jpg")
    assert page.locator("#prosegui").is_disabled()          # serve anche l'ospite
    carica(page, "ospite", "ospite.jpg", b"ospite.jpg")
    page.click("#prosegui")

    page.locator("#revisione").wait_for()
    casa = page.locator("#tabella-casa")
    assert casa.locator("input[data-k=cognome]").evaluate_all("els => els.map(e => e.value)") == ["ROSSI", "BIANCHI"]
    assert "Riserve (1)" in casa.inner_text()
    ospite = page.locator("#tabella-ospite")
    assert ospite.locator("td.dubbio").count() == 4         # riga incerta evidenziata
    assert "nome poco leggibile" in ospite.inner_text()

    campo = ospite.locator("input[data-k=nome]").first
    campo.fill("annA ")
    campo.dispatch_event("change")
    with page.expect_download() as dl:
        page.click("#scarica")
    salvato = json.loads(open(dl.value.path()).read())
    assert set(salvato) == {"casa", "ospite"}
    assert salvato["ospite"]["giocatori"][0]["nome"] == "ANNA"
    assert salvato["casa"]["giocatori"][1]["riserva"] is True


def test_errore_su_una_squadra(page):
    carica(page, "casa", "casa.jpg", b"casa.jpg")
    carica(page, "ospite", "rotta.jpg", b"rotta")
    page.click("#prosegui")
    page.locator("#revisione").wait_for()
    assert "foto illeggibile" in page.locator("#tabella-ospite").inner_text()
    assert page.locator("#tabella-casa input[data-k=cognome]").count() == 2


def test_compilazione_dalla_pagina(page):
    carica(page, "casa", "casa.jpg", b"casa.jpg")
    carica(page, "ospite", "ospite.jpg", b"ospite.jpg")
    page.click("#prosegui")
    page.locator("#revisione").wait_for()

    page.click("#avvia")                                    # senza gara non parte
    assert page.locator("#compilazione").is_hidden()
    page.fill("#gara", "sarego liona")
    page.once("dialog", lambda d: d.accept())
    page.click("#avvia")

    page.locator("#esito-finale .ok").wait_for(timeout=60_000)
    assert "Salva Tutto" in page.locator("#esito-finale").inner_text()
    stati = lambda lato: page.locator(f"#esiti-{lato} .esito").all_inner_texts()
    assert stati("casa") == ["Selezionato", "Selezionato"]  # ROSSI e BIANCHI sono già in archivio
    assert stati("ospite") == ["Selezionato", "Nuovo"]
    assert "Salvataggio (Salva Tutto)" in page.locator("#passi").inner_text()
    page.locator("#screenshot").wait_for()
    assert page.locator("#screenshot").evaluate("img => img.complete && img.naturalWidth > 0")
    page.click("#torna")
    assert page.locator("#revisione").is_visible()


def test_casella_r_arriva_alla_compilazione(page):
    """Se nella tabella l'arbitro cambia titolari e riserve con la casella R, la compilazione
    deve ricevere i valori cambiati."""
    carica(page, "casa", "casa.jpg", b"casa.jpg")
    carica(page, "ospite", "ospite.jpg", b"ospite.jpg")
    page.click("#prosegui")
    page.locator("#revisione").wait_for()
    page.locator("#tabella-casa input[data-k=riserva]").nth(1).click()    # BIANCHI: da riserva a titolare
    page.locator("#tabella-ospite input[data-k=riserva]").nth(0).click()  # VERDI: da titolare a riserva
    inviato = {}
    page.route("**/api/compila", lambda route: (inviato.update(json.loads(route.request.post_data)),
                                                route.fulfill(status=409, json={"detail": "prova"})))
    page.fill("#gara", "sarego")
    page.on("dialog", lambda d: d.accept())
    page.click("#avvia")
    page.wait_for_timeout(500)
    assert [g["riserva"] for g in inviato["casa"]["giocatori"]] == [False, False]
    assert [g["riserva"] for g in inviato["ospite"]["giocatori"]] == [True, False]


def test_piu_di_11_titolari_blocca_la_compilazione(page):
    carica(page, "casa", "casa.jpg", b"casa.jpg")
    carica(page, "ospite", "ospite.jpg", b"ospite.jpg")
    page.click("#prosegui")
    page.locator("#revisione").wait_for()
    page.evaluate("""() => { for (let i = 0; i < 12; i++) dati.casa.distinta.giocatori.push(
        {...dati.casa.distinta.giocatori[0], numero: 20 + i, riserva: false}); }""")
    messaggi = []
    page.on("dialog", lambda d: (messaggi.append(d.message), d.accept()))
    page.fill("#gara", "sarego")
    page.click("#avvia")
    page.wait_for_timeout(300)
    assert messaggi and "13 titolari" in messaggi[0]
    assert page.locator("#compilazione").is_hidden()


def avvisi_sost(page, lato):
    return page.locator(f"#sost-{lato} .avvisi li").all_inner_texts()


def test_rapportino_sostituzioni_controllate_e_compilate(page):
    carica(page, "casa", "casa.jpg", b"casa.jpg")
    carica(page, "ospite", "ospite.jpg", b"ospite.jpg")
    carica(page, "rapportino", "rapportino.jpg", b"rapportino")
    page.click("#prosegui")
    page.locator("#revisione").wait_for()
    assert page.locator("#box-sostituzioni").is_visible()

    casa = page.locator("#sost-casa")
    assert casa.locator("tr[data-i]").count() == 2
    assert casa.locator("tr[data-i] [data-k=esce]").evaluate_all("els => els.map(e => e.value)") == ["1", "1"]
    page.wait_for_function("document.querySelectorAll('#sost-casa .avvisi li').length > 0")
    assert avvisi_sost(page, "casa") == ["5' del 2° t.: il n. 13 non è in distinta.",
                                         "5' del 2° t.: esce il n. 1, ma non è in campo (uscito al 20' del 1° t.)."]
    assert casa.locator("tr.anomalia").count() == 1 and casa.locator("tr[data-i='1']").get_attribute("class") == "anomalia"
    assert casa.locator("tr[data-i='0'] [data-chi=esce]").inner_text() == "ROSSI MARIO"   # nome dalla distinta
    assert casa.locator("tr[data-i='0'] [data-chi=entra]").inner_text() == "BIANCHI LUCA"
    assert "minuto 3 o 8" in " ".join(avvisi_sost(page, "ospite"))

    # L'arbitro toglie la riga sbagliata e scrive quella giusta.
    casa.locator("tr[data-i='1'] .togli").click()
    casa.get_by_text("Nessuna anomalia").wait_for()
    assert casa.locator(".avvisi").count() == 0
    casa.locator(".aggiungi").click()
    nuova = casa.locator("tr[data-i='1']")
    assert nuova.locator("[data-k=tempo]").input_value() == "1"   # tempo della riga prima
    nuova.locator("[data-k=tempo]").select_option("2")
    for k, v in (("minuto", "15"), ("esce", "12"), ("entra", "1")):
        nuova.locator(f"[data-k={k}]").fill(v)
        nuova.locator(f"[data-k={k}]").dispatch_event("change")
    page.wait_for_function("document.querySelectorAll('#sost-casa .avvisi li').length === 1")
    assert avvisi_sost(page, "casa") == ["15' del 2° t.: rientra il n. 1 (uscito al 20' del 1° t.). Controlla che sia giusto."]

    # Cambiare la distinta ricalcola i controlli: se il 12 diventa titolare, non può più entrare.
    page.locator("#tabella-casa input[data-k=riserva]").nth(1).uncheck()
    page.wait_for_function("document.querySelectorAll('#sost-casa .avvisi li').length === 2")
    assert "20' del 1° t.: entra il n. 12, ma è già in campo (titolare)." in avvisi_sost(page, "casa")
    page.locator("#tabella-casa input[data-k=riserva]").nth(1).check()
    page.wait_for_function("document.querySelectorAll('#sost-casa .avvisi li').length === 1")

    page.fill("#gara", "tezze brendola")
    portale_finto.SALVATAGGI.clear()
    domande = []
    page.once("dialog", lambda d: (domande.append(d.message), d.accept()))
    page.click("#avvia")
    page.locator("#esito-finale .ok").wait_for(timeout=90_000)
    assert "sostituzioni (casa 2, ospite 1)" in domande[0] and "3 da controllare" in domande[0]
    passi = page.locator("#passi").inner_text()
    assert "Riapertura del referto per le Sostituzioni" in passi and "Sostituzioni salvate" in passi
    # Dopo il salvataggio il referto viene riaperto e le sostituzioni lette dal portale.
    assert "Verifica sul portale: tutte le sostituzioni inserite risultano salvate." in passi
    finale = page.locator("#esito-finale").inner_text()
    assert "Sostituzioni verificate sul portale." in finale and "finestra anonima" in finale
    assert page.locator("#esiti-casa .esiti-sost .esito").all_inner_texts() == ["Inserita", "Inserita"]
    assert page.locator("#esiti-ospite .esiti-sost .esito").all_inner_texts() == ["Inserita"]
    # Entrambi i "Salva Tutto" sono arrivati al portale prima che il browser si chiudesse:
    # prima le Liste Gara, poi le sostituzioni nel referto riaperto.
    assert [s["pagina"] for s in portale_finto.SALVATAGGI] == ["liste.asp", "default.asp"]
    assert portale_finto.SALVATAGGI[1]["casa"] == [["1", "20", "1", "12"], ["2", "15", "12", "1"]]
    assert portale_finto.SALVATAGGI[1]["ospite"] == [["2", "3", "9", "10"]]


def test_rapportino_illeggibile(page):
    carica(page, "casa", "casa.jpg", b"casa.jpg")
    carica(page, "ospite", "ospite.jpg", b"ospite.jpg")
    carica(page, "rapportino", "rapportino.jpg", b"rotta")
    page.click("#prosegui")
    page.locator("#revisione").wait_for()
    assert "rapportino illeggibile" in page.locator("#errore-rapportino").inner_text()
    assert "Nessuna sostituzione" in page.locator("#sost-casa").inner_text()  # si possono scrivere a mano
    assert page.locator("#tabella-casa input[data-k=cognome]").count() == 2   # le distinte ci sono


def test_senza_rapportino_niente_sostituzioni(page):
    carica(page, "casa", "casa.jpg", b"casa.jpg")
    carica(page, "ospite", "ospite.jpg", b"ospite.jpg")
    page.click("#prosegui")
    page.locator("#revisione").wait_for()
    assert page.locator("#box-sostituzioni").is_hidden()


def test_allegati_dalla_pagina(page):
    carica(page, "casa", "casa.jpg", FOTO["casa.jpg"])
    carica(page, "ospite", "ospite.jpg", FOTO["ospite.jpg"])
    carica(page, "rapportino", "rapportino.jpg", _jpeg("whitesmoke"))
    assert all(page.locator(f"#fase-{f}").is_checked() for f in ("liste", "sostituzioni", "allegati"))  # di norma tutto
    page.click("#prosegui")
    page.locator("#revisione").wait_for()
    page.fill("#gara", "tezze brendola")
    domande = []
    page.once("dialog", lambda d: (domande.append(d.message), d.accept()))
    page.click("#avvia")
    page.locator("#esito-finale .ok").wait_for(timeout=120_000)
    assert "• Allegare: distinta di casa, distinta ospite, rapportino." in domande[0]
    assert page.locator("#esiti-allegati .esito").all_inner_texts() == ["Caricato"] * 3
    assert page.locator("#box-allegati").is_visible()
    assert "allegati non caricati" not in page.locator("#esito-finale").inner_text()
    assert [(a["tipo"], a["squadra"]) for a in portale_finto.ALLEGATI_CARICATI] == [("1", "1001"), ("1", "2001"), ("3", "0")]
    assert "Allegati: 3 caricati, 0 già presenti, 0 con errori." in page.locator("#passi").inner_text()


def test_senza_allegati_niente_allegati(page):
    carica(page, "casa", "casa.jpg", FOTO["casa.jpg"])
    carica(page, "ospite", "ospite.jpg", FOTO["ospite.jpg"])
    page.uncheck("#fase-allegati")
    page.click("#prosegui")
    page.locator("#revisione").wait_for()
    page.fill("#gara", "tezze brendola")
    domande = []
    page.once("dialog", lambda d: (domande.append(d.message), d.accept()))
    page.click("#avvia")
    page.locator("#esito-finale .ok").wait_for(timeout=120_000)
    assert "Allegare" not in domande[0] and "• Liste Gara" in domande[0]
    assert portale_finto.ALLEGATI_CARICATI == []
    assert page.locator("#box-allegati").is_hidden()
    assert "Allegati" not in page.locator("#passi").inner_text()


def test_prosegui_secondo_le_caselle(page):
    carica(page, "rapportino", "rapportino.jpg", b"rapportino")
    assert page.locator("#prosegui").is_disabled()                 # Liste Gara spuntate: servono le distinte
    assert "servono le due distinte" in page.locator("#stato-caricamento").inner_text()
    page.uncheck("#fase-liste")
    assert page.locator("#prosegui").is_enabled()                  # sostituzioni e allegati: basta il rapportino
    for f in ("sostituzioni", "allegati"):
        page.uncheck(f"#fase-{f}")
    assert page.locator("#prosegui").is_disabled()
    assert "spunta almeno una cosa da fare" in page.locator("#stato-caricamento").inner_text().lower()


def test_solo_allegati_senza_leggere_niente(page):
    LETTURE_FATTE.clear()
    portale_finto.SALVATAGGI.clear()
    carica(page, "casa", "casa.jpg", FOTO["casa.jpg"])
    carica(page, "ospite", "ospite.jpg", FOTO["ospite.jpg"])
    carica(page, "rapportino", "rapportino.jpg", _jpeg("whitesmoke"))
    page.uncheck("#fase-liste")
    page.uncheck("#fase-sostituzioni")
    page.click("#prosegui")
    page.locator("#revisione").wait_for()
    assert LETTURE_FATTE == []                                    # per allegare non si legge niente
    assert page.locator("#griglia-distinte").is_hidden() and page.locator("#box-sostituzioni").is_hidden()
    assert page.locator("#riepilogo-fasi li").all_inner_texts() == [
        "Allegati: distinta di casa, distinta ospite, rapportino; quelli già presenti non vengono ricaricati."]
    page.fill("#gara", "tezze brendola")
    domande = []
    page.once("dialog", lambda d: (domande.append(d.message), d.accept()))
    page.click("#avvia")
    page.locator("#esito-finale .ok").wait_for(timeout=120_000)
    assert "• Allegare:" in domande[0] and "Liste Gara" not in domande[0] and "sostituzioni" not in domande[0]
    assert page.locator("#esito-finale .ok").inner_text().startswith("Completato.")
    assert page.locator("#esiti-allegati .esito").all_inner_texts() == ["Caricato"] * 3
    assert page.locator("#griglia-esiti").is_hidden()
    passi = page.locator("#passi").inner_text()
    assert "Svolgimento" not in passi and "Liste Gara" not in passi and "Sostituzioni" not in passi
    assert portale_finto.SALVATAGGI == []                         # nessun «Salva Tutto»


def test_solo_sostituzioni(page):
    LETTURE_FATTE.clear()
    portale_finto.SALVATAGGI.clear()
    carica(page, "rapportino", "rapportino.jpg", b"rapportino")
    page.uncheck("#fase-liste")
    page.uncheck("#fase-allegati")
    page.click("#prosegui")
    page.locator("#revisione").wait_for()
    assert LETTURE_FATTE == ["rapportino"]                        # le distinte non servono
    assert page.locator("#griglia-distinte").is_hidden() and page.locator("#box-sostituzioni").is_visible()
    page.wait_for_function("document.querySelectorAll('#sost-casa .avvisi li').length > 0")
    page.fill("#gara", "tezze brendola")
    domande = []
    page.once("dialog", lambda d: (domande.append(d.message), d.accept()))
    page.click("#avvia")
    page.locator("#esito-finale .ok").wait_for(timeout=120_000)
    assert "Inserire le sostituzioni (casa 2, ospite 1)" in domande[0] and "Liste Gara" not in domande[0]
    passi = page.locator("#passi").inner_text()
    assert "Apertura della gara «tezze brendola» per le Sostituzioni" in passi and "Svolgimento" not in passi
    assert [s["pagina"] for s in portale_finto.SALVATAGGI] == ["default.asp"]   # un solo salvataggio
    # Il 20' 1°t esce 1 entra 12 va; il 5' 2°t esce di nuovo l'1: il portale non lo permette.
    assert page.locator("#esiti-casa .esiti-sost .esito").all_inner_texts() == ["Inserita", "Errore"]
    assert page.locator("#esiti-ospite .esiti-sost .esito").all_inner_texts() == ["Inserita"]
    assert "Verifica sul portale: tutte le sostituzioni inserite risultano salvate." in passi
    assert page.locator("#box-allegati").is_hidden()
