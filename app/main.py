"""Pannello web privato: carica la distinta, leggi i dati, rivedili."""

import os
import secrets
from pathlib import Path

import anthropic
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .checks import controlla
from .extract import LetturaFallita, estrai_distinta

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
        distinta = estrai_distinta(dati, file.content_type)
    except LetturaFallita as e:
        raise HTTPException(422, str(e))
    except anthropic.RateLimitError:
        raise HTTPException(429, "Troppe richieste, riprova tra poco.")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"Errore del servizio di lettura ({e.status_code}).")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "Servizio di lettura non raggiungibile.")
    return {"distinta": distinta.model_dump(), "avvisi": controlla(distinta)}
