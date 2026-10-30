"""Controlli di coerenza sui dati estratti, da mostrare all'arbitro prima di usarli."""

import re
from collections import Counter
from datetime import datetime

from .schema import Distinta

MAX_TITOLARI = 11


def controlla(distinta: Distinta) -> list[str]:
    avvisi: list[str] = []
    giocatori = distinta.giocatori

    if not giocatori:
        return ["Nessun giocatore letto: controlla la foto."]

    titolari = [g for g in giocatori if g.ruolo == "titolare"]
    if len(titolari) != MAX_TITOLARI:
        avvisi.append(f"Titolari letti: {len(titolari)} (attesi {MAX_TITOLARI}).")
    if not any(g.portiere for g in titolari):
        avvisi.append("Nessun portiere (P) tra i titolari.")

    capitani = [g.cognome_nome for g in giocatori if g.capitano == "C"]
    if len(capitani) != 1:
        avvisi.append(f"Capitani (C) trovati: {len(capitani)} (atteso 1).")
    vice = [g.cognome_nome for g in giocatori if g.capitano == "V"]
    if len(vice) > 1:
        avvisi.append(f"Vice capitani (V) trovati: {len(vice)}.")

    numeri = Counter(g.numero_maglia for g in giocatori if g.numero_maglia is not None)
    for numero, volte in sorted(numeri.items()):
        if volte > 1:
            avvisi.append(f"Numero di maglia {numero} ripetuto {volte} volte.")

    nomi = Counter(g.cognome_nome.strip().upper() for g in giocatori)
    for nome, volte in nomi.items():
        if volte > 1:
            avvisi.append(f"{nome} compare {volte} volte.")

    for g in giocatori:
        chi = f"Riga {g.riga} ({g.cognome_nome})"
        if g.numero_maglia is None:
            avvisi.append(f"{chi}: numero di maglia mancante.")
        if g.data_nascita is None:
            avvisi.append(f"{chi}: data di nascita mancante.")
        else:
            try:
                datetime.strptime(g.data_nascita, "%d/%m/%Y")
            except ValueError:
                avvisi.append(f"{chi}: data di nascita non valida ({g.data_nascita}).")
        if g.matricola_figc and not re.fullmatch(r"\d{5,10}", g.matricola_figc):
            avvisi.append(f"{chi}: matricola F.I.G.C. sospetta ({g.matricola_figc}).")
        for dubbio in g.dubbi:
            avvisi.append(f"{chi}: {dubbio}")

    avvisi.extend(distinta.note_generali)
    return avvisi
