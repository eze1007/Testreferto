"""Pannello web privato: carica le distinte, rivedi i dati, compila Sinfonia4You."""

import os
import secrets
import threading
import uuid
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
from .checks import controlla
from .extract import LetturaFallita, estrai_distinta
from .schema import Distinta
from .sinfonia import Esito

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


@app.post("/api/estrai", dependencies=[Depends(autenticato)])
async def estrai(file: UploadFile) -> dict:
    if file.content_type not in TIPI_AMMESSI:
        raise HTTPException(415, f"Formato non supportato: {file.content_type}")
    dati = await file.read(MAX_UPLOAD + 1)
    if len(dati) > MAX_UPLOAD:
        raise HTTPException(413, "File troppo grande (max 20 MB).")
    try:
        distinta = await run_in_threadpool(estrai_distinta, dati, file.content_type)
    except LetturaFallita as e:
        raise HTTPException(422, str(e))
    except anthropic.RateLimitError:
        raise HTTPException(429, "Troppe richieste, riprova tra poco.")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"Errore del servizio di lettura ({e.status_code}).")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "Servizio di lettura non raggiungibile.")
    return {"distinta": distinta.model_dump(), "avvisi": controlla(distinta)}


# --- Compilazione di Sinfonia4You ---------------------------------------------------------

# Solo per i test: permette di puntare il browser alla copia finta del portale.
PREPARA_PAGINA: Callable[[Page], None] | None = None


class RichiestaCompilazione(BaseModel):
    gara: str
    casa: Distinta | None = None
    ospite: Distinta | None = None


@dataclass
class Lavoro:
    stato: str = "in_corso"  # "in_corso", "completato", "errore"
    messaggi: list[str] = field(default_factory=list)
    esiti: dict[str, list[dict]] = field(default_factory=lambda: {"casa": [], "ospite": []})
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


def _esegui(lavoro: Lavoro, squadre: dict[str, Distinta], gara: str, utente: str, password: str) -> None:
    try:
        r = compilazione.compila(
            squadre, gara, utente, password,
            headless=os.environ.get("BROWSER_VISIBILE") != "1",  # 1 = si vede il browser (prove sul PC)
            avanzamento=lavoro.messaggi.append,
            al_giocatore=lambda lato, e: lavoro.esiti[lato].append(_esito(e)),
            prepara_pagina=PREPARA_PAGINA,
        )
        lavoro.avvisi = {lato: rep.avvisi for lato, rep in r.report.items()}
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
    if not _un_lavoro_alla_volta.acquire(blocking=False):
        raise HTTPException(409, "C'è già una compilazione in corso.")
    id_lavoro = uuid.uuid4().hex
    _lavori[id_lavoro] = lavoro = Lavoro()
    threading.Thread(target=_esegui, args=(lavoro, squadre, richiesta.gara, utente, password), daemon=True).start()
    return {"id": id_lavoro}


def _lavoro(id_lavoro: str) -> Lavoro:
    if id_lavoro not in _lavori:
        raise HTTPException(404, "Compilazione non trovata.")
    return _lavori[id_lavoro]


@app.get("/api/compila/{id_lavoro}", dependencies=[Depends(autenticato)])
def stato_compilazione(id_lavoro: str) -> dict:
    l = _lavoro(id_lavoro)
    return {"stato": l.stato, "messaggi": l.messaggi, "esiti": l.esiti, "avvisi": l.avvisi,
            "bottone": l.bottone, "errore": l.errore, "screenshot": l.screenshot is not None}


@app.get("/api/compila/{id_lavoro}/screenshot", dependencies=[Depends(autenticato)])
def screenshot_compilazione(id_lavoro: str) -> Response:
    l = _lavoro(id_lavoro)
    if not l.screenshot:
        raise HTTPException(404, "Screenshot non disponibile.")
    return Response(l.screenshot, media_type="image/png", headers={"Cache-Control": "no-store"})
