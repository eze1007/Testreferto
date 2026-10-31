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


def compila_tre_fasi(s4y, giocatori, lato):
    s4y.libera_righe_sbagliate(giocatori, lato)
    aggiunti = s4y.aggiungi_mancanti(giocatori, lato)
    report = s4y.compila_lista(giocatori, lato, aggiunti=aggiunti)
    s4y.verifica_e_ripara(giocatori, lato)
    return report


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
    report = compila_tre_fasi(s4y, giocatori, "ospite")

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
    with pytest.raises(RuntimeError, match="Nessuna gara trovata"):
        s4y.apri_gara("JUVENTUS")


def test_numeri_alti_tra_i_titolari(page):
    s4y = Sinfonia(page)
    s4y.login("arbitro123", "segreta")
    s4y.apri_gara("sarego liona")
    s4y.svolgimento_e_sicurezza()
    nomi = ["UNO", "DUE", "SEDICI", "QUATTRO", "CINQUE", "SEI", "SETTE", "OTTO", "NOVE", "DIECI", "TREDICI"]
    titolari = [g(n, "TITOLARE", nome, "01/01/2000") for n, nome in zip((1, 2, 16, 4, 5, 6, 7, 8, 9, 10, 13), nomi)]
    riserve = [g(3, "RISERVA", "TRE", "01/01/2000", riserva=True)]
    report = compila_tre_fasi(s4y, titolari + riserve, "casa")
    assert {e.stato for e in report.esiti} == {"aggiunto"}
    casa = leggi_colonna(page, "casa")
    assert [r[0] for r in casa[:11]] == ["1", "2", "16", "4", "5", "6", "7", "8", "9", "10", "13"]
    assert casa[2][1].startswith("TITOLARE SEDICI")                      # il 16 è nelle righe dei titolari
    assert casa[11][:2] == ["3", "RISERVA TRE (01/01/2000 - ID 911)"]   # il 3 è la prima riserva


def test_login_con_finestra_di_benvenuto(page):
    s4y = Sinfonia(page)
    s4y.login("arbitro123", "segreta")      # la finestra modale "Benvenuto" viene chiusa con Ok
    assert page.get_by_text("Benvenuto su Sinfonia4You").is_visible()
    assert page.locator(".ui-dialog").count() == 0


def test_codice_di_sicurezza_senza_browser_visibile(page):
    page.unroute(portale_finto.BASE + "**")
    portale_finto.installa(page, captcha=True)
    with pytest.raises(RuntimeError, match="codice di sicurezza"):
        Sinfonia(page).login("arbitro123", "segreta")


def test_gara_gia_refertata(page):
    s4y = Sinfonia(page)
    s4y.login("arbitro123", "segreta")
    with pytest.raises(RuntimeError, match="già refertata"):
        s4y.apri_gara("montecchio")         # ha solo "i" e PDF: niente "+" da premere


def test_tipo_icona():
    tipo = Sinfonia._tipo_icona
    assert tipo("nuovo_inserimento/default.asp?id=5") == "nuovo"
    assert tipo("/img/ico_add.png") == "nuovo" and tipo("+") == "nuovo"
    assert tipo("/img/pdf.png stampa.asp?a=1+2") == "pdf"   # un + nell'indirizzo non conta
    assert tipo("/img/info.png") == "info" and tipo("/img/matita.png") == "modifica"


@pytest.mark.parametrize("gara", ["Tezze vs Brendola", "tezze", "brendol", "Calcio Tezze - Brendola"])
def test_ricerca_gara_con_una_parte_del_nome(page, gara):
    s4y = Sinfonia(page)
    s4y.login("arbitro123", "segreta")
    s4y.apri_gara(gara)       # "tezze" trova anche la gara già refertata con ALTAVILLA: vale quella col +
    assert page.get_by_text("Disputata Regolarmente").is_visible()


def test_ricerca_gara_non_trovata_o_ambigua(page):
    s4y = Sinfonia(page)
    s4y.login("arbitro123", "segreta")
    with pytest.raises(RuntimeError, match="Nessuna gara trovata"):
        s4y.apri_gara("Juventus")
    page.unroute(portale_finto.BASE + "**")
    portale_finto.installa(page)
    with pytest.raises(RuntimeError, match="Più gare da refertare"):
        s4y.apri_gara("2026")  # corrisponde a due gare con il +


