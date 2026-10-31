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
