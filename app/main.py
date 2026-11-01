"""Pannello web privato: carica le distinte, rivedi i dati, compila Sinfonia4You."""

import base64
import binascii
import os
import secrets
import threading
import uuid
from datetime import datetime
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from playwright.sync_api import Page
from pydantic import BaseModel

from . import compilazione
from .checks import controlla, controlla_sostituzioni
from .extract import LetturaFallita, estrai_distinta, estrai_rapportino
from .schema import Distinta, Sostituzione
from .sinfonia import Esito, EsitoSostituzione

MAX_UPLOAD = 20 * 1024 * 1024
TIPI_AMMESSI = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Lettura distinta", docs_url=None, redoc_url=None)
security = HTTPBasic()


def autenticato(cred: HTTPBasicCredentials = Depends(security)) -> None:
    utente = os.environ.get("APP_USER", "")
    password = os.environ.get("APP_PASSWORD", "")
    if not utente or not password:
        raise HTTPException(503, "APP_USER e APP_PASSWORD non configurati sul server.")
    ok = secrets.compare_digest(cred.username, utente) and secrets.compare_digest(cred.password, password)
    if not ok:
        raise HTTPException(401, "Credenziali errate", headers={"WWW-Authenticate": "Basic"})


@app.get("/", dependencies=[Depends(autenticato)])
def pagina() -> FileResponse:
    return FileResponse(STATIC / "index.html")


async def _leggi_file(file: UploadFile, funzione):
    if file.content_type not in TIPI_AMMESSI:
        raise HTTPException(415, f"Formato non supportato: {file.content_type}")
    dati = await file.read(MAX_UPLOAD + 1)
    if len(dati) > MAX_UPLOAD:
        raise HTTPException(413, "File troppo grande (max 20 MB).")
    try:
        return await run_in_threadpool(funzione, dati, file.content_type)
    except LetturaFallita as e:
        raise HTTPException(422, str(e))
    except anthropic.RateLimitError:
        raise HTTPException(429, "Troppe richieste, riprova tra poco.")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"Errore del servizio di lettura ({e.status_code}).")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "Servizio di lettura non raggiungibile.")


@app.post("/api/estrai", dependencies=[Depends(autenticato)])
async def estrai(file: UploadFile) -> dict:
    distinta = await _leggi_file(file, lambda d, ct: estrai_distinta(d, ct))
    return {"distinta": distinta.model_dump(), "avvisi": controlla(distinta)}


@app.post("/api/rapportino", dependencies=[Depends(autenticato)])
async def rapportino(file: UploadFile) -> dict:
    """Legge le sostituzioni dal rapportino di fine gara (i controlli li fa /api/controlla-sostituzioni,
    che conosce anche le distinte)."""
    r = await _leggi_file(file, lambda d, ct: estrai_rapportino(d, ct))
    return {"rapportino": r.model_dump()}


class SquadraDaControllare(BaseModel):
    sostituzioni: list[Sostituzione] = []
    distinta: Distinta | None = None


@app.post("/api/controlla-sostituzioni", dependencies=[Depends(autenticato)])
def verifica_sostituzioni(squadre: dict[str, SquadraDaControllare]) -> dict:
    """Avvisi sulle sostituzioni di ogni squadra, ricalcolati a ogni modifica nella pagina."""
    return {lato: controlla_sostituzioni(s.sostituzioni, s.distinta) for lato, s in squadre.items()}


# --- Compilazione di Sinfonia4You ---------------------------------------------------------

# Solo per i test: permette di puntare il browser alla copia finta del portale.
PREPARA_PAGINA: Callable[[Page], None] | None = None


class FileAllegato(BaseModel):
    nome: str = ""
    tipo: str = ""   # tipo del file indicato dal browser, es. image/jpeg
    dati: str        # contenuto in base64


class RichiestaCompilazione(BaseModel):
    gara: str
    casa: Distinta | None = None
    ospite: Distinta | None = None
    sostituzioni: dict[str, list[Sostituzione]] = {}
    # File caricati nella prima schermata da allegare al referto: "casa", "ospite", "rapportino".
    allegati: dict[str, FileAllegato] = {}


def _file_allegati(allegati: dict[str, FileAllegato]) -> dict[str, tuple[bytes, str]]:
    file = {}
    for chiave, f in allegati.items():
        if chiave not in ("casa", "ospite", "rapportino"):
            continue
        try:
            dati = base64.b64decode(f.dati, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, f"Allegato «{chiave}» non valido.")
        if len(dati) > MAX_UPLOAD:
            raise HTTPException(413, f"Allegato «{chiave}» troppo grande (max 20 MB).")
        file[chiave] = (dati, f.tipo)
    return file


