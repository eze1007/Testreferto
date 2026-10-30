"""Compila le Liste Gara di Sinfonia4You partendo dal JSON scaricato dal pannello.

Uso:
  python -m scripts.compila_sinfonia distinta.json --gara "SAN GIOVANNI ILARIONE" --lato ospite

Il browser si apre visibile. Alla fine il referto viene salvato (mai inviato definitivamente)
e il browser resta aperto per il controllo. Credenziali da SINFONIA_USER / SINFONIA_PASSWORD (file .env),
altrimenti vengono chieste a terminale.
"""

import argparse
import getpass
import os
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.schema import Distinta
from app.sinfonia import Sinfonia

ICONE = {"selezionato": "OK ", "aggiunto": "NEW", "da_verificare": "???", "errore": "ERR"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", type=Path, help="File distinta.json scaricato dal pannello")
    ap.add_argument("--gara", required=True, help="Parole che identificano la gara nella lista, es. il nome di una squadra")
    ap.add_argument("--lato", required=True, choices=["casa", "ospite"], help="Squadra della distinta")
    ap.add_argument("--headless", action="store_true", help="Browser invisibile (solo per prove)")
    args = ap.parse_args()

    distinta = Distinta.model_validate_json(args.json.read_text(encoding="utf-8"))
    utente = os.environ.get("SINFONIA_USER") or input("Utente Sinfonia4You: ")
    password = os.environ.get("SINFONIA_PASSWORD") or getpass.getpass("Password: ")
    debug = Path("esplorazione") / datetime.now().strftime("%Y%m%d-%H%M%S")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, executable_path=os.environ.get("CHROMIUM_PATH"))
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        s4y = Sinfonia(page, cartella_debug=debug)
        try:
            s4y.login(utente, password)
            s4y.apri_gara(args.gara)
            s4y.svolgimento_e_sicurezza()
            report = s4y.compila_lista(distinta.giocatori, args.lato)
            salvato = s4y.salva()
        except Exception:
            s4y.istantanea("errore")
            print(f"\nErrore. Screenshot e pagine salvati in {debug}/")
            raise
        finally:
            print(f"Istantanee in {debug}/ (contengono dati personali: non condividerle)")

        print()
        for e in report.esiti:
            g = e.giocatore
            print(f"[{ICONE[e.stato]}] {g.numero or '?':>2} {g.cognome} {g.nome} {g.data_nascita or ''}"
                  f"{' (R)' if g.riserva else ''}  {e.dettaglio}")
        for a in report.avvisi:
            print("ATTENZIONE:", a)
        print(f"\nReferto salvato (bottone: {salvato}). Controlla la pagina nel browser.")
        if not args.headless:
            input("Premi Invio per chiudere il browser… ")
        browser.close()


if __name__ == "__main__":
    main()
