"""Struttura dati estratta dalla distinta: numero, cognome, nome, data di nascita, riserva."""

from typing import Optional

from pydantic import BaseModel, Field


class Giocatore(BaseModel):
    numero: Optional[int] = Field(description="Numero nella colonna 'N° del Ruolo'; null se illeggibile")
    cognome: str = Field(description="Cognome in maiuscolo, come scritto (anche composto, es. 'DAL CERO')")
    nome: str = Field(description="Nome o nomi in maiuscolo, come scritti, senza sigle (R)/(P)")
    data_nascita: Optional[str] = Field(description="Data di nascita in formato GG/MM/AAAA; null se illeggibile")
    riserva: bool = Field(description="True se accanto al nome c'è la sigla (R)")
    dubbi: list[str] = Field(description="Campi letti con incertezza; lista vuota se tutto chiaro")


class Distinta(BaseModel):
    giocatori: list[Giocatore]
    note_generali: list[str] = Field(description="Problemi generali: foto sfocata, parti tagliate, ecc.")
