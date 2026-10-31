"""Controlli di coerenza sui dati estratti, da mostrare all'arbitro prima di usarli."""

from collections import Counter
from datetime import datetime

from .schema import Distinta, Sostituzione


def controlla(distinta: Distinta) -> list[str]:
    giocatori = distinta.giocatori
    if not giocatori:
        return ["Nessun giocatore letto: controlla la foto."]

    avvisi: list[str] = []
    if len(giocatori) < 11:
        avvisi.append(f"Solo {len(giocatori)} giocatori letti: i titolari dovrebbero essere 11.")
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
        if g.data_nascita is None:
            avvisi.append(f"{chi}: data di nascita mancante.")
        else:
            try:
                datetime.strptime(g.data_nascita, "%d/%m/%Y")
            except ValueError:
                avvisi.append(f"{chi}: data di nascita non valida ({g.data_nascita}).")
        for dubbio in g.dubbi:
            avvisi.append(f"{chi}: {dubbio}")

    avvisi.extend(distinta.note_generali)
    return avvisi


# --- Sostituzioni del rapportino di fine gara -----------------------------------------------

def quando(s: Sostituzione) -> str:
    return f"{s.minuto if s.minuto is not None else '?'}' del {s.tempo if s.tempo is not None else '?'}° t."


def ordine_cronologico(sostituzioni: list[Sostituzione]) -> list[int]:
    """Indici delle sostituzioni in ordine di tempo e minuto (a parità, l'ordine del foglio).
    Il portale le vuole in quest'ordine: ogni sostituzione cambia chi può uscire ed entrare dopo."""
    return sorted(range(len(sostituzioni)),
                  key=lambda i: (sostituzioni[i].tempo or 99, sostituzioni[i].minuto or 999))


def completa(s: Sostituzione) -> bool:
    return None not in (s.tempo, s.minuto, s.esce, s.entra)


def controlla_sostituzioni(sostituzioni: list[Sostituzione], distinta: Distinta | None = None) -> list[dict]:
    """Ripercorre le sostituzioni in ordine di tempo e segnala quelle impossibili.

    Restituisce [{"riga": indice nella lista (o None), "testo": avviso}]. Con la distinta si sa chi
    parte in campo (titolari) e chi in panchina (riserve); senza, lo si deduce dalla prima volta
    che un numero compare. Il rientro di chi è uscito è ammesso dal portale, ma viene segnalato."""
    avvisi: list[dict] = []
    stato: dict[int, str] = {}   # numero -> "campo", "panchina", "uscito"
    storia: dict[int, str] = {}  # numero -> ultimo movimento ("titolare", "entrato al 17' del 2° t.")
    if distinta:
        for g in distinta.giocatori:
            if g.numero is not None:
                stato[g.numero] = "panchina" if g.riserva else "campo"
                storia[g.numero] = "riserva" if g.riserva else "titolare"

    for i in ordine_cronologico(sostituzioni):
        s = sostituzioni[i]
        avviso = lambda testo, i=i: avvisi.append({"riga": i, "testo": testo})
        for dubbio in s.dubbi:
            avviso(f"{quando(s)}: {dubbio}")
        mancanti = [nome for nome, v in (("il tempo", s.tempo), ("il minuto", s.minuto),
                                         ("chi esce", s.esce), ("chi entra", s.entra)) if v is None]
        if mancanti:
            avviso(f"{quando(s)}: manca {', '.join(mancanti)}.")
        if s.tempo is not None and s.tempo not in (1, 2):
            avviso(f"{quando(s)}: tempo {s.tempo} non valido (1 o 2).")
        if s.minuto is not None and s.minuto < 1:
            avviso(f"{quando(s)}: minuto {s.minuto} non valido.")
        if s.esce is not None and s.esce == s.entra:
            avviso(f"{quando(s)}: esce ed entra lo stesso n. {s.esce}.")
            continue
        if distinta:
            for n in (s.esce, s.entra):
                if n is not None and n not in stato:
                    avviso(f"{quando(s)}: il n. {n} non è in distinta.")

        # Un movimento impossibile si segnala e non cambia la situazione: così l'errore compare una
        # volta sola, sulla riga sbagliata, e non si trascina nelle righe dopo.
        if s.esce is not None:
            st = stato.get(s.esce, "campo")
            if st == "panchina":
                avviso(f"{quando(s)}: esce il n. {s.esce}, ma è una riserva non ancora entrata.")
            elif st == "uscito":
                avviso(f"{quando(s)}: esce il n. {s.esce}, ma non è in campo ({storia[s.esce]}).")
            else:
                stato[s.esce], storia[s.esce] = "uscito", f"uscito al {quando(s)}"
        if s.entra is not None:
            st = stato.get(s.entra, "panchina")
            if st == "campo":
                avviso(f"{quando(s)}: entra il n. {s.entra}, ma è già in campo ({storia[s.entra]}).")
            else:
                if st == "uscito":
                    avviso(f"{quando(s)}: rientra il n. {s.entra} ({storia[s.entra]}). Controlla che sia giusto.")
                stato[s.entra], storia[s.entra] = "campo", f"entrato al {quando(s)}"
    return avvisi