@pytest.mark.parametrize("scritto, riga, atteso", [
    ("San Lazzaro", "25/10/2026 S.LAZZARO SERENISSIMA ALTAIR 430", True),
    ("Serenissima", "25/10/2026 S.LAZZARO SERENISSIMA ALTAIR 430", True),
    ("San Lazzaro vs Altair", "25/10/2026 S.LAZZARO SERENISSIMA ALTAIR 430", True),
    ("Real Lugo", "24/10/2026 REAL LUGO A.S.D. CALCIONOVOLEDO VILLAVERLA 28", True),
    ("Villaverla", "24/10/2026 REAL LUGO A.S.D. CALCIONOVOLEDO VILLAVERLA 28", True),
    ("San Pietro", "04/10/2026 MONTECCHIO S.PIETRO SAN VITALE 1995 120", True),
    ("Sarego Liona", "11/10/2026 SAN GIOVANNI ILARIONE SAREGO LIONA ACADEMY 756", True),
    ("San Zeno", "18/10/2026 RALDON SAN ZENO VERONA 1919 ARL 284", True),
    ("San Lazzaro", "18/10/2026 RALDON SAN ZENO VERONA 1919 ARL 284", False),
    ("Tezze", "25/10/2026 S.LAZZARO SERENISSIMA ALTAIR 430", False),
])
def test_ricerca_qualsiasi_squadra(scritto, riga, atteso):
    from app.sinfonia import corrisponde, parole_gara
    assert corrisponde(parole_gara(scritto), riga) is atteso


def test_entrambe_le_squadre_con_ricariche(page):
    """Il caso del test reale: casa e ospite con giocatori nuovi. Ogni "Aggiungi persona" azzera le
    scelte non salvate (come una ricarica): alla fine entrambe le colonne devono essere complete."""
    s4y = Sinfonia(page)
    s4y.login("arbitro123", "segreta")
    s4y.apri_gara("tezze")
    s4y.svolgimento_e_sicurezza()
    casa = [g(n, "CASA", nome, "01/01/2012") for n, nome in [(1, "UNO"), (2, "DUE"), (3, "TRE")]] + \
           [g(1, "ROSSI", "MARIO", "01/01/2000")]
    ospite = [g(7, "OSPITE", "SETTE", "02/02/2012"), g(9, "VERDI", "ANNA", "03/03/2003"),
              g(4, "OSPITE", "QUATTRO", "02/02/2012", riserva=True)]
    casa[3].numero = 4
    aggiunti = {"casa": s4y.aggiungi_mancanti(casa, "casa"), "ospite": s4y.aggiungi_mancanti(ospite, "ospite")}
    s4y.compila_lista(casa, "casa", aggiunti=aggiunti["casa"])
    s4y.compila_lista(ospite, "ospite", aggiunti=aggiunti["ospite"])
    s4y.verifica_e_ripara(casa, "casa")
    s4y.verifica_e_ripara(ospite, "ospite")
    c, o = leggi_colonna(page, "casa"), leggi_colonna(page, "ospite")
    assert [r[0] for r in c[:4]] == ["1", "2", "3", "4"]
    assert [r[1].split(" (")[0] for r in c[:4]] == ["CASA UNO", "CASA DUE", "CASA TRE", "ROSSI MARIO"]
    assert [r[1].split(" (")[0] for r in o[:2]] == ["OSPITE SETTE", "VERDI ANNA"]
    assert o[11][:1] == ["4"] and o[11][1].startswith("OSPITE QUATTRO")


def _entra(page):
    s4y = Sinfonia(page)
    s4y.login("arbitro123", "segreta")
    s4y.apri_gara("tezze")
    s4y.svolgimento_e_sicurezza()
    return s4y


def test_righe_con_dati_vecchi_vengono_corrette(page):
    """Da una prova precedente: nelle righe 2 e 5 ci sono giocatori che ora non c'entrano."""
    s4y = _entra(page)
    page.evaluate("""() => { const s = [...document.querySelectorAll('select.gioc.ospite')];
        s[1].selectedIndex = 3; s[4].selectedIndex = 4; }""")
    giocatori = [g(1, "ROSSI", "MARIO", "01/01/2000"), g(2, "NUOVO", "ARRIVATO", "05/05/2012")]
    compila_tre_fasi(s4y, giocatori, "ospite")
    ospite = leggi_colonna(page, "ospite")
    assert ospite[1][1].startswith("NUOVO ARRIVATO")   # al posto del giocatore vecchio
    assert ospite[4][1] == ""                         # riga in più svuotata


