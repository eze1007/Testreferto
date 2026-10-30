# Testreferto

Agente per ridurre il lavoro manuale nella compilazione del referto arbitrale su Sinfonia4You.

**Fase 1 (questa versione): lettura della distinta.** Si carica dal telefono una foto o un PDF
della distinta di gara, Claude estrae i dati dei calciatori, il programma segnala incongruenze
e l'arbitro rivede e corregge tutto in una tabella. Il portale Sinfonia4You non viene ancora toccato.

## Cosa estrae

Per ogni riga compilata: numero di maglia, cognome e nome, data di nascita, matricola F.I.G.C.,
titolare o riserva `(R)`, portiere `(P)`, capitano `C` / vice `V`, documento. In più l'intestazione
(squadra, gara, campionato, data, campo) e lo staff (assistente dell'arbitro, dirigenti, allenatore…).

I controlli automatici (`app/checks.py`) segnalano: titolari diversi da 11, nessun portiere
titolare, capitano mancante o doppio, numeri di maglia ripetuti, nomi doppi, date non valide,
matricole sospette e ogni campo che il modello ha letto con incertezza.

`app/matching.py` è già pronto per la Fase 2: abbina i nomi letti alle voci dei menu del portale
(nome, data di nascita, ID), usando la data di nascita per distinguere gli omonimi e segnalando
come "da verificare" i casi ambigui.

## Avvio

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # inserisci la chiave API e utente/password del pannello
set -a && source .env && set +a
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Apri `http://<indirizzo-server>:8000` dal telefono. Il pannello è protetto da utente e password
(`APP_USER` / `APP_PASSWORD`); su una VPS va messo dietro HTTPS (es. Caddy o Nginx).

Prova dal terminale senza pannello:

```bash
python -m scripts.prova_lettura percorso/distinta.jpg
```

Test (con dati inventati, nessuna chiamata all'API):

```bash
pytest
```

## Privacy

Le distinte contengono dati personali (nomi, date di nascita, documenti). Non vengono salvate
sul server né committate nel repository (`.gitignore` esclude immagini e PDF). Le credenziali
stanno solo nel file `.env`.

## Prossime fasi

1. ~~Prototipo di lettura~~
2. Verifica del portale: osservare i menu di "Liste Gara" e come vengono salvate le selezioni
3. Automazione controllata con Playwright su una partita di prova, senza invio definitivo
4. Collaudo campo per campo
