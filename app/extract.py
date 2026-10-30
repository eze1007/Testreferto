"""Lettura della distinta (foto o PDF) con Claude."""

import base64
import io

import anthropic
from PIL import Image, ImageOps

from .schema import Distinta

MODEL = "claude-opus-5-5"

# L'API accetta immagini fino a 5 MB; il lato lungo oltre ~2000 px non aggiunge dettaglio utile.
MAX_LATO = 2000
MAX_BYTES = 4_500_000

SYSTEM_PROMPT = """Leggi distinte di gara del calcio dilettantistico italiano (F.I.G.C. - L.N.D.) \
fotografate o scansionate da un arbitro.

Una distinta elenca i calciatori di una sola squadra. Per ogni riga compilata riporta i dati \
esattamente come sono scritti: non correggere i nomi e non inventare valori. Se un campo è \
illeggibile mettilo a null e spiegalo in `dubbi`; se una lettera o una cifra è incerta, riporta \
la lettura più probabile e segnala il dubbio. Ignora le righe vuote.

Le sigle accanto al nome hanno questo significato: (R) riserva, (P) portiere, (Tess.) tesseramento \
in corso. Un giocatore senza (R) è titolare. Nella colonna Capitano/V.Cap. "C" indica il capitano e \
"V" il vice capitano. Segni a penna nelle colonne Espulsi/Ammoniti non fanno parte della distinta: \
ignorali."""


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
    client = client or anthropic.Anthropic()
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
                {"type": "text", "text": "Estrai tutti i dati di questa distinta."},
            ],
        }],
        output_format=Distinta,
    )
    if response.stop_reason == "refusal":
        raise LetturaFallita("Il modello ha rifiutato la richiesta.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise LetturaFallita("Risposta incompleta: riprova con una foto più nitida.")
    return response.parsed_output
