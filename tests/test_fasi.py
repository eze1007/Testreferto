"""Scelta di cosa fare (Liste Gara, Sostituzioni, Allegati): controlli del server e procedura."""

import base64
import glob
import io
import os

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.compilazione import compila
from app.schema import Distinta, Giocatore, Sostituzione

from . import portale_finto

CHROMIUM = os.environ.get("CHROMIUM_PATH") or next(iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")), None)

DISTINTA = {"giocatori": [{"testo_originale": "ROSSI MARIO", "numero": 1, "cognome": "ROSSI", "nome": "MARIO",
                           "data_nascita": "01/01/2000", "riserva": False, "dubbi": []}], "note_generali": []}
SOSTITUZIONE = {"tempo": 1, "minuto": 20, "esce": 1, "entra": 12, "dubbi": []}


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_USER", "arbitro")
    monkeypatch.setenv("APP_PASSWORD", "segreta")
    monkeypatch.setenv("SINFONIA_USER", "arbitro123")
    monkeypatch.setenv("SINFONIA_PASSWORD", "segreta")
    avviati = []
    # Niente browser: si guarda solo cosa arriverebbe alla compilazione.
    monkeypatch.setattr(main, "_esegui", lambda lavoro, squadre, gara, u, p, sost, allegati, fasi: (
        avviati.append({"squadre": set(squadre), "sostituzioni": set(sost), "allegati": set(allegati), "fasi": fasi}),
        main._un_lavoro_alla_volta.release()))
    c = TestClient(main.app)
    c.avviati = avviati
    return c


def invia(client, **corpo):
    return client.post("/api/compila", auth=("arbitro", "segreta"), json={"gara": "tezze", **corpo})


@pytest.mark.parametrize("corpo, messaggio", [
    ({"fasi": []}, "Scegli cosa fare"),
    ({"fasi": ["invia"]}, "Scegli cosa fare"),
    ({"fasi": ["liste"]}, "almeno una squadra"),
    ({"fasi": ["sostituzioni"], "casa": DISTINTA}, "Nessuna sostituzione"),
    ({"fasi": ["sostituzioni"], "sostituzioni": {"casa": []}}, "Nessuna sostituzione"),
    ({"fasi": ["allegati"], "casa": DISTINTA}, "Nessun file da allegare"),
    ({"fasi": ["allegati"], "gara": "  "}, "Scrivi la gara"),
])
def test_scelte_non_valide(client, corpo, messaggio):
    r = invia(client, **corpo)
    assert r.status_code == 422 and messaggio in r.json()["detail"]
    assert client.avviati == []


def test_solo_cio_che_e_scelto_arriva_alla_compilazione(client):
    allegato = {"nome": "d.jpg", "tipo": "image/jpeg", "dati": base64.b64encode(jpeg()).decode()}
    tutto = {"casa": DISTINTA, "sostituzioni": {"casa": [SOSTITUZIONE]}, "allegati": {"casa": allegato}}
    assert invia(client, fasi=["allegati"], **tutto).status_code == 200
    assert invia(client, fasi=["sostituzioni"], **tutto).status_code == 200
    assert invia(client, **tutto).status_code == 200                 # senza "fasi": tutto, come prima
    assert client.avviati == [
        {"squadre": set(), "sostituzioni": set(), "allegati": {"casa"}, "fasi": {"allegati"}},
        {"squadre": set(), "sostituzioni": {"casa"}, "allegati": set(), "fasi": {"sostituzioni"}},
        {"squadre": {"casa"}, "sostituzioni": {"casa"}, "allegati": {"casa"},
         "fasi": {"liste", "sostituzioni", "allegati"}},
    ]


# --- procedura sul portale finto -----------------------------------------------------------------

SQUADRE = {"casa": Distinta.model_validate(DISTINTA)}


@pytest.fixture
def chromium(monkeypatch):
    if CHROMIUM:
        monkeypatch.setenv("CHROMIUM_PATH", CHROMIUM)
    portale_finto.SALVATAGGI.clear()


def test_solo_allegati(chromium):
    passi = []
    r = compila({}, "tezze brendola", "arbitro123", "segreta", avanzamento=passi.append, fasi={"allegati"},
                prepara_pagina=portale_finto.installa, allegati={"rapportino": (jpeg(), "image/jpeg")})
    assert r.errore is None and r.bottone_salvataggio is None
    assert [(e.descrizione, e.stato) for e in r.allegati] == [("Rapportino di fine gara", "caricato")]
    assert portale_finto.SALVATAGGI == []                              # nessun «Salva Tutto»
    assert not any("Svolgimento" in p or "Liste Gara" in p or "Sostituzioni" in p for p in passi)
    assert "Apertura della gara «tezze brendola»…" in passi


def test_solo_sostituzioni(chromium):
    passi = []
    r = compila(SQUADRE, "tezze brendola", "arbitro123", "segreta", avanzamento=passi.append,
                fasi={"sostituzioni"}, prepara_pagina=portale_finto.installa,
                sostituzioni={"casa": [Sostituzione(**SOSTITUZIONE)]},
                allegati={"rapportino": (jpeg(), "image/jpeg")})   # non scelti: non si allegano
    assert r.errore is None
    assert [e.stato for e in r.sostituzioni["casa"]] == ["inserita"]
    assert r.report == {} and r.allegati == []                         # liste e allegati non toccati
    assert [s["pagina"] for s in portale_finto.SALVATAGGI] == ["default.asp"]
    assert portale_finto.ALLEGATI_CARICATI == []
    assert "Apertura della gara «tezze brendola» per le Sostituzioni…" in passi
    assert r.verifica == []
