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

La distinta stampa prima il cognome: se la colonna "Cognome e nome" ha due parole, la prima è il
cognome e la seconda il nome. Con tre o più parole vale la lettura del modello, e se cognome +
nome non ricompongono il testo stampato il giocatore viene segnalato.

I controlli sulla distinta (`app/checks.py`) segnalano numeri ripetuti o mancanti, nomi doppi,
date di nascita mancanti o non valide e ogni campo letto con incertezza.

## Avvio

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # chiave API, utente/password del pannello e credenziali Sinfonia4You
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

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
