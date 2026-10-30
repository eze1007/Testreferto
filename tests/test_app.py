"""Test con dati inventati: nessun dato reale di calciatori nel repository."""

import io
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.checks import controlla
from app.extract import LetturaFallita, estrai_distinta
from app.matching import VocePortale, abbina
from app.schema import Distinta, Giocatore


def giocatore(riga, nome, **kw):
    base = dict(riga=riga, numero_maglia=riga, cognome_nome=nome, data_nascita="01/01/2000",
                matricola_figc="1234567", ruolo="titolare" if riga <= 11 else "riserva",
                portiere=riga in (1, 12), capitano="C" if riga == 3 else None,
                documento_tipo="Tess.", documento_numero="1000000", dubbi=[])
    base.update(kw)
    return Giocatore(**base)


def distinta(giocatori=None):
    return Distinta(numero_distinta="1", squadra="ASD PROVA", codice_societa="1", gara="ASD PROVA - ASD ESEMPIO",
                    campionato="SECONDA CATEGORIA", data_ora="01/01/2026 15:30", campo="COMUNALE",
                    giocatori=giocatori if giocatori is not None else [giocatore(i, f"ROSSI MARIO{i}") for i in range(1, 21)],
                    staff=[], note_generali=[])


def test_distinta_corretta_nessun_avviso():
    assert controlla(distinta()) == []


def test_avvisi_su_errori_tipici():
    g = [giocatore(i, f"BIANCHI LUCA{i}") for i in range(1, 11)]  # solo 10 titolari
    g[4] = giocatore(5, "VERDI ANNA", numero_maglia=4, data_nascita="31/02/2001", dubbi=["cognome poco leggibile"])
    avvisi = controlla(distinta(g))
    testo = "\n".join(avvisi)
    assert "Titolari letti: 10" in testo
    assert "Numero di maglia 4 ripetuto 2 volte" in testo
    assert "data di nascita non valida" in testo
    assert "cognome poco leggibile" in testo


def test_abbinamento_omonimi_usa_data_di_nascita():
    voci = [VocePortale("A1", "ROSSI MARIO", "01/01/1990"), VocePortale("A2", "ROSSI MARIO", "05/05/2004")]
    r = abbina(giocatore(1, "ROSSI MARIO", data_nascita="05/05/2004"), voci)
    assert r.stato == "sicuro" and r.voce.id == "A2"


def test_abbinamento_nome_invertito_e_accenti():
    voci = [VocePortale("B1", "Nicolò Andreoli", "02/02/2002"), VocePortale("B2", "Gianni Neri", "03/03/2003")]
    r = abbina(giocatore(1, "ANDREOLI NICOLO", data_nascita=None), voci)
    assert r.voce.id == "B1" and r.stato == "sicuro"


def test_abbinamento_ambiguo_da_verificare():
    voci = [VocePortale("C1", "ROSSI MARIO", "01/01/1990"), VocePortale("C2", "ROSSI MARIO", "02/02/1991")]
    r = abbina(giocatore(1, "ROSSI MARIO", data_nascita=None), voci)
    assert r.stato == "da_verificare" and len(r.alternative) == 1


def test_abbinamento_non_trovato():
    r = abbina(giocatore(1, "ZANETTI PAOLO"), [VocePortale("D1", "BIANCHI LUCA")])
    assert r.stato == "non_trovato" and r.voce is None


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
    assert risultato.squadra == "ASD PROVA"
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
    assert r.json()["distinta"]["squadra"] == "ASD PROVA" and r.json()["avvisi"] == []
    r = c.post("/api/estrai", auth=("arbitro", "segreta"), files={"file": ("x.txt", b"ciao", "text/plain")})
    assert r.status_code == 415
