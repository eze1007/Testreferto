# Testreferto

Agente per ridurre il lavoro manuale nella compilazione del referto arbitrale su Sinfonia4You.

Il programma fa due cose:

1. **Lettura della distinta.** Da una foto o un PDF estrae, per ogni calciatore, numero, cognome,
   nome, data di nascita e se è una riserva `(R)`. L'arbitro rivede l'elenco in una tabella,
   corregge se serve e scarica il file `distinta.json`.
2. **Compilazione di Sinfonia4You.** Partendo da `distinta.json` apre il portale, entra nella gara,
   segna "Disputata Regolarmente" e "Adeguate senza Forza Pubblica" + Ambulanza "NON Presente"
   (passando da una scheda all'altra con "Successivo"),
   poi nelle Liste Gara imposta numero e nominativo di ogni calciatore nella colonna della squadra.

Regole della compilazione (`app/sinfonia.py`):

- il nominativo si sceglie dalla tendina solo se cognome, nome e data di nascita coincidono
  nelle lettere (non contano maiuscole, spazi, accenti, apostrofi e l'ordine COGNOME NOME /
  NOME COGNOME; l'ID è ignorato); una lettera diversa o mancante è un altro giocatore; con più
  voci identiche si prende la prima;
- se non c'è una voce identica, anche quando ce n'è una simile, il calciatore viene creato con
  "Aggiungi persona" (cognome, nome, data di nascita);
- la data di nascita viene digitata a mano nel campo; il sesso resta MASCHILE (predefinito);
- documenti e capitano non vengono toccati;
- alla fine viene premuto **"Salva Tutto"**; "Invia al G.S." non viene mai premuto. Il browser
  resta aperto per il controllo.

La distinta stampa prima il cognome: se la colonna "Cognome e nome" ha due parole, la prima è il
cognome e la seconda il nome. Con tre o più parole vale la lettura del modello, e se cognome +
nome non ricompongono il testo stampato il giocatore viene segnalato.

I controlli sulla distinta (`app/checks.py`) segnalano numeri ripetuti o mancanti, nomi doppi,
date di nascita mancanti o non valide e ogni campo letto con incertezza.

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

Compilazione di Sinfonia4You (browser visibile; `--lato` è la squadra della distinta):

```bash
playwright install chromium
python -m scripts.compila_sinfonia distinta.json --gara "SAREGO LIONA" --lato ospite
```

`--gara` sono parole che identificano una sola riga nella lista di Gestione Referti. A ogni passo
vengono salvati screenshot e pagina in `esplorazione/`: se qualcosa non funziona servono a capire
dove. Contengono dati personali.

Test (dati inventati; la compilazione è provata su una copia finta del portale in
`tests/portale_finto.py`, nessun accesso a Sinfonia4You):

```bash
pytest
```

## Privacy

Le distinte contengono dati personali. Non vengono salvate
sul server né committate nel repository (`.gitignore` esclude immagini e PDF). Le credenziali
(API e Sinfonia4You) stanno solo nel file `.env`.
