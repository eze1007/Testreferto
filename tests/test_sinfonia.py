"""Test della compilazione su una copia finta del portale (nessun accesso a Sinfonia4You)."""

import glob
import os

import pytest
from playwright.sync_api import sync_playwright

from app.schema import Giocatore
from app.sinfonia import Sinfonia, scegli_opzione

from . import portale_finto


def g(numero, cognome, nome, data, riserva=False):
    return Giocatore(testo_originale=f"{cognome} {nome}", numero=numero, cognome=cognome, nome=nome, data_nascita=data, riserva=riserva, dubbi=[])


OPZIONI = ["", "ROSSI MARIO (01/01/2000 - ID 111)", "ROSSI MARIO (01/01/2000 - ID 222)",
           "ROSSI MARIO (05/05/1990 - ID 333)", "ANDREOLI NICOLÒ (02/02/2002 - ID 444)"]


def test_omonimi_stessa_data_sceglie_il_primo():
    assert scegli_opzione(g(1, "ROSSI", "MARIO", "01/01/2000"), OPZIONI).indice == 1


def test_omonimo_con_altra_data():
    assert scegli_opzione(g(1, "ROSSI", "MARIO", "05/05/1990"), OPZIONI).indice == 3


def test_nome_simile_o_data_diversa_crea_nuovo():
    for cognome, nome, data in [("ANDREOLLI", "NICOLO", "02/02/2002"),  # una lettera diversa
                                ("ROSSI", "MARIO", "09/09/1999")]:      # data diversa
        assert scegli_opzione(g(1, cognome, nome, data), OPZIONI).stato == "nuovo"


def test_accenti_non_contano():
    assert scegli_opzione(g(1, "ANDREOLI", "NICOLO", "02/02/2002"), OPZIONI).indice == 4


def test_ordine_apostrofi_e_spazi_non_contano():
    opzioni = ["", "NICOLA CUNEGATTI (06/02/2003 - ID 1)", "D'ANGELO MARCO (01/01/2001 - ID 2)",
               "DALCERO ALESSANDRO (06/11/2004 - ID 3)", "ANDREOLLI NICOLO' (04/04/2009 - ID 4)"]
    assert scegli_opzione(g(1, "CUNEGATTI", "NICOLA", "06/02/2003"), opzioni).indice == 1  # ordine invertito
    assert scegli_opzione(g(1, "D ANGELO", "MARCO", "01/01/2001"), opzioni).indice == 2    # apostrofo
    assert scegli_opzione(g(1, "DANGELO", "MARCO", "01/01/2001"), opzioni).indice == 2
    assert scegli_opzione(g(1, "DAL CERO", "ALESSANDRO", "06/11/2004"), opzioni).indice == 3  # spazio
    assert scegli_opzione(g(1, "ANDREOLLI", "NICOLÒ", "04/04/2009"), opzioni).indice == 4  # accento come apostrofo


def test_lettera_mancante_e_un_altro_giocatore():
    opzioni = ["CUNEGATI NICOLA (06/02/2003 - ID 1)", "CUNEGATTI NICOL (06/02/2003 - ID 2)"]
    assert scegli_opzione(g(1, "CUNEGATTI", "NICOLA", "06/02/2003"), opzioni).stato == "nuovo"


def test_maiuscole_e_spazi_non_contano():
    assert scegli_opzione(g(1, "rossi ", " mario", "01/01/2000"), OPZIONI).indice == 1


def test_giocatore_nuovo_e_data_mancante():
    assert scegli_opzione(g(1, "NERI", "PAOLO", "03/03/2003"), OPZIONI).stato == "nuovo"
    assert scegli_opzione(g(1, "NERI", "PAOLO", None), OPZIONI).stato == "da_verificare"


@pytest.fixture
def page():
    exe = os.environ.get("CHROMIUM_PATH") or next(iter(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")), None)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe)
        pagina = browser.new_page(viewport={"width": 1400, "height": 1000})
        portale_finto.installa(pagina)
        yield pagina
        browser.close()


def leggi_colonna(page, lato):
    """(numero, nominativo, documento) di ogni riga compilata della colonna."""
    return page.evaluate(
        """(lato) => [...document.querySelectorAll('select.gioc.' + lato)].map((s) => {
             const riga = s.parentElement, doc = riga.nextElementSibling;
             return [riga.querySelector('select').value, s.value, doc.querySelector('input').value,
                     riga.querySelectorAll('select')[2].value];
           })""",
        lato,
    )


def test_percorso_completo(page):
    s4y = Sinfonia(page)
    with pytest.raises(RuntimeError, match="Login non riuscito"):
        s4y.login("arbitro123", "sbagliata")
    s4y.login("arbitro123", "segreta")
    s4y.apri_gara("san giovanni ilarione")
    s4y.svolgimento_e_sicurezza()

    giocatori = [
        g(7, "ROSSI", "MARIO", "01/01/2000"),
        g(9, "DAL CERO", "ALESSANDRO", "06/11/2004"),
        g(10, "NERI", "PAOLO", "03/03/2003"),            # non in archivio: va aggiunto
        g(11, "BIANCHI", "LUCAS", "02/02/2001"),         # simile a BIANCHI LUCA: va creato
        g(14, "VERDI", "ANNA", "03/03/2003", riserva=True),
    ]
    report = s4y.compila_lista(giocatori, "ospite")

    assert [e.stato for e in report.esiti] == ["selezionato", "selezionato", "aggiunto", "aggiunto", "selezionato"]
    assert report.avvisi == []

    ospite = leggi_colonna(page, "ospite")
    assert ospite[0][:2] == ["7", "ROSSI MARIO (01/01/2000 - ID 111)"]
    assert ospite[1][:2] == ["9", "DAL CERO ALESSANDRO (06/11/2004 - ID 444)"]
    assert ospite[2][:2] == ["10", "NERI PAOLO (03/03/2003 - ID 900)"]
    assert ospite[3][:2] == ["11", "BIANCHI LUCAS (02/02/2001 - ID 901)"]
    assert ospite[11][:2] == ["14", "VERDI ANNA (03/03/2003 - ID 555)"]  # prima riga riserve
    assert all(r[2] == "" and r[3] == "" for r in ospite)  # documenti e capitano non toccati
    assert all(r[1] == "" for r in leggi_colonna(page, "casa"))  # squadra di casa intatta

    assert s4y.salva() == "Salva Tutto"
    assert page.evaluate("[salvato, salvatoScheda, inviato]") == [True, False, False]  # mai "Invia al G.S."


def test_gara_non_trovata(page):
    s4y = Sinfonia(page)
    s4y.login("arbitro123", "segreta")
    with pytest.raises(RuntimeError, match="Gare trovate"):
        s4y.apri_gara("JUVENTUS")
