"""Procedura completa di compilazione, usata dalla pagina web e dallo script da terminale."""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from .schema import Distinta
from .sinfonia import Esito, Report, Sinfonia

NOMI_LATO = {"casa": "squadra di casa", "ospite": "squadra ospite"}


@dataclass
class Risultato:
    report: dict[str, Report] = field(default_factory=dict)
    bottone_salvataggio: str | None = None
    screenshot: bytes | None = None  # pagina finale, oppure il punto in cui si è fermato
    errore: str | None = None


def compila(
    squadre: dict[str, Distinta],
    gara: str,
    utente: str,
    password: str,
    *,
    headless: bool = True,
    cartella_debug: Path | None = None,
    avanzamento: Callable[[str], None] = lambda messaggio: None,
    al_giocatore: Callable[[str, Esito], None] = lambda lato, esito: None,
    prepara_pagina: Callable[[Page], None] | None = None,
    alla_fine: Callable[[Page], None] | None = None,
) -> Risultato:
    """Login, apertura gara, Svolgimento e Sicurezza, Liste Gara delle squadre, Salva Tutto."""
    risultato = Risultato()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, executable_path=os.environ.get("CHROMIUM_PATH"))
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        if prepara_pagina:
            prepara_pagina(page)
        s4y = Sinfonia(page, cartella_debug=cartella_debug)
        try:
            avanzamento("Accesso a Sinfonia4You…")
            s4y.login(utente, password)
            avanzamento(f"Ricerca della gara «{gara}»…")
            s4y.apri_gara(gara)
            avanzamento("Svolgimento e Sicurezza…")
            s4y.svolgimento_e_sicurezza()
            for lato, distinta in squadre.items():
                avanzamento(f"Liste Gara, {NOMI_LATO[lato]}…")
                risultato.report[lato] = s4y.compila_lista(
                    distinta.giocatori, lato, al_giocatore=lambda e, lato=lato: al_giocatore(lato, e))
            avanzamento("Salvataggio (Salva Tutto)…")
            risultato.bottone_salvataggio = s4y.salva()
            avanzamento("Referto salvato.")
        except Exception as e:
            risultato.errore = str(e).splitlines()[0] if str(e) else type(e).__name__
            s4y.istantanea("errore")
        try:
            risultato.screenshot = page.screenshot(full_page=True)
        except Exception:
            pass
        if alla_fine:
            alla_fine(page)
        browser.close()
    return risultato
