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


def giocatore(numero, cognome="ROSSI", nome="MARIO", data="01/01/2000", dubbi=None):
    return Giocatore(testo_originale=f"{cognome} {nome}", numero=numero, cognome=cognome, nome=nome, data_nascita=data,
                     riserva=numero is not None and numero > 11, dubbi=dubbi or [])


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
        giocatore(10, "ROSA", "LUCIA", data="31/02/2001"),
        giocatore(11, "BLU", "ELSA", data=None),
    ]
    testo = "\n".join(controlla(distinta(g)))
    assert "Numero 4 ripetuto 2 volte" in testo
    assert "BIANCHI LUCA compare 2 volte" in testo
    assert "NERI PAOLO: numero mancante" in testo
    assert "GIALLI: cognome o nome mancante" in testo
    assert "nome poco leggibile" in testo
    assert "ROSA LUCIA: data di nascita non valida" in testo
    assert "BLU ELSA: data di nascita mancante" in testo


def test_regola_due_parole_e_divisione_da_verificare():
    letti = [
        Giocatore(testo_originale="HOXHA GANI", numero=11, cognome="GANI", nome="HOXHA",
                  data_nascita="16/08/2002", riserva=False, dubbi=[]),
        Giocatore(testo_originale="AMOAF OBAMFO MICHAEL", numero=5, cognome="AMOAF", nome="OBAMFO MICHAEL",
                  data_nascita="07/08/2005", riserva=False, dubbi=[]),
        Giocatore(testo_originale="DAL CERO ALESSANDRO", numero=18, cognome="DAL", nome="CERO",
                  data_nascita="06/11/2004", riserva=True, dubbi=[]),
    ]
    risultato = estrai_distinta(b"%PDF", "application/pdf", client=FakeClient(parsed=distinta(letti)))
    hoxha, amoaf, dal_cero = risultato.giocatori
    assert (hoxha.cognome, hoxha.nome) == ("HOXHA", "GANI")              # due parole: la prima è il cognome
    assert (amoaf.cognome, amoaf.nome) == ("AMOAF", "OBAMFO MICHAEL")    # tre parole: resta la lettura
    avvisi = controlla(risultato)
    assert any("DAL CERO" in a and "divisione cognome/nome" in a for a in avvisi)  # parola persa
    assert not any("AMOAF" in a for a in avvisi)


def test_primi_11_titolari_qualunque_numero():
    numeri = [1, 2, 13, 4, 5, 16, 7, 8, 9, 10, 11, 3, 6, 12]       # 13 e 16 tra i titolari, 3 e 6 riserve
    letti = [Giocatore(testo_originale=f"G{n} X", numero=n, cognome=f"G{n}", nome="X", data_nascita="01/01/2000",
                       riserva=i >= 11, dubbi=[]) for i, n in enumerate(numeri)]
    letti[2].riserva = True                                          # (R) letta per errore su un titolare
    risultato = estrai_distinta(b"%PDF", "application/pdf", client=FakeClient(parsed=distinta(letti)))
    titolari = [g.numero for g in risultato.giocatori if not g.riserva]
    riserve = [g.numero for g in risultato.giocatori if g.riserva]
    assert titolari == [1, 2, 13, 4, 5, 16, 7, 8, 9, 10, 11] and riserve == [3, 6, 12]
    avvisi = controlla(risultato)
    assert any("G13 X" in a and "3° nella lista: considerato titolare" in a for a in avvisi)
    assert sum("sigla (R)" in a for a in avvisi) == 1


def test_meno_di_11_giocatori():
    assert any("Solo 7 giocatori" in a for a in controlla(distinta([giocatore(i, f"R{i}") for i in range(1, 8)])))


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
    assert r.json()["distinta"]["giocatori"][0] == {"testo_originale": "ROSSI1 MARIO", "numero": 1, "cognome": "ROSSI1", "nome": "MARIO",
                                                    "data_nascita": "01/01/2000", "riserva": False, "dubbi": []}
    assert r.json()["avvisi"] == []
    r = c.post("/api/estrai", auth=("arbitro", "segreta"), files={"file": ("x.txt", b"ciao", "text/plain")})
    assert r.status_code == 415
