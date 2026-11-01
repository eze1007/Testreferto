"""Allegati del referto: distinte e rapportino di fine gara nella scheda «Allegati» di Sinfonia4You.

Il portale accetta pdf, jpg e png fino a 1 MB (1048576 byte) e consiglia JPEG o PNG, perché con i
PDF l'anteprima di stampa del referto può non funzionare. Ogni file, foto o PDF, viene quindi
trasformato in un JPEG sotto il limite.
"""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps

# Limite del portale: 1048576 byte. Si resta un po' sotto, per sicurezza.
LIMITE_BYTE = 1_000_000
LATO_MASSIMO = 2400  # basta per leggere bene una distinta; si riduce se il file è troppo pesante
LATO_MINIMO = 800
MAX_PAGINE_PDF = 3

# Tipi di allegato del portale (tendina «tipo» della scheda Allegati).
TIPO_LISTA_CALCIATORI = 1      # le distinte: va indicata anche la squadra
TIPO_MODULO_AMMONITI = 3       # MODULO AMMONITI/ESPULSI: il rapportino di fine gara

# Cosa si allega, nell'ordine: (chiave, descrizione, tipo, squadra, nome del file sul portale).
ALLEGATI_REFERTO = [
    ("casa", "Distinta squadra di casa", TIPO_LISTA_CALCIATORI, "casa", "distinta_casa.jpg"),
    ("ospite", "Distinta squadra ospite", TIPO_LISTA_CALCIATORI, "ospite", "distinta_ospite.jpg"),
    ("rapportino", "Rapportino di fine gara", TIPO_MODULO_AMMONITI, None, "rapportino_fine_gara.jpg"),
]


class AllegatoNonValido(Exception):
    pass


@dataclass
class Allegato:
    chiave: str          # "casa", "ospite", "rapportino"
    descrizione: str
    tipo: int            # TIPO_LISTA_CALCIATORI o TIPO_MODULO_AMMONITI
    squadra: str | None  # "casa" / "ospite" per le distinte, None per il rapportino
    nome_file: str
    dati: bytes          # JPEG pronto per il portale


@dataclass
class EsitoAllegato:
    descrizione: str
    stato: str  # "caricato", "gia_presente", "errore"
    dettaglio: str = ""


def _immagine(dati: bytes, content_type: str) -> Image.Image:
    """La foto (raddrizzata secondo l'EXIF) oppure le prime pagine del PDF una sotto l'altra."""
    if content_type == "application/pdf" or dati[:4] == b"%PDF":
        import pypdfium2

        try:
            pdf = pypdfium2.PdfDocument(dati)
            pagine = [pdf[i].render(scale=200 / 72).to_pil().convert("RGB") for i in range(min(len(pdf), MAX_PAGINE_PDF))]
        except Exception as e:
            raise AllegatoNonValido(f"PDF non leggibile ({e})")
        if not pagine:
            raise AllegatoNonValido("PDF senza pagine")
        larghezza = max(p.width for p in pagine)
        foglio = Image.new("RGB", (larghezza, sum(p.height for p in pagine)), "white")
        y = 0
        for p in pagine:
            foglio.paste(p, (0, y))
            y += p.height
        return foglio
    try:
        img = Image.open(io.BytesIO(dati))
        img.load()
    except Exception:
        raise AllegatoNonValido("il file non è un'immagine o un PDF leggibile (servono foto JPEG/PNG o PDF)")
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        # Le parti trasparenti diventano bianche, non nere.
        img = img.convert("RGBA")
        sfondo = Image.new("RGB", img.size, "white")
        sfondo.paste(img, mask=img.getchannel("A"))
        return sfondo
    return img.convert("RGB")


def prepara_allegato(dati: bytes, content_type: str = "") -> bytes:
    """JPEG sotto LIMITE_BYTE: si prova con il lato lungo a LATO_MASSIMO e qualità alta, poi si
    abbassa la qualità e, se non basta, si rimpicciolisce l'immagine."""
    if not dati:
        raise AllegatoNonValido("file vuoto")
    img = _immagine(dati, content_type)
    lato = LATO_MASSIMO
    while lato >= LATO_MINIMO:
        copia = img.copy()
        copia.thumbnail((lato, lato))
        for qualita in (90, 85, 80, 75, 70, 65, 60):
            out = io.BytesIO()
            copia.save(out, format="JPEG", quality=qualita, optimize=True)
            if out.tell() <= LIMITE_BYTE:
                return out.getvalue()
        lato = int(lato * 0.8)
    raise AllegatoNonValido("impossibile ridurre il file sotto 1 MB")
