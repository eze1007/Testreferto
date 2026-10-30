# Testreferto

Agente per ridurre il lavoro manuale nella compilazione del referto arbitrale su Sinfonia4You.

Il programma fa una cosa sola: da una foto o un PDF della distinta di gara estrae, per ogni
calciatore, **numero, cognome e nome**. L'arbitro rivede l'elenco in una tabella, corregge se serve
e lo scarica (JSON) o lo copia.

I controlli automatici (`app/checks.py`) segnalano numeri ripetuti o mancanti, nomi doppi, cognome
o nome vuoti e ogni campo che il modello ha letto con incertezza.

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

Le distinte contengono dati personali. Non vengono salvate
sul server né committate nel repository (`.gitignore` esclude immagini e PDF). Le credenziali
stanno solo nel file `.env`.
