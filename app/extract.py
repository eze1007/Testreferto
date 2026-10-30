"""Lettura della distinta (foto o PDF) con Claude."""

import base64
import io

import anthropic
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
il nome, la data di nascita (GG/MM/AAAA) e se è una riserva (sigla "(R)" sotto o accanto al nome). Nella colonna "Cognome e nome" il cognome viene prima del \
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
                {"type": "text", "text": "Estrai i dati di ogni calciatore."},
            ],
        }],
        output_format=Distinta,
    )
    if response.stop_reason == "refusal":
        raise LetturaFallita("Il modello ha rifiutato la richiesta.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise LetturaFallita("Risposta incompleta: riprova con una foto più nitida.")
    distinta = response.parsed_output
    for g in distinta.giocatori:
        applica_regola_due_parole(g)
    applica_regola_titolari(distinta)
    return distinta


TITOLARI = 11


def applica_regola_titolari(distinta: Distinta) -> None:
    """I primi 11 della lista sono titolari, gli altri riserve, qualunque sia il numero di maglia.

    La sigla (R) letta dal modello serve solo da controllo: se non torna con la posizione,
    il giocatore viene segnalato.
    """
    for posizione, g in enumerate(distinta.giocatori):
        riserva = posizione >= TITOLARI
        if g.riserva != riserva:
            g.dubbi.append(f"sulla distinta {'manca' if riserva else 'compare'} la sigla (R), "
                           f"ma è {posizione + 1}° nella lista: considerato {'riserva' if riserva else 'titolare'}")
        g.riserva = riserva


def applica_regola_due_parole(g: Giocatore) -> None:
    """La distinta stampa prima il cognome: con due sole parole la divisione è sicura."""
    parole = g.testo_originale.split()
    if len(parole) == 2:
        g.cognome, g.nome = parole
