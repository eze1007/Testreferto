"""Abbinamento tra i giocatori letti e le voci dei menu di Sinfonia4You.

Le voci del portale mostrano nome, data di nascita e ID. La data di nascita è il criterio
più affidabile per distinguere omonimi; il nome viene confrontato in modo tollerante
(ordine cognome/nome, accenti, piccoli errori di lettura).
"""

import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from .schema import Giocatore

SOGLIA_NOME = 0.85


@dataclass
class VocePortale:
    id: str
    nome: str
    data_nascita: str | None = None


@dataclass
class Abbinamento:
    giocatore: Giocatore
    voce: VocePortale | None
    punteggio: float
    stato: str  # "sicuro", "da_verificare", "non_trovato"
    alternative: list[VocePortale]


def _normalizza(nome: str) -> str:
    nome = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    parole = "".join(c if c.isalnum() else " " for c in nome.upper()).split()
    return " ".join(sorted(parole))


def somiglianza_nome(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalizza(a), _normalizza(b)).ratio()


def abbina(giocatore: Giocatore, voci: list[VocePortale]) -> Abbinamento:
    candidati = sorted(
        ((somiglianza_nome(giocatore.cognome_nome, v.nome), v) for v in voci),
        key=lambda x: x[0],
        reverse=True,
    )
    candidati = [(s, v) for s, v in candidati if s >= 0.6]
    if not candidati:
        return Abbinamento(giocatore, None, 0.0, "non_trovato", [])

    if giocatore.data_nascita:
        stessa_data = [(s, v) for s, v in candidati if v.data_nascita == giocatore.data_nascita]
        if len(stessa_data) == 1 and stessa_data[0][0] >= 0.7:
            s, v = stessa_data[0]
            return Abbinamento(giocatore, v, s, "sicuro", [])

    migliore_s, migliore = candidati[0]
    altri = [v for s, v in candidati[1:] if migliore_s - s < 0.1]
    if migliore_s >= SOGLIA_NOME and not altri:
        stato = "sicuro" if migliore_s == 1.0 else "da_verificare"
        return Abbinamento(giocatore, migliore, migliore_s, stato, [])
    return Abbinamento(giocatore, migliore, migliore_s, "da_verificare", altri)