def test_finestra_aggiungi_con_etichette_e_calendario(page):
    """Finestra fatta diversamente: etichette <label> fuori da tabelle e un calendario che si apre
    sulla data e copre il bottone Conferma finché il campo ha il focus."""
    s4y = _entra(page)
    page.evaluate("""() => {
        document.getElementById('dlg').innerHTML = `
          <div class="titolo">Aggiungi Tesserato</div>
          <div><label>Matricola:</label> <input id="m"></div>
          <div><label>Cognome *:</label> <input id="c"></div>
          <div><label>Nome *:</label> <input id="n"></div>
          <div><label>Data di Nascita *:</label> <input id="d"> <input type="checkbox"> Sconosciuta</div>
          <div id="cal" style="display:none;position:absolute;left:0;top:0;width:100%;height:100%;background:#eee">calendario</div>
          <div class="ui-dialog-buttonpane"><button onclick="conferma()">Conferma</button></div>`;
        const d = document.getElementById('d'), cal = document.getElementById('cal');
        d.addEventListener('focus', () => { cal.style.display = 'block'; });
        d.addEventListener('keydown', (e) => { if (e.key === 'Tab') cal.style.display = 'none'; });
    }""")
    report = compila_tre_fasi(s4y, [g(8, "AMBICA", "MAURIZIO", "15/01/2012")], "ospite")
    assert [e.stato for e in report.esiti] == ["aggiunto"]
    assert leggi_colonna(page, "ospite")[0][1] == "AMBICA MAURIZIO (15/01/2012 - ID 900)"


def test_scambio_titolari_riserve_su_referto_gia_salvato(page):
    """Il caso del Brendola: da una prova precedente il referto ha 13 e 14 tra i titolari e il 10
    e l'11 tra le riserve. Ora il 10 e l'11 sono titolari e il 13 e il 14 riserve. Il portale non
    accetta lo stesso giocatore in due righe: bisogna prima liberare le righe e poi rimettere."""
    s4y = _entra(page)
    archivio = ["DIECI ANTONIO (10/10/2012 - ID 1)", "UNDICI MARCO (11/11/2012 - ID 2)",
                "TREDICI LUCA (13/01/2012 - ID 3)", "QUATTORDICI PAOLO (14/01/2012 - ID 4)"]
    page.evaluate("""(archivio) => {
        const s = [...document.querySelectorAll('select.gioc.ospite')];
        s.forEach((sel) => archivio.forEach((t) => sel.add(new Option(t))));
        const voce = (sel, t) => { sel.selectedIndex = [...sel.options].findIndex((o) => o.text === t); };
        voce(s[9], archivio[2]);  voce(s[10], archivio[3]);   // titolari 10 e 11: TREDICI e QUATTORDICI
        voce(s[11], archivio[0]); voce(s[12], archivio[1]);   // prime riserve: DIECI e UNDICI
    }""", archivio)
    titolari = [g(n, "TITOLARE", nome, "01/01/2012") for n, nome in
                zip(range(1, 10), ["UNO", "DUE", "TRE", "QUATTRO", "CINQUE", "SEI", "SETTE", "OTTO", "NOVE"])]
    titolari += [g(10, "DIECI", "ANTONIO", "10/10/2012"), g(11, "UNDICI", "MARCO", "11/11/2012")]
    riserve = [g(13, "TREDICI", "LUCA", "13/01/2012", riserva=True), g(14, "QUATTORDICI", "PAOLO", "14/01/2012", riserva=True)]
    report = compila_tre_fasi(s4y, titolari + riserve, "ospite")
    ospite = leggi_colonna(page, "ospite")
    nomi = [r[1].split(" (")[0] for r in ospite]
    assert nomi[9:11] == ["DIECI ANTONIO", "UNDICI MARCO"]             # ora titolari
    assert nomi[11:13] == ["TREDICI LUCA", "QUATTORDICI PAOLO"]        # ora riserve
    assert nomi[13:] == [""] * 7                                       # niente altro nelle riserve
    assert [ospite[i][0] for i in (9, 10, 11, 12)] == ["10", "11", "13", "14"]
    stati = {e.giocatore.cognome: e.stato for e in report.esiti}
    assert stati["DIECI"] == stati["TREDICI"] == "selezionato"         # nessun doppione in archivio
    assert not any(o.startswith("DIECI ANTONIO (10/10/2012 - ID 9") for o in s4y._opzioni("select.gioc.ospite >> nth=0"))


