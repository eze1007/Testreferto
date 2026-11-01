"""Allegati del referto: preparazione dei file e caricamento nella scheda Allegati (portale finto)."""

import glob
import io
import os

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright

from app.allegati import (LIMITE_BYTE, TIPO_LISTA_CALCIATORI, TIPO_MODULO_AMMONITI, Allegato,
                          AllegatoNonValido, prepara_allegato)
from app.sinfonia import Sinfonia

from . import portale_finto

CHROMIUM = os.environ.get("CHROMIUM_PATH") or next(iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")), None)


def foto(larghezza=4032, altezza=3024, formato="JPEG", rumore=True, **opzioni) -> bytes:
    img = Image.effect_noise((larghezza, altezza), 100).convert("RGB") if rumore else Image.new("RGB", (larghezza, altezza), "white")
    out = io.BytesIO()
    img.save(out, format=formato, **opzioni)
    return out.getvalue()


def apri(dati: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(dati))
    img.load()
    return img


# --- preparazione dei file ---------------------------------------------------------------------

def test_foto_pesante_diventa_jpeg_sotto_1_mb():
    dati = foto(quality=95)            # rumore: il caso peggiore per la compressione
    assert len(dati) > 3_000_000
    pronto = prepara_allegato(dati, "image/jpeg")
    assert len(pronto) <= LIMITE_BYTE < 1048576
    img = apri(pronto)
    assert img.format == "JPEG" and max(img.size) <= 2400


def test_foglio_normale_resta_grande_e_leggibile():
    pronto = prepara_allegato(foto(3024, 4032, rumore=False, quality=95), "image/jpeg")
    assert apri(pronto).size == (1800, 2400)   # solo ridimensionato, nessuna perdita oltre il necessario


def test_png_trasparente_diventa_bianco():
    img = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    out = io.BytesIO()
    img.save(out, format="PNG")
    pronto = apri(prepara_allegato(out.getvalue(), "image/png"))
    assert pronto.format == "JPEG" and pronto.getpixel((10, 10))[0] > 240   # bianco, non nero


def test_pdf_di_piu_pagine_in_un_solo_jpeg():
    pagine = [Image.new("RGB", (595, 842), c) for c in ("white", "lightgray")]
    out = io.BytesIO()
    pagine[0].save(out, format="PDF", save_all=True, append_images=pagine[1:])
    pronto = apri(prepara_allegato(out.getvalue(), "application/pdf"))
    assert pronto.format == "JPEG"
    assert pronto.height > pronto.width * 2      # le due pagine una sotto l'altra


def test_foto_ruotata_dal_telefono_viene_raddrizzata():
    img = Image.new("RGB", (400, 300), "white")
    exif = Image.Exif()
    exif[0x0112] = 6                             # "ruota di 90°": la foto è in verticale
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif.tobytes())
    assert apri(prepara_allegato(out.getvalue(), "image/jpeg")).size == (300, 400)


@pytest.mark.parametrize("dati", [b"", b"non sono una foto", b"%PDF-1.4 rotto"])
def test_file_non_validi(dati):
    with pytest.raises(AllegatoNonValido):
        prepara_allegato(dati, "image/jpeg")


# --- riconoscimento della squadra --------------------------------------------------------------

NOMI = {"casa": "ASD LONIGO", "ospite": "A.S.D. GAZZOLO 2014"}


@pytest.mark.parametrize("testo, lato", [("LONIGO", "casa"), ("GAZZOLO 2014", "ospite"), ("ASD Lonigo", "casa"),
                                          ("SAN BONIFACIO", None), ("", None)])
def test_lato_da_nome(testo, lato):
    assert Sinfonia.lato_da_nome(testo, NOMI) == lato


def test_squadra_ambigua_non_si_indovina():
    nomi = {"casa": "VERONA", "ospite": "HELLAS VERONA"}
    assert Sinfonia.lato_da_nome("HELLAS VERONA", nomi) == "ospite"   # uguale: vince
    assert Sinfonia.lato_da_nome("VERONA", nomi) == "casa"
    assert Sinfonia.lato_da_nome("VERON", nomi) is None              # contenuto in entrambi: non si sceglie