@dataclass
class Lavoro:
    stato: str = "in_corso"  # "in_corso", "completato", "errore"
    messaggi: list[str] = field(default_factory=list)
    esiti: dict[str, list[dict]] = field(default_factory=lambda: {"casa": [], "ospite": []})
    sostituzioni: dict[str, list[dict]] = field(default_factory=lambda: {"casa": [], "ospite": []})
    verifica: list[str] | None = None  # controllo delle sostituzioni sul portale dopo il salvataggio
    allegati: list[dict] = field(default_factory=list)
    avvisi: dict[str, list[str]] = field(default_factory=dict)
    bottone: str | None = None
    errore: str | None = None
    screenshot: bytes | None = None


_lavori: dict[str, Lavoro] = {}
_un_lavoro_alla_volta = threading.Lock()


def _esito(e: Esito) -> dict:
    g = e.giocatore
    return {"numero": g.numero, "cognome": g.cognome, "nome": g.nome, "data_nascita": g.data_nascita,
            "riserva": g.riserva, "stato": e.stato, "dettaglio": e.dettaglio}


def _esito_sostituzione(e: EsitoSostituzione) -> dict:
    return {**e.sostituzione.model_dump(exclude={"dubbi"}), "stato": e.stato, "dettaglio": e.dettaglio}


def _esegui(lavoro: Lavoro, squadre: dict[str, Distinta], gara: str, utente: str, password: str,
            sostituzioni: dict[str, list[Sostituzione]] | None = None,
            allegati: dict[str, tuple[bytes, str]] | None = None) -> None:
    try:
        r = compilazione.compila(
            squadre, gara, utente, password,
            headless=os.environ.get("BROWSER_VISIBILE") != "1",  # 1 = si vede il browser (prove sul PC)
            cartella_debug=Path("esplorazione") / datetime.now().strftime("%Y%m%d-%H%M%S"),
            avanzamento=lavoro.messaggi.append,
            al_giocatore=lambda lato, e: lavoro.esiti[lato].append(_esito(e)),
            prepara_pagina=PREPARA_PAGINA,
            sostituzioni=sostituzioni,
            alla_sostituzione=lambda lato, e: lavoro.sostituzioni[lato].append(_esito_sostituzione(e)),
            allegati=allegati,
            all_allegato=lambda e: lavoro.allegati.append(
                {"descrizione": e.descrizione, "stato": e.stato, "dettaglio": e.dettaglio}),
        )
        lavoro.avvisi = {lato: rep.avvisi for lato, rep in r.report.items()}
        lavoro.verifica = r.verifica
        lavoro.bottone, lavoro.errore, lavoro.screenshot = r.bottone_salvataggio, r.errore, r.screenshot
        lavoro.stato = "errore" if r.errore else "completato"
    except Exception as e:  # es. browser non avviabile
        lavoro.errore, lavoro.stato = str(e).splitlines()[0], "errore"
    finally:
        _un_lavoro_alla_volta.release()


@app.post("/api/compila", dependencies=[Depends(autenticato)])
def avvia_compilazione(richiesta: RichiestaCompilazione) -> dict:
    utente, password = os.environ.get("SINFONIA_USER"), os.environ.get("SINFONIA_PASSWORD")
    if not utente or not password:
        raise HTTPException(503, "SINFONIA_USER e SINFONIA_PASSWORD non configurati sul server.")
    squadre = {lato: d for lato in ("casa", "ospite") if (d := getattr(richiesta, lato))}
    if not squadre or not richiesta.gara.strip():
        raise HTTPException(422, "Servono la gara e almeno una squadra.")
    allegati = _file_allegati(richiesta.allegati)
    if not _un_lavoro_alla_volta.acquire(blocking=False):
        raise HTTPException(409, "C'è già una compilazione in corso.")
    id_lavoro = uuid.uuid4().hex
    _lavori[id_lavoro] = lavoro = Lavoro()
    sostituzioni = {lato: s for lato, s in richiesta.sostituzioni.items() if lato in ("casa", "ospite")}
    threading.Thread(target=_esegui, args=(lavoro, squadre, richiesta.gara, utente, password, sostituzioni, allegati),
                     daemon=True).start()
    return {"id": id_lavoro}


def _lavoro(id_lavoro: str) -> Lavoro:
    if id_lavoro not in _lavori:
        raise HTTPException(404, "Compilazione non trovata.")
    return _lavori[id_lavoro]


@app.get("/api/compila/{id_lavoro}", dependencies=[Depends(autenticato)])
def stato_compilazione(id_lavoro: str) -> dict:
    l = _lavoro(id_lavoro)
    return {"stato": l.stato, "messaggi": l.messaggi, "esiti": l.esiti, "sostituzioni": l.sostituzioni, "verifica": l.verifica, "allegati": l.allegati, "avvisi": l.avvisi,
            "bottone": l.bottone, "errore": l.errore, "screenshot": l.screenshot is not None}


@app.get("/api/compila/{id_lavoro}/screenshot", dependencies=[Depends(autenticato)])
def screenshot_compilazione(id_lavoro: str) -> Response:
    l = _lavoro(id_lavoro)
    if not l.screenshot:
        raise HTTPException(404, "Screenshot non disponibile.")
    return Response(l.screenshot, media_type="image/png", headers={"Cache-Control": "no-store"})
