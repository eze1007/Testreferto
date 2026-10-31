"""Test con dati inventati: nessun dato reale di calciatori nel repository."""

import io
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.checks import controlla
from app.extract import LetturaFallita, estrai_distinta, normalizza_data
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


def test_divisione_cognome_nome_decisa_dal_programma():
    def letto(testo, cognome, nome, dubbi):
        return Giocatore(testo_originale=testo, numero=1, cognome=cognome, nome=nome, data_nascita="01/01/2012",
                         dubbi=dubbi)
    letti = [
        letto("HOXHA GANI", "GANI", "HOXHA", []),
        letto("YOADA MOUBARAKA", "YOADA", "MOUBARAKA", ["Divisione tra cognome e nome non certa"]),
        letto("SPOLADORE TIAGO TESFAHUN", "SPOLADORE TIAGO", "TESFAHUN",
              ["Divisione tra cognome e nome per nome doppio/composto non certa"]),
        letto("DAL CERO ALESSANDRO", "DAL", "CERO ALESSANDRO", []),
        letto("DI BARI ANTONIO", "DI", "BARI ANTONIO", ["seconda lettera del nome poco leggibile"]),
    ]
    risultato = estrai_distinta(b"%PDF", "application/pdf", client=FakeClient(parsed=distinta(letti)))
    assert [(g.cognome, g.nome) for g in risultato.giocatori] == [
        ("HOXHA", "GANI"), ("YOADA", "MOUBARAKA"), ("SPOLADORE", "TIAGO TESFAHUN"),
        ("DAL CERO", "ALESSANDRO"), ("DI BARI", "ANTONIO")]
    avvisi = controlla(risultato)
    assert not any("ivisione" in a for a in avvisi)                    # niente falsi allarmi sulla divisione
    assert any("seconda lettera del nome poco leggibile" in a for a in avvisi)  # i dubbi veri restano


def test_primi_11_titolari_qualunque_numero():
    numeri = [1, 2, 13, 4, 5, 16, 7, 8, 9, 10, 11, 3, 6, 12]       # 13 e 16 tra i primi 11
    letti = [Giocatore(testo_originale=f"G{n} X", numero=n, cognome=f"G{n}", nome="X", data_nascita="01/01/2000",
                       dubbi=[]) for n in numeri]
    risultato = estrai_distinta(b"%PDF", "application/pdf", client=FakeClient(parsed=distinta(letti)))
    assert [g.numero for g in risultato.giocatori if not g.riserva] == [1, 2, 13, 4, 5, 16, 7, 8, 9, 10, 11]
    assert [g.numero for g in risultato.giocatori if g.riserva] == [3, 6, 12]


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


def test_yepapi(monkeypatch):
    import httpx
    from app import extract

    inviato = {}
    risposta = {"giocatori": [
        {"testo_originale": "HOXHA GANI", "numero": 11, "cognome": "GANI", "nome": "HOXHA",
         "data_nascita": "16/08/2002", "dubbi": []},
        {"testo_originale": "NERI", "numero": 7, "cognome": "NERI", "nome": None, "data_nascita": None, "dubbi": []},
    ], "note_generali": []}

    def server(req):
        inviato.update(json.loads(req.content), chiave=req.headers["x-api-key"])
        testo = "Ecco i dati:\n```json\n" + json.dumps(risposta) + "\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": testo}, "finish_reason": "stop"}]})

    monkeypatch.setenv("YEPAPI_API_KEY", "yep_sk_prova")
    monkeypatch.delenv("YEPAPI_MODEL", raising=False)
    http = httpx.Client(transport=httpx.MockTransport(server))
    monkeypatch.setattr(extract.httpx, "Client", lambda **kw: http)
    d = estrai_distinta(jpeg_grande(), "image/jpeg")
    assert inviato["chiave"] == "yep_sk_prova" and inviato["model"] == "anthropic/claude-haiku-5.5"
    assert inviato["messages"][1]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert (d.giocatori[0].cognome, d.giocatori[0].nome) == ("HOXHA", "GANI")   # regola delle due parole
    assert d.giocatori[1].nome == ""                                           # nome illeggibile: niente crash
    assert any("NERI: cognome o nome mancante" in a for a in controlla(d))


def test_yepapi_errore(monkeypatch):
    import httpx
    from app import extract

    monkeypatch.setenv("YEPAPI_API_KEY", "sbagliata")
    http = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(401, json={"error": "INVALID_API_KEY"})))
    monkeypatch.setattr(extract.httpx, "Client", lambda **kw: http)
    with pytest.raises(LetturaFallita, match="401"):
        estrai_distinta(jpeg_grande(), "image/jpeg")


def test_date_con_anno_a_due_cifre():
    assert normalizza_data("15.01.12", 2026) == "15/01/2012"
    assert normalizza_data("23-08-12", 2026) == "23/08/2012"
    assert normalizza_data("1/2/98", 2026) == "01/02/1998"
    assert normalizza_data("05/07/2012", 2026) == "05/07/2012"


def test_maiuscole_minuscole_e_date_dopo_la_lettura():
    letti = [Giocatore(testo_originale="Dalla Pozza Giovanni", numero=15, cognome="Dalla Pozza", nome="Giovanni",
                       data_nascita="29.07.13", dubbi=[]),
             Giocatore(testo_originale="Hena Andrea", numero=9, cognome="Andrea", nome="Hena",
                       data_nascita="29/06/13", dubbi=[])]
    risultato = estrai_distinta(b"%PDF", "application/pdf", client=FakeClient(parsed=distinta(letti)))
    dalla_pozza, hena = risultato.giocatori
    assert (dalla_pozza.cognome, dalla_pozza.nome, dalla_pozza.data_nascita) == ("DALLA POZZA", "GIOVANNI", "29/07/2013")
    assert (hena.cognome, hena.nome, hena.data_nascita) == ("HENA", "ANDREA", "29/06/2013")
    assert not any("divisione" in a for a in controlla(risultato))   # "Dalla Pozza" = "DALLA POZZA"


def test_aggiunti_a_penna_in_fondo_sono_riserve():
    # Come la distinta del Brendola: la riga cancellata non viene letta, il 10 e l'11 sono scritti a
    # penna in fondo alla lista. Titolari = primi 11 della lista, quindi 10 e 11 restano riserve.
    numeri = [1, 2, 3, 4, 5, 6, 7, 8, 9, 13, 14, 15, 16, 17, 18, 10, 11]
    letti = [Giocatore(testo_originale=f"GIOCATORE N{n}", numero=n, cognome="GIOCATORE", nome=f"N{n}",
                       data_nascita="01/01/2012", dubbi=[]) for n in numeri]
    risultato = estrai_distinta(b"%PDF", "application/pdf", client=FakeClient(parsed=distinta(letti)))
    assert [g.numero for g in risultato.giocatori if not g.riserva] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 13, 14]
    assert [g.numero for g in risultato.giocatori if g.riserva] == [15, 16, 17, 18, 10, 11]