def test_valore_squadra():
    s4y = Sinfonia.__new__(Sinfonia)  # solo il metodo, senza browser
    opzioni = [["0", ""], ["1085046", "GAZZOLO 2014"], ["1085043", "LONIGO"]]
    assert s4y._valore_squadra(opzioni, "casa", NOMI) == "1085043"
    assert s4y._valore_squadra(opzioni, "ospite", NOMI) == "1085046"
    with pytest.raises(RuntimeError, match="squadra non riconosciuta"):
        s4y._valore_squadra(opzioni, "casa", {"casa": "SAN BONIFACIO", "ospite": "ALTRA"})
    # Solo se il referto non mostra i nomi: per posizione, prima la casa.
    assert s4y._valore_squadra(opzioni, "casa", {"casa": "", "ospite": ""}) == "1085046"


# --- caricamento sul portale finto -------------------------------------------------------------

def allegati(nome_casa="distinta_casa.jpg"):
    jpeg = prepara_allegato(foto(1200, 1600, quality=90), "image/jpeg")
    return [Allegato("casa", "Distinta squadra di casa", TIPO_LISTA_CALCIATORI, "casa", nome_casa, jpeg),
            Allegato("ospite", "Distinta squadra ospite", TIPO_LISTA_CALCIATORI, "ospite", "distinta_ospite.jpg", jpeg),
            Allegato("rapportino", "Rapportino di fine gara", TIPO_MODULO_AMMONITI, None, "rapportino_fine_gara.jpg", jpeg)]


@pytest.fixture
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROMIUM)
        yield b
        b.close()


def referto(browser, **opzioni):
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    portale_finto.installa(page, **opzioni)
    s4y = Sinfonia(page)
    s4y.login("arbitro123", "segreta")
    s4y.apri_gara("tezze brendola")
    return page, s4y


def test_carica_distinte_e_rapportino(browser):
    page, s4y = referto(browser)
    esiti = s4y.carica_allegati(allegati())
    assert [e.stato for e in esiti] == ["caricato"] * 3, [e.dettaglio for e in esiti]
    caricati = portale_finto.ALLEGATI_CARICATI
    # Squadre riconosciute dal nome (nella tendina sono in ordine inverso: BRENDOLA prima).
    assert [(a["tipo"], a["squadra"], a["nome"], a["mime"]) for a in caricati] == [
        ("1", "1001", "distinta_casa.jpg", "image/jpeg"),     # TEZZE = CALCIO TEZZE, la casa
        ("1", "2001", "distinta_ospite.jpg", "image/jpeg"),   # BRENDOLA CALCIO = BRENDOLA, l'ospite
        ("3", "0", "rapportino_fine_gara.jpg", "image/jpeg"),  # modulo ammoniti/espulsi, senza squadra
    ]
    assert all(0 < a["byte"] <= LIMITE_BYTE for a in caricati)
    righe = page.locator("#riepilogo_allegati_referto > tr")
    assert righe.count() == 3 and page.locator("button.download_allegato").count() == 3
    assert page.locator("input.file_allegato").count() == 0
    assert page.evaluate("[salvato, inviato]") == [False, False]   # il caricamento non preme Salva né Invia


def test_secondo_giro_niente_doppioni(browser):
    page, s4y = referto(browser)
    assert [e.stato for e in s4y.carica_allegati(allegati())] == ["caricato"] * 3
    s4y.apri_gara("tezze brendola")                 # referto riaperto: gli allegati arrivano dal server
    esiti = s4y.carica_allegati(allegati())
    assert [e.stato for e in esiti] == ["gia_presente"] * 3
    assert len(portale_finto.ALLEGATI_CARICATI) == 3


def test_allegato_gia_presente_non_si_ricarica(browser):
    vecchio = {"id": 7, "tipo": "3", "squadra": "0", "nome": "rapportino.jpg"}
    page, s4y = referto(browser, allegati_presenti=[vecchio])
    esiti = s4y.carica_allegati(allegati())
    assert [e.stato for e in esiti] == ["caricato", "caricato", "gia_presente"]
    assert [a["nome"] for a in portale_finto.ALLEGATI_CARICATI] == ["rapportino.jpg", "distinta_casa.jpg", "distinta_ospite.jpg"]


def test_distinta_di_una_squadra_non_vale_per_l_altra(browser):
    # C'è già la distinta della squadra ospite (BRENDOLA): quella di casa va caricata comunque.
    vecchia = {"id": 8, "tipo": "1", "squadra": "2001", "nome": "brendola.jpg"}
    page, s4y = referto(browser, allegati_presenti=[vecchia])
    esiti = s4y.carica_allegati(allegati())
    assert [e.stato for e in esiti] == ["caricato", "gia_presente", "caricato"]
    assert [(a["tipo"], a["squadra"]) for a in portale_finto.ALLEGATI_CARICATI[1:]] == [("1", "1001"), ("3", "0")]


