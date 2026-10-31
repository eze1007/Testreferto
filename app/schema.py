"""Struttura dati estratta dalla distinta: numero, cognome, nome, data di nascita, riserva."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Giocatore(BaseModel):
    testo_originale: str = Field(description="Contenuto della colonna 'Cognome e nome' come stampato, senza sigle (R)/(P)")
    numero: Optional[int] = Field(description="Numero di maglia ('N° del Ruolo', oppure l'unica colonna di numeri); null se illeggibile")
    cognome: str = Field(description="Cognome in maiuscolo, come scritto (anche composto, es. 'DAL CERO')")
    nome: str = Field(description="Nome o nomi in maiuscolo, come scritti, senza sigle (R)/(P)")
    data_nascita: Optional[str] = Field(description="Data di nascita in formato GG/MM/AAAA; null se illeggibile")
    riserva: bool = Field(default=False, description="Lascia false: lo decide il programma (dal 12° giocatore in poi)")
    dubbi: list[str] = Field(description="Campi letti con incertezza; lista vuota se tutto chiaro")

    @field_validator("testo_originale", "cognome", "nome", mode="before")
    @classmethod
    def _vuoto_se_mancante(cls, v):
        # Un nome illeggibile non deve far fallire tutta la distinta: resta vuoto e viene segnalato.
        return "" if v is None else v


class Distinta(BaseModel):
    giocatori: list[Giocatore]
    note_generali: list[str] = Field(description="Problemi generali: foto sfocata, parti tagliate, ecc.")


# --- Rapportino di fine gara ------------------------------------------------------------------

class Sostituzione(BaseModel):
    tempo: Optional[int] = Field(description="Tempo di gioco (1 o 2), scritto dopo 'del'; null se illeggibile")
    minuto: Optional[int] = Field(description="Minuto scritto dopo 'Al'; null se illeggibile")
    esce: Optional[int] = Field(description="Numero di maglia scritto dopo 'esce il n.'; null se illeggibile")
    entra: Optional[int] = Field(description="Numero di maglia scritto dopo 'entra il n.'; null se illeggibile")
    dubbi: list[str] = Field(default_factory=list, description="Cifre lette con incertezza; lista vuota se tutto chiaro")


class Rapportino(BaseModel):
    casa: list[Sostituzione] = Field(description="Sostituzioni della società ospitante (colonna di sinistra), nell'ordine delle righe")
    ospite: list[Sostituzione] = Field(description="Sostituzioni della società ospitata (colonna di destra), nell'ordine delle righe")
    note_generali: list[str] = Field(default_factory=list, description="Problemi di leggibilità della foto")
