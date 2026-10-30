"""Lettura della distinta (foto o PDF) con Claude.

Se nel .env c'è YEPAPI_API_KEY la lettura passa da YepAPI (endpoint OpenAI-compatibile, modello
in YEPAPI_MODEL); altrimenti usa direttamente l'API Anthropic con ANTHROPIC_API_KEY.
"""

import base64
import io
import json
import os
import re

import anthropic
import httpx
from PIL import Image, ImageOps

from .schema import Distinta, Giocatore

MODEL = "claude-opus-5-5"

# L'API accetta immagini fino a 5 MB; il lato lungo oltre ~2000 px non aggiunge dettaglio utile.
MAX_LATO = 2000
MAX_BYTES = 4_500_000

SYSTEM_PROMPT = """Leggi distinte di gara del calcio dilettantistico italiano (F.I.G.C. - L.N.D.) \
fotografate o scansionate da un arbitro.

Elenca i calciatori nell'ordine delle righe della distinta, dall'alto in basso, senza riordinarli. \
Per ogni calciatore estrai: il numero (colonna "N° del Ruolo", non il numero di riga stampato a \
margine; non è in ordine e nei primi 11 possono esserci numeri alti come 13 o 16), il cognome, \
il nome e la data di nascita (GG/MM/AAAA). Nella colonna "Cognome e nome" il cognome viene prima del \
nome; i cognomi possono essere composti (es. "DAL CERO") e i nomi doppi (es. "MATTEO ANTONIO"). \
Non riportare le sigle nel nome e non includere staff o dirigenti. In `testo_originale` copia \
il contenuto della colonna "Cognome e nome" così com'è (senza sigle), prima di dividerlo.

Riporta i dati esattamente come sono scritti: non correggere i nomi e non inventare valori. Se \
una lettera o una cifra è incerta, o la divisione tra cognome e nome non è chiara, riporta la \
lettura più probabile e segnala il dubbio. Ignora le righe vuote e i segni a penna."""


def _prepara_immagine(dati: bytes) -> tuple[bytes, str]:
    img = Image.open(io.BytesIO(dati))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_LATO, MAX_LATO))
    qualita = 90
    while True:
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=qualita)
        if out.tell() <= MAX_BYTES or qualita <= 50:
            return out.getvalue(), "image/jpeg"
        qualita -= 10


def _blocco_file(dati: bytes, content_type: str) -> dict:
    if content_type == "application/pdf" or dati[:4] == b"%PDF":
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": base64.standard_b64encode(dati).decode()},
        }
    jpeg, media_type = _prepara_immagine(dati)
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type,
                   "data": base64.standard_b64encode(jpeg).decode()},
    }


class LetturaFallita(Exception):
    pass


def estrai_distinta(dati: bytes, content_type: str, client: anthropic.Anthropic | None = None) -> Distinta:
    if client is None and os.environ.get("YEPAPI_API_KEY"):
        distinta = _estrai_yepapi(dati, content_type)
    else:
        distinta = _estrai_anthropic(dati, content_type, client or anthropic.Anthropic())
    for g in distinta.giocatori:
        applica_regola_due_parole(g)
    applica_regola_titolari(distinta)
    return distinta


def _estrai_anthropic(dati: bytes, content_type: str, client: anthropic.Anthropic) -> Distinta:
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                _blocco_file(dati, content_type),
                {"type": "text", "text": "Estrai i dati di ogni calciatore."},
            ],
        }],
        output_format=Distinta,
    )
    if response.stop_reason == "refusal":
        raise LetturaFallita("Il modello ha rifiutato la richiesta.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise LetturaFallita("Risposta incompleta: riprova con una foto più nitida.")
    return response.parsed_output


# --- YepAPI (OpenAI-compatibile) ---------------------------------------------------------

YEPAPI_URL = "https://api.yepapi.com/v1/ai/chat/completions"
YEPAPI_MODEL = "anthropic/claude-haiku-5.5"  # sulla distinta di prova: 20/20 (Haiku 4.5: 9/20)
MAX_PAGINE_PDF = 3

FORMATO_JSON = """Rispondi solo con un oggetto JSON, senza testo prima o dopo, in questo formato:
{"giocatori": [{"testo_originale": "ROSSI MARIO", "numero": 7, "cognome": "ROSSI", "nome": "MARIO",
"data_nascita": "01/01/2000", "dubbi": []}], "note_generali": []}
Usa null per numero o data illeggibili. In note_generali metti solo problemi di leggibilità della \
foto, non i dati della gara."""


def _immagini(dati: bytes, content_type: str) -> list[bytes]:
    """JPEG da inviare: la foto, oppure le prime pagine del PDF trasformate in immagini."""
    if content_type != "application/pdf" and dati[:4] != b"%PDF":
        return [_prepara_immagine(dati)[0]]
    import pypdfium2

    pdf = pypdfium2.PdfDocument(dati)
    pagine = []
    for i in range(min(len(pdf), MAX_PAGINE_PDF)):
        out = io.BytesIO()
        pdf[i].render(scale=200 / 72).to_pil().save(out, format="PNG")
        pagine.append(_prepara_immagine(out.getvalue())[0])
    return pagine


def _estrai_yepapi(dati: bytes, content_type: str, http: httpx.Client | None = None) -> Distinta:
    contenuto = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(j).decode()}}
                 for j in _immagini(dati, content_type)]
    contenuto.append({"type": "text", "text": "Estrai i dati di ogni calciatore.\n\n" + FORMATO_JSON})
    richiesta = {
        "model": os.environ.get("YEPAPI_MODEL") or YEPAPI_MODEL,
        "max_tokens": 8000,
        "temperature": 0,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": contenuto}],
    }
    http = http or httpx.Client(timeout=180)
    try:
        r = http.post(YEPAPI_URL, json=richiesta,
                      headers={"x-api-key": os.environ["YEPAPI_API_KEY"],
                               "Authorization": f"Bearer {os.environ['YEPAPI_API_KEY']}"})
    except httpx.HTTPError as e:
        raise LetturaFallita(f"YepAPI non raggiungibile: {e}")
    if r.status_code != 200:
        raise LetturaFallita(f"YepAPI ha risposto {r.status_code}: {r.text[:300]}")
    scelta = r.json()["choices"][0]
    if scelta.get("finish_reason") == "length":
        raise LetturaFallita("Risposta incompleta: riprova con una foto più nitida.")
    testo = scelta["message"]["content"] or ""
    m = re.search(r"\{.*\}", testo, re.S)  # il JSON, anche se racchiuso tra ``` o con testo attorno
    try:
        return Distinta.model_validate(json.loads(m.group(0) if m else testo))
    except (ValueError, TypeError) as e:
        raise LetturaFallita(f"Risposta non valida dal modello: {str(e)[:200]}")


TITOLARI = 11


def applica_regola_titolari(distinta: Distinta) -> None:
    """I primi 11 della lista sono titolari, gli altri riserve, qualunque sia il numero di maglia."""
    for posizione, g in enumerate(distinta.giocatori):
        g.riserva = posizione >= TITOLARI


def applica_regola_due_parole(g: Giocatore) -> None:
    """La distinta stampa prima il cognome: con due sole parole la divisione è sicura."""
    parole = g.testo_originale.split()
    if len(parole) == 2:
        g.cognome, g.nome = parole