# --- sostituzioni ------------------------------------------------------------------------------

def sost(tempo, minuto, esce, entra):
    from app.schema import Sostituzione
    return Sostituzione(tempo=tempo, minuto=minuto, esce=esce, entra=entra)


def leggi_sostituzioni(page, corpo):
    """[tempo, minuto, numero che esce, numero che entra] delle righe compilate."""
    return page.evaluate(
        """(corpo) => [...document.querySelectorAll(`#riepilogo_sostituzioni_${corpo} > tr`)].map((tr) => {
             const v = (n) => tr.querySelector(`[name=${n}]`);
             const num = (n) => v(n).selectedOptions[0]?.dataset.numero || '';
             return [v('tempo').value, v('minuto').value, num('esce'), num('entra')];
           }).filter((r) => r[2] || r[3])""", corpo)


def test_sostituzioni_in_ordine_con_rientro_ed_errori(page):
    s4y = Sinfonia(page)
    s4y.login("arbitro123", "segreta")
    s4y.apri_gara("tezze brendola")
    elenco = [
        sost(2, 25, 7, 18),
        sost(1, 25, 6, 17),      # prima in ordine di tempo
        sost(2, 30, 17, 6),      # rientro del 6 ("* 6 - ..." nella tendina ENTRA)
        sost(2, 5, 99, 12),      # il 99 non c'è: non inserita
        sost(None, 10, 3, 13),   # incompleta: non inserita
    ]
    esiti = s4y.compila_sostituzioni(elenco, "casa")
    assert [e.stato for e in esiti] == ["inserita", "inserita", "inserita", "errore", "errore"]
    assert "il n. 99 non può uscire" in esiti[3].dettaglio and "1, 2, 3" in esiti[3].dettaglio
    assert esiti[4].dettaglio == "dati incompleti: non inserita"
    # La riga rimasta da una prova precedente (esce 2, entra 12) è stata tolta.
    assert leggi_sostituzioni(page, "casa") == [["1", "25", "6", "17"], ["2", "25", "7", "18"], ["2", "30", "17", "6"]]
    assert leggi_sostituzioni(page, "fuori") == []  # ospite intatta
    # Le righe libere (anche quella usata dal tentativo scartato) restano con tempo e minuto vuoti.
    quarta = page.locator("#riepilogo_sostituzioni_casa > tr").nth(3)
    assert [quarta.locator(f"[name={n}]").input_value() for n in ("tempo", "minuto", "esce", "entra")] == ["0"] * 4
    assert page.evaluate("[salvato, inviato]") == [False, False]  # il salvataggio lo decide la procedura


def test_piu_di_sette_sostituzioni_aggiunge_righe(page):
    s4y = Sinfonia(page)
    s4y.login("arbitro123", "segreta")
    s4y.apri_gara("tezze brendola")
    elenco = [sost(2, 1, 8, 15), sost(2, 2, 9, 16), sost(2, 3, 7, 17), sost(2, 4, 6, 18),
              sost(2, 5, 5, 10), sost(2, 6, 4, 11), sost(2, 7, 15, 8), sost(2, 8, 16, 9)]
    esiti = s4y.compila_sostituzioni(elenco, "ospite")
    assert [e.stato for e in esiti] == ["inserita"] * 8
    assert [r[2:] for r in leggi_sostituzioni(page, "fuori")] == [
        ["8", "15"], ["9", "16"], ["7", "17"], ["6", "18"], ["5", "10"], ["4", "11"], ["15", "8"], ["16", "9"]]
    assert any("7 Sostituzioni al massimo" in m for m in s4y.messaggi_portale)  # conferma accettata
    assert s4y.accetta_conferme is False
