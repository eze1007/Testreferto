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
from app.schema import Distinta, Giocatore


def g(n, cognome, nome, data, riserva=False, dubbi=()):
    return Giocatore(testo_originale=f"{cognome} {nome}", numero=n, cognome=cognome, nome=nome,
                     data_nascita=data, riserva=riserva, dubbi=list(dubbi))


LETTURE = {
    "casa.jpg": Distinta(giocatori=[g(1, "ROSSI", "MARIO", "01/01/2000"),
                                    g(12, "BIANCHI", "LUCA", "02/02/2001", riserva=True)], note_generali=[]),
    "ospite.jpg": Distinta(giocatori=[g(9, "VERDI", "ANNA", "03/03/2003", dubbi=["nome poco leggibile"])],
                           note_generali=[]),
}


def finta_lettura(dati: bytes, content_type: str) -> Distinta:
    if dati == b"rotta":
        raise main.LetturaFallita("foto illeggibile")
    return LETTURE[dati.decode()].model_copy(deep=True)


@pytest.fixture(scope="module")
def server():
    os.environ.update(APP_USER="arbitro", APP_PASSWORD="segreta")
    originale, main.estrai_distinta = main.estrai_distinta, finta_lettura
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


@pytest.fixture
def page(server):
    exe = os.environ.get("CHROMIUM_PATH") or next(iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")), None)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe)
        ctx = browser.new_context(http_credentials={"username": "arbitro", "password": "segreta"}, accept_downloads=True)
        pagina = ctx.new_page()
        pagina.goto(server)
        yield pagina
        browser.close()


def carica(page, lato, nome, contenuto):
    page.set_input_files(f".card[data-lato={lato}] input[type=file]",
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

    campo = ospite.locator("input[data-k=nome]")
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
