"""Procedura completa sul portale finto: Liste Gara, Sostituzioni e verifica dopo il salvataggio."""

import glob
import os

import pytest

from app.compilazione import compila
from app.schema import Distinta, Giocatore, Sostituzione

from . import portale_finto

CHROMIUM = os.environ.get("CHROMIUM_PATH") or next(iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")), None)


def g(n, cognome, nome, data, riserva=False):
    return Giocatore(testo_originale=f"{cognome} {nome}", numero=n, cognome=cognome, nome=nome,
                     data_nascita=data, riserva=riserva, dubbi=[])


SQUADRE = {
    "casa": Distinta(giocatori=[g(1, "ROSSI", "MARIO", "01/01/2000")], note_generali=[]),
    "ospite": Distinta(giocatori=[g(9, "VERDI", "ANNA", "03/03/2003")], note_generali=[]),
}
SOSTITUZIONI = {
    "casa": [Sostituzione(tempo=1, minuto=20, esce=1, entra=12), Sostituzione(tempo=2, minuto=15, esce=12, entra=1)],
    "ospite": [Sostituzione(tempo=2, minuto=3, esce=9, entra=10)],
}


@pytest.fixture
def esegui(monkeypatch):
    if CHROMIUM:
        monkeypatch.setenv("CHROMIUM_PATH", CHROMIUM)
    portale_finto.SALVATAGGI.clear()

    def avvia():
        passi = []
        r = compila(SQUADRE, "tezze brendola", "arbitro123", "segreta", avanzamento=passi.append,
                    prepara_pagina=portale_finto.installa,
                    sostituzioni={lato: [s.model_copy() for s in elenco] for lato, elenco in SOSTITUZIONI.items()})
        return r, passi

    return avvia


def test_sostituzioni_salvate_e_verificate(esegui):
    r, passi = esegui()
    assert r.errore is None
    assert [e.stato for e in r.sostituzioni["casa"]] == ["inserita", "inserita"]
    # Le 6 righe vuote dell'ospite sono state tolte prima di salvare.
    assert "Tolte 6 righe vuote o incomplete dalla scheda Sostituzioni." in passi
    salvate = portale_finto.SOSTITUZIONI_SALVATE
    assert salvate["casa"] == [["1", "20", "1", "12"], ["2", "15", "12", "1"]]  # la riga vecchia (3') non c'è più
    assert salvate["ospite"] == [["2", "3", "9", "10"]]
    # Il referto è stato riaperto e le sostituzioni lette dal portale coincidono.
    assert r.verifica == []
    assert "Verifica sul portale: tutte le sostituzioni inserite risultano salvate." in passi


def test_sostituzioni_perse_dal_portale_vengono_segnalate(esegui, monkeypatch):
    monkeypatch.setattr(portale_finto, "PERDI_SALVATAGGI", True)  # risponde OK ma non conserva nulla
    r, passi = esegui()
    assert r.errore is None
    assert r.verifica == [
        "squadra di casa: sul portale non risultano salvate 20' del 1° t. esce 1 entra 12; 15' del 2° t. esce 12 entra 1.",
        "squadra ospite: sul portale non risultano salvate 3' del 2° t. esce 9 entra 10.",
    ]
    assert any(p.startswith("ATTENZIONE: squadra di casa: sul portale non risultano salvate") for p in passi)


# --- allegati ------------------------------------------------------------------------------------

def _file(formato: str) -> bytes:
    import io

    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (1240, 1754), "white").save(out, format=formato)
    return out.getvalue()


def test_procedura_completa_con_allegati(esegui, monkeypatch):
    file = {"casa": (_file("JPEG"), "image/jpeg"), "ospite": (_file("PNG"), "image/png"),
            "rapportino": (_file("PDF"), "application/pdf")}
    passi, esiti = [], []
    if CHROMIUM:
        monkeypatch.setenv("CHROMIUM_PATH", CHROMIUM)
    r = compila(SQUADRE, "tezze brendola", "arbitro123", "segreta", avanzamento=passi.append,
                prepara_pagina=portale_finto.installa, allegati=file, all_allegato=esiti.append,
                sostituzioni={lato: [s.model_copy() for s in elenco] for lato, elenco in SOSTITUZIONI.items()})
    assert r.errore is None
    assert [(e.descrizione, e.stato) for e in r.allegati] == [
        ("Distinta squadra di casa", "caricato"), ("Distinta squadra ospite", "caricato"),
        ("Rapportino di fine gara", "caricato")]
    assert [e.stato for e in esiti] == ["caricato"] * 3          # anche durante, per la pagina
    assert [(a["tipo"], a["squadra"], a["mime"]) for a in portale_finto.ALLEGATI_CARICATI] == [
        ("1", "1001", "image/jpeg"), ("1", "2001", "image/jpeg"), ("3", "0", "image/jpeg")]
    assert "Allegati: 3 caricati, 0 già presenti, 0 con errori." in passi
    # Dopo gli allegati la verifica delle sostituzioni c'è ancora.
    assert r.verifica == [] and "Verifica sul portale: tutte le sostituzioni inserite risultano salvate." in passi
    assert passi.index("Allegati: 3 caricati, 0 già presenti, 0 con errori.") < passi.index(
        "Verifica: riapro il referto come è salvato sul portale…")


def test_allegati_senza_sostituzioni_e_file_non_valido(monkeypatch):
    if CHROMIUM:
        monkeypatch.setenv("CHROMIUM_PATH", CHROMIUM)
    passi = []
    r = compila(SQUADRE, "tezze brendola", "arbitro123", "segreta", avanzamento=passi.append,
                prepara_pagina=portale_finto.installa,
                allegati={"casa": (_file("JPEG"), "image/jpeg"), "rapportino": (b"non leggibile", "image/jpeg")})
    assert r.errore is None
    stati = {e.descrizione: (e.stato, e.dettaglio) for e in r.allegati}
    assert stati["Distinta squadra di casa"] == ("caricato", "Allegato caricato correttamente.")
    assert stati["Rapportino di fine gara"][0] == "errore"
    assert "immagine o un PDF leggibile" in stati["Rapportino di fine gara"][1]
    assert "Distinta squadra ospite" not in stati           # non caricata nella pagina: niente da allegare
    assert [(a["tipo"], a["squadra"]) for a in portale_finto.ALLEGATI_CARICATI] == [("1", "1001")]
    assert r.verifica is None                                 # nessuna sostituzione, nessuna verifica
