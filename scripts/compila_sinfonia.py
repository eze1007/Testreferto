"""Compila le Liste Gara di Sinfonia4You partendo dal JSON scaricato dal pannello.

Uso:
  python -m scripts.compila_sinfonia liste_gara.json --gara "SAN GIOVANNI ILARIONE"

liste_gara.json contiene le due squadre ({"casa": ..., "ospite": ...}) e vengono compilate
entrambe le colonne. Il browser si apre visibile. Alla fine viene premuto "Salva Tutto" (mai
"Invia al G.S.") e il browser resta aperto per il controllo. Credenziali da SINFONIA_USER /
SINFONIA_PASSWORD (file .env), altrimenti vengono chieste a terminale.
"""

import argparse
import getpass
import json
import os
from datetime import datetime
from pathlib import Path

from app.compilazione import NOMI_LATO, compila
from app.schema import Distinta

ICONE = {"selezionato": "OK ", "aggiunto": "NEW", "da_verificare": "???", "errore": "ERR"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", type=Path, help="File liste_gara.json scaricato dal pannello")
    ap.add_argument("--gara", required=True, help="Parole che identificano la gara nella lista, es. il nome di una squadra")
    ap.add_argument("--headless", action="store_true", help="Browser invisibile (solo per prove)")
    args = ap.parse_args()

    contenuto = json.loads(args.json.read_text(encoding="utf-8"))
    squadre = {lato: Distinta.model_validate(contenuto[lato]) for lato in ("casa", "ospite") if lato in contenuto}
    if not squadre:
        raise SystemExit("Il file non contiene né 'casa' né 'ospite'.")
    utente = os.environ.get("SINFONIA_USER") or input("Utente Sinfonia4You: ")
    password = os.environ.get("SINFONIA_PASSWORD") or getpass.getpass("Password: ")
    debug = Path("esplorazione") / datetime.now().strftime("%Y%m%d-%H%M%S")

    def stampa(lato, e):
        g = e.giocatore
        print(f"  [{ICONE[e.stato]}] {g.numero or '?':>2} {g.cognome} {g.nome} {g.data_nascita or ''}"
              f"{' (R)' if g.riserva else ''}  {e.dettaglio}")

    risultato = compila(
        squadre, args.gara, utente, password,
        headless=args.headless, cartella_debug=debug, avanzamento=print, al_giocatore=stampa,
        alla_fine=None if args.headless else lambda page: input("\nControlla il browser. Premi Invio per chiuderlo… "),
    )
    print(f"\nIstantanee in {debug}/ (contengono dati personali: non condividerle)")
    for lato, r in risultato.report.items():
        for a in r.avvisi:
            print(f"ATTENZIONE ({NOMI_LATO[lato]}): {a}")
    if risultato.errore:
        raise SystemExit(f"Errore: {risultato.errore}")
    print(f"Referto salvato (bottone: {risultato.bottone_salvataggio}).")


if __name__ == "__main__":
    main()
