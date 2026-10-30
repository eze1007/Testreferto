"""Test con dati inventati: nessun dato reale di calciatori nel repository."""

import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.checks import controlla
from app.extract import LetturaFallita, estrai_distinta
from app.schema import Distinta, Giocatore


def giocatore(numero, cognome="ROSSI", nome="MARIO", dubbi=None):
    return Giocatore(numero=numero, cognome=cognome, nome=nome, dubbi=dubbi or [])


def distinta(giocatori=None):
    if giocatori is None:
        giocatori = [giocatore(i, f"ROSSI{i}") for i in range(1, 21)]
    return Distinta(giocatori=giocatori, note_generali=[])


def test_distinta_corretta_nessun_avviso():
    assert controlla(distinta()) == []


def test_avvisi_su_errori_tipici():
    g = [
        giocatore(4, "BIANCHI", "LUCA"),
        giocatore(4, "VERDI", "ANNA"),
        giocatore(None, "NERI", "PAOLO"),
        giocatore(7, "BIANCHI", "LUCA"),
        giocatore(9, "GIALLI", "", dubbi=["nome poco leggibile"]),
    ]
    testo = "\n".join(controlla(distinta(g)))
    assert "Numero 4 ripetuto 2 volte" in testo
    assert "BIANCHI LUCA compare 2 volte" in testo
    assert "NERI PAOLO: numero mancante" in testo
    assert "GIALLI: cognome o nome mancante" in testo
    assert "nome poco leggibile" in testo


def test_distinta_vuota():
    assert controlla(distinta([])) == ["Nessun giocatore letto: controlla la foto."]


class FakeClient:
    def __init__(self, stop_reason="end_turn", parsed=None):
        self.chiamate = []
        resp = SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed)

        def parse(**kw):
            self.chiamate.append(kw)
            return resp

        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=parse))


def jpeg_grande():
    out = io.BytesIO()
    Image.new("RGB", (4000, 3000), "white").save(out, format="JPEG")
    return out.getvalue()


def test_estrai_ridimensiona_immagine_e_usa_schema():
    client = FakeClient(parsed=distinta())
    risultato = estrai_distinta(jpeg_grande(), "image/jpeg", client=client)
    assert len(risultato.giocatori) == 20
    kw = client.chiamate[0]
    assert kw["output_format"] is Distinta
    blocco = kw["messages"][0]["content"][0]
    assert blocco["type"] == "image" and blocco["source"]["media_type"] == "image/jpeg"


def test_estrai_pdf_come_documento():
    client = FakeClient(parsed=distinta())
    estrai_distinta(b"%PDF-1.4 finto", "application/pdf", client=client)
    assert client.chiamate[0]["messages"][0]["content"][0]["type"] == "document"


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_estrai_errori(stop):
    with pytest.raises(LetturaFallita):
        estrai_distinta(b"%PDF", "application/pdf", client=FakeClient(stop_reason=stop))


def test_api_richiede_password_e_restituisce_avvisi(monkeypatch):
    monkeypatch.setenv("APP_USER", "arbitro")
    monkeypatch.setenv("APP_PASSWORD", "segreta")
    monkeypatch.setattr(main, "estrai_distinta", lambda dati, ct: distinta())
    c = TestClient(main.app)
    assert c.get("/").status_code == 401
    assert c.get("/", auth=("arbitro", "sbagliata")).status_code == 401
    r = c.post("/api/estrai", auth=("arbitro", "segreta"),
               files={"file": ("d.jpg", jpeg_grande(), "image/jpeg")})
    assert r.status_code == 200
    assert r.json()["distinta"]["giocatori"][0] == {"numero": 1, "cognome": "ROSSI1", "nome": "MARIO", "dubbi": []}
    assert r.json()["avvisi"] == []
    r = c.post("/api/estrai", auth=("arbitro", "segreta"), files={"file": ("x.txt", b"ciao", "text/plain")})
    assert r.status_code == 415