def test_errore_del_portale(browser, monkeypatch):
    monkeypatch.setattr(portale_finto, "FALLISCI_ALLEGATI", True)
    page, s4y = referto(browser)
    esiti = s4y.carica_allegati(allegati())
    assert [e.stato for e in esiti] == ["errore"] * 3
    assert esiti[0].dettaglio == "Errore nel caricamento dell'allegato."
    assert portale_finto.ALLEGATI_CARICATI == []
    # La riga rimasta vuota dopo l'errore viene riusata, non se ne aggiungono altre.
    assert page.locator("#riepilogo_allegati_referto > tr").count() == 1


def test_file_rifiutato_dal_portale(browser):
    # Un'estensione che il portale non accetta: avviso, nessun invio, errore con il testo dell'avviso.
    page, s4y = referto(browser)
    esiti = s4y.carica_allegati(allegati(nome_casa="distinta_casa.gif"))
    assert esiti[0].stato == "errore" and "sono ammessi solo file pdf, jpg, png" in esiti[0].dettaglio
    assert [e.stato for e in esiti[1:]] == ["caricato", "caricato"]
    assert [a["nome"] for a in portale_finto.ALLEGATI_CARICATI] == ["distinta_ospite.jpg", "rapportino_fine_gara.jpg"]


def test_api_allegato_rovinato(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main
    monkeypatch.setenv("APP_USER", "arbitro")
    monkeypatch.setenv("APP_PASSWORD", "segreta")
    monkeypatch.setenv("SINFONIA_USER", "arbitro123")
    monkeypatch.setenv("SINFONIA_PASSWORD", "segreta")
    corpo = {"gara": "tezze", "casa": {"giocatori": [], "note_generali": []},
             "allegati": {"casa": {"nome": "x.jpg", "tipo": "image/jpeg", "dati": "@@@ non base64 @@@"}}}
    r = TestClient(main.app).post("/api/compila", auth=("arbitro", "segreta"), json=corpo)
    assert r.status_code == 422 and "non valido" in r.json()["detail"]
    assert main._un_lavoro_alla_volta.acquire(blocking=False)   # nessuna compilazione rimasta bloccata
    main._un_lavoro_alla_volta.release()


def test_distinta_presente_di_squadra_sconosciuta_non_si_carica_alla_cieca(browser):
    # Una distinta già allegata con una squadra che non corrisponde a nessuna delle due.
    sconosciuta = {"id": 9, "tipo": "1", "squadra": "9999", "nome": "distinta.jpg"}
    page, s4y = referto(browser, allegati_presenti=[sconosciuta])
    esiti = s4y.carica_allegati(allegati())
    assert [e.stato for e in esiti] == ["errore", "errore", "caricato"]
    assert "non riconosco la squadra" in esiti[0].dettaglio
    assert [a["nome"] for a in portale_finto.ALLEGATI_CARICATI] == ["distinta.jpg", "rapportino_fine_gara.jpg"]


def test_allegato_presente_mostrato_solo_come_testo(browser):
    # Riga senza tendine: tipo e squadra si leggono dal testo («LISTA CALCIATORI», «TEZZE»).
    vecchia = {"id": 10, "tipo": "1", "squadra": "1001", "nome": "tezze.jpg", "solo_testo": True}
    page, s4y = referto(browser, allegati_presenti=[vecchia])
    esiti = s4y.carica_allegati(allegati())
    assert [e.stato for e in esiti] == ["gia_presente", "caricato", "caricato"]
    assert [(a["tipo"], a["squadra"]) for a in portale_finto.ALLEGATI_CARICATI[1:]] == [("1", "2001"), ("3", "0")]


def test_parole_distintive():
    from app.sinfonia import parole_distintive
    assert parole_distintive("A.S.D. GAZZOLO 2014") == {"GAZZOLO"}
    assert parole_distintive("CALCIO TEZZE") == {"TEZZE"}
    assert parole_distintive("S.LAZZARO SERENISSIMA") == {"LAZZARO", "SERENISSIMA"}
    assert parole_distintive("Nicolò Calcio") == {"NICOLO"}
