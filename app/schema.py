"""Struttura dati della distinta di gara (una distinta = una squadra)."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Giocatore(BaseModel):
    riga: int = Field(description="Numero di riga stampato a sinistra nella distinta (1, 2, 3...)")
    numero_maglia: Optional[int] = Field(description="Numero indicato nella colonna 'N° del Ruolo'")
    cognome_nome: str = Field(description="Cognome e nome in maiuscolo, esattamente come scritti, senza (R)/(P)")
    data_nascita: Optional[str] = Field(description="Formato GG/MM/AAAA")
    matricola_figc: Optional[str] = Field(description="Colonna 'N. Matricola F.I.G.C.', solo cifre")
    ruolo: Literal["titolare", "riserva"] = Field(description="'riserva' se accanto al nome c'è (R), altrimenti 'titolare'")
    portiere: bool = Field(description="True se accanto al nome c'è (P)")
    capitano: Optional[Literal["C", "V"]] = Field(description="'C' capitano, 'V' vice capitano, null altrimenti")
    documento_tipo: Optional[str] = Field(description="Es. 'Tess.' o 'C.I.'")
    documento_numero: Optional[str]
    dubbi: list[str] = Field(description="Campi letti con incertezza o illeggibili; lista vuota se tutto chiaro")


class Persona(BaseModel):
    ruolo: str = Field(description="Es. 'Assistente dell'Arbitro', 'Dirigente accompagnatore', 'Allenatore', 'Massaggiatore'")
    cognome_nome: str
    data_nascita: Optional[str]
    matricola: Optional[str]
    tessera: Optional[str]


class Distinta(BaseModel):
    numero_distinta: Optional[str]
    squadra: str = Field(description="Società che presenta la distinta (intestazione in alto), senza il codice numerico")
    codice_societa: Optional[str] = Field(description="Codice numerico prima del nome della società")
    gara: Optional[str] = Field(description="Testo della gara, es. 'SQUADRA A - SQUADRA B'")
    campionato: Optional[str]
    data_ora: Optional[str] = Field(description="Data e ora della gara come scritte")
    campo: Optional[str]
    giocatori: list[Giocatore]
    staff: list[Persona] = Field(description="Assistente dell'arbitro, dirigenti, allenatori, massaggiatore, ecc. solo se compilati")
    note_generali: list[str] = Field(description="Problemi generali: foto sfocata, parti tagliate, scritte a mano, ecc.")
