"""Controlli di coerenza sui dati estratti, da mostrare all'arbitro prima di usarli."""

from collections import Counter

from .schema import Distinta


def controlla(distinta: Distinta) -> list[str]:
    giocatori = distinta.giocatori
    if not giocatori:
        return ["Nessun giocatore letto: controlla la foto."]

    avvisi: list[str] = []
    numeri = Counter(g.numero for g in giocatori if g.numero is not None)
    for numero, volte in sorted(numeri.items()):
        if volte > 1:
            avvisi.append(f"Numero {numero} ripetuto {volte} volte.")

    nomi = Counter(f"{g.cognome} {g.nome}".upper() for g in giocatori)
    for nome, volte in nomi.items():
        if volte > 1:
            avvisi.append(f"{nome} compare {volte} volte.")

    for g in giocatori:
        chi = f"{g.cognome} {g.nome}".strip() or "Giocatore senza nome"
        if g.numero is None:
            avvisi.append(f"{chi}: numero mancante.")
        if not g.cognome or not g.nome:
            avvisi.append(f"{chi}: cognome o nome mancante.")
        for dubbio in g.dubbi:
            avvisi.append(f"{chi}: {dubbio}")

    avvisi.extend(distinta.note_generali)
    return avvisi
