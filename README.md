# Testreferto

Agente per ridurre il lavoro manuale nella compilazione del referto arbitrale su Sinfonia4You.

Il programma fa due cose:

1. **Lettura delle distinte.** Nella pagina web si carica la foto o il PDF della distinta della
   squadra di casa (a sinistra) e di quella ospite (a destra), poi **Prosegui**. Per ogni
   calciatore vengono estratti numero, cognome, nome e data di nascita (i primi 11 sono titolari),
   mostrati in due tabelle (titolari e riserve) correggibili a mano.
2. **Compilazione di Sinfonia4You.** Nella stessa pagina si scrive la gara (parole che la
   identificano in Gestione Referti) e si preme **Compila Sinfonia4You**. Il server apre il portale,
   entra nella gara, segna "Disputata Regolarmente" e "Adeguate senza Forza Pubblica" + Ambulanza
   "NON Presente" (passando da una scheda all'altra con "Successivo"), compila le Liste Gara di
   entrambe le squadre e preme "Salva Tutto". La pagina mostra l'avanzamento, l'esito di ogni
   giocatore (selezionato, nuovo, da verificare) e lo screenshot finale.

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

Titolari e riserve si decidono dalla posizione nella lista, non dal numero di maglia: i primi 11
giocatori sono titolari (anche con numeri come 13 o 16), dal 12° in poi riserve.

La divisione tra cognome e nome la fa il programma, non il modello: la distinta stampa prima il
cognome, quindi il cognome è la prima parola più le eventuali particelle davanti (DAL CERO, DALLA
POZZA, DI BARI) e il resto è il nome (GRIGATO / MATTEO ANTONIO). Nessun avviso sulla divisione.

I controlli sulla distinta (`app/checks.py`) segnalano numeri ripetuti o mancanti, nomi doppi,
date di nascita mancanti o non valide e ogni campo letto con incertezza.

## Installazione su Windows

1. Scarica il progetto (su GitHub: branch `claude/relaxed-planck-yatgnx`, Code → Download ZIP) ed
   estrai la cartella. Serve Python 3.10 o successivo già installato.
2. Doppio clic su **`installa.bat`**: crea l'ambiente `.venv`, installa le librerie e il browser per
   Sinfonia4You e crea il file `.env` dal modello (se non esiste). Non avvia il programma.
3. Apri `.env` con il Blocco note e scrivi le chiavi.
4. Quando vuoi usarlo: doppio clic su **`avvia.bat`**, si apre http://localhost:8000.
5. Per passare all'ultima versione: doppio clic su **`aggiorna.bat`** (scarica da GitHub e
   sostituisce i file; non tocca `.env`, `.venv` ed `esplorazione`).

## Avvio (Linux / macOS)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # chiave API, utente/password del pannello e credenziali Sinfonia4You
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

La lettura delle distinte usa YepAPI se nel `.env` c'è `YEPAPI_API_KEY` (modello in
`YEPAPI_MODEL`, predefinito `anthropic/claude-haiku-5.5`), altrimenti l'API Anthropic con
`ANTHROPIC_API_KEY`. Sulla distinta di prova Haiku 5.5 e Sonnet 5.5 hanno letto 20 giocatori su
20 senza errori; Haiku 4.5 solo 9 su 20.

Il file `.env` viene letto automaticamente all'avvio (anche su Windows: basta copiare
`.env.example` in `.env` e compilarlo).

Apri `http://<indirizzo-server>:8000` dal telefono. Il pannello è protetto da utente e password
(`APP_USER` / `APP_PASSWORD`); su una VPS va messo dietro HTTPS (es. Caddy o Nginx).

Prova dal terminale senza pannello:

```bash
python -m scripts.prova_lettura percorso/distinta.jpg
```

In alternativa alla pagina, compilazione da terminale con il JSON scaricato (browser visibile):

```bash
playwright install chromium
python -m scripts.compila_sinfonia liste_gara.json --gara "SAREGO LIONA"
```

`--gara` è il nome (anche parziale) di una o entrambe le squadre, es. "Tezze" o "Tezze vs Brendola":
parole come "vs" o "contro" sono ignorate e, se più gare corrispondono, vale quella con il "+". A ogni passo
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
