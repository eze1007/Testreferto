"""Rapportino di fine gara: lettura delle sostituzioni e controlli (dati del Tezze-Brendola)."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.checks import controlla_sostituzioni, ordine_cronologico
from app.extract import LetturaFallita, estrai_rapportino
from app.schema import Distinta, Giocatore, Rapportino, Sostituzione


def s(tempo, minuto, esce, entra, dubbi=()):
    return Sostituzione(tempo=tempo, minuto=minuto, esce=esce, entra=entra, dubbi=list(dubbi))


def distinta(titolari, riserve):
    g = lambda n, r: Giocatore(testo_originale=f"G{n} X", numero=n, cognome=f"G{n}", nome="X",
                               data_nascita="01/01/2012", riserva=r, dubbi=[])
    return Distinta(giocatori=[g(n, False) for n in titolari] + [g(n, True) for n in riserve], note_generali=[])


TEZZE = distinta(range(1, 12), range(12, 20))
BRENDOLA = distinta([1, 2, 3, 4, 5, 6, 7, 8, 9, 13, 14], [15, 16, 17, 18, 10, 11])

# Come scritte sul rapportino del 31/10, con gli errori del dirigente.
RAPPORTINO_TEZZE = [s(1, 25, 6, 17), s(2, 17, 9, 13), s(2, 19, 10, 14), s(2, 13, 13, 16), s(2, 25, 6, 18)]


def _testi(avvisi):
    return [a["testo"] for a in avvisi]


def test_sostituzioni_corrette_nessun_avviso():
    sost = [s(1, 25, 6, 17), s(2, 17, 9, 13), s(2, 19, 10, 14), s(2, 33, 13, 16), s(2, 25, 7, 18)]
    assert controlla_sostituzioni(sost, TEZZE) == []


def test_errori_del_rapportino_tezze():
    avvisi = controlla_sostituzioni(RAPPORTINO_TEZZE, TEZZE)
    assert _testi(avvisi) == [
        # in ordine di tempo il 13 esce al 13' prima di entrare al 17' (il minuto giusto era 33')
        "13' del 2° t.: esce il n. 13, ma è una riserva non ancora entrata.",
        # il 6 è già uscito nel 1° tempo: probabilmente era il 7
        "25' del 2° t.: esce il n. 6, ma non è in campo (uscito al 25' del 1° t.).",
    ]
    assert [a["riga"] for a in avvisi] == [3, 4]  # indice della riga sul foglio, per evidenziarla


def test_ordine_cronologico_con_parita_nell_ordine_del_foglio():
    assert ordine_cronologico(RAPPORTINO_TEZZE) == [0, 3, 1, 2, 4]
    assert ordine_cronologico([s(2, 1, 8, 15), s(2, 1, 11, 16), s(1, 30, 3, 17)]) == [2, 0, 1]


def test_numero_non_in_distinta_e_titolare_che_entra():
    avvisi = _testi(controlla_sostituzioni([s(2, 1, 8, 13), s(2, 5, 3, 40)], BRENDOLA))
    assert "1' del 2° t.: entra il n. 13, ma è già in campo (titolare)." in avvisi
    assert "5' del 2° t.: il n. 40 non è in distinta." in avvisi


def test_rientro_ammesso_ma_segnalato():
    avvisi = _testi(controlla_sostituzioni([s(1, 10, 6, 12), s(2, 5, 12, 6)], TEZZE))
    assert avvisi == ["5' del 2° t.: rientra il n. 6 (uscito al 10' del 1° t.). Controlla che sia giusto."]


def test_dati_mancanti_dubbi_e_stesso_numero():
    avvisi = _testi(controlla_sostituzioni([s(None, 20, 6, None, dubbi=["minuto 20 o 28"]), s(2, 3, 5, 5)], TEZZE))
    assert "20' del ?° t.: minuto 20 o 28" in avvisi
    assert "20' del ?° t.: manca il tempo, chi entra." in avvisi
    assert "3' del 2° t.: esce ed entra lo stesso n. 5." in avvisi


def test_senza_distinta_si_deduce_dalla_prima_comparsa():
    # Senza distinta il 13, che esce per primo, si considera in campo: poi rientra al 17'.
    assert _testi(controlla_sostituzioni(RAPPORTINO_TEZZE)) == [
        "17' del 2° t.: rientra il n. 13 (uscito al 13' del 2° t.). Controlla che sia giusto.",
        "25' del 2° t.: esce il n. 6, ma non è in campo (uscito al 25' del 1° t.).",
    ]


# --- lettura -------------------------------------------------------------------------------

class FakeClient:
    def __init__(self, stop_reason="end_turn", parsed=None):
        self.chiamate = []
        resp = SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed)
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=lambda **kw: (self.chiamate.append(kw), resp)[1]))


def test_estrai_rapportino_anthropic(monkeypatch):
    monkeypatch.delenv("YEPAPI_API_KEY", raising=False)
    letto = Rapportino(casa=RAPPORTINO_TEZZE, ospite=[s(2, 1, 8, 13)], note_generali=[])
    client = FakeClient(parsed=letto)
    r = estrai_rapportino(b"%PDF-1.4 finto", "application/pdf", client=client)
    assert r == letto
    kw = client.chiamate[0]
    assert kw["output_format"] is Rapportino
    assert "Società ospitante" in kw["system"] and "esce il n." in kw["system"]
    with pytest.raises(LetturaFallita):
        estrai_rapportino(b"%PDF", "application/pdf", client=FakeClient(stop_reason="refusal"))


def test_estrai_rapportino_yepapi(monkeypatch):
    import httpx
    from app import extract

    inviato = {}
    risposta = {"casa": [{"tempo": 1, "minuto": 25, "esce": 6, "entra": 17, "dubbi": []}],
                "ospite": [{"tempo": 2, "minuto": None, "esce": 7, "entra": 15, "dubbi": ["minuto illeggibile"]}],
                "note_generali": []}

    def server(req):
        inviato.update(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(risposta)}, "finish_reason": "stop"}]})

    monkeypatch.setenv("YEPAPI_API_KEY", "yep_sk_prova")
    http = httpx.Client(transport=httpx.MockTransport(server))
    monkeypatch.setattr(extract.httpx, "Client", lambda **kw: http)
    from tests.test_app import jpeg_grande
    r = estrai_rapportino(jpeg_grande(), "image/jpeg")
    assert r.casa == [s(1, 25, 6, 17)] and r.ospite[0].minuto is None
    assert "Società ospitata" in inviato["messages"][0]["content"]
    assert '"casa"' in inviato["messages"][1]["content"][-1]["text"]


def test_api_rapportino_e_controllo(monkeypatch):
    monkeypatch.setenv("APP_USER", "arbitro")
    monkeypatch.setenv("APP_PASSWORD", "segreta")
    monkeypatch.setattr(main, "estrai_rapportino",
                        lambda dati, ct: Rapportino(casa=RAPPORTINO_TEZZE, ospite=[], note_generali=[]))
    c = TestClient(main.app)
    auth = ("arbitro", "segreta")
    r = c.post("/api/rapportino", auth=auth, files={"file": ("r.jpg", b"x", "image/jpeg")})
    assert r.status_code == 200 and r.json()["rapportino"]["casa"][0] == {
        "tempo": 1, "minuto": 25, "esce": 6, "entra": 17, "dubbi": []}
    assert c.post("/api/rapportino", auth=auth, files={"file": ("r.txt", b"x", "text/plain")}).status_code == 415

    corpo = {"casa": {"sostituzioni": r.json()["rapportino"]["casa"], "distinta": TEZZE.model_dump()},
             "ospite": {"sostituzioni": [], "distinta": None}}
    v = c.post("/api/controlla-sostituzioni", auth=auth, json=corpo).json()
    assert len(v["casa"]) == 2 and v["ospite"] == []
