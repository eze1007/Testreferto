"""Prova la lettura di una distinta dal terminale.

Uso: python -m scripts.prova_lettura percorso/distinta.jpg
"""

import json
import mimetypes
import sys
from pathlib import Path

from app.checks import controlla
from app.extract import estrai_distinta


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = Path(sys.argv[1])
    content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    distinta = estrai_distinta(path.read_bytes(), content_type)
    print(json.dumps(distinta.model_dump(), indent=2, ensure_ascii=False))
    print("\nDA CONTROLLARE:" if (avvisi := controlla(distinta)) else "\nNessun avviso.")
    for a in avvisi:
        print(" -", a)


if __name__ == "__main__":
    main()
