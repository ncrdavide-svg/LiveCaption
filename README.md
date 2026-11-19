<p align="center"><img src="assets/LiveCaption.png" width="160" alt="LiveCaption"></p>

<h1 align="center">LiveCaption</h1>

<p align="center">Sottotitoli dal vivo: ascolta il microfono dalla scheda audio, trascrive quello che dici e lo mostra a schermo pieno sul secondo monitor, con la traduzione in inglese sotto.</p>

<p align="center">
  <a href="https://github.com/ncrdavide-svg/LiveCaption/releases/latest/download/LiveCaption.zip"><b>⬇ Scarica LiveCaption per Windows 10/11 (zip)</b></a><br>
  <img src="https://img.shields.io/github/v/release/ncrdavide-svg/LiveCaption?label=versione&color=2ea44f" alt="versione"> · <a href="https://github.com/ncrdavide-svg/LiveCaption/releases">tutte le versioni</a>
</p>

Nessuna installazione: scompatta lo zip dove vuoi e avvia `LiveCaption\LiveCaption.exe`.

> Al primo avvio Windows potrebbe mostrare "Windows ha protetto il PC" (l'exe non è firmato): clicca **Ulteriori informazioni → Esegui comunque**.

Tutto funziona **offline**, sul portatile: nessun servizio online, nessun costo. Serve internet solo al primo avvio, per scaricare i modelli (circa 4 GB).

## Funzioni

- **Ingresso audio a scelta**: la scheda Focusrite viene selezionata da sola; scegli l'ingresso 1, l'ingresso 2 o il mix dei due. Un indicatore di livello mostra se l'audio arriva.
- **Trascrizione in italiano** in tempo reale con [Vosk](https://alphacephei.com/vosk/): le parole compaiono mentre parli.
- **Punteggiatura e maiuscole** aggiunte a fine frase da un modello dedicato.
- **Un colore per relatore**: riconosce chi parla dalla voce, anche con tutti sullo stesso microfono (4 colori personalizzabili, sensibilità regolabile).
- **Traduzione in inglese** sotto ogni frase, in corsivo.
- **Display** a schermo pieno sul monitor scelto, oppure in una finestra ridimensionabile.
- Colore di sfondo, font e grandezza del testo a scelta; ogni funzione si può spegnere per alleggerire il PC.

## Requisiti

- Windows 10 o 11 a 64 bit.
- Circa 4 GB di memoria libera mentre gira (8 GB di RAM consigliati).
- Circa 5 GB su disco per i modelli.

## Modelli

Al primo avvio LiveCaption scarica in `%LOCALAPPDATA%\LiveCaption\models`:

| Modello | Uso |
|---|---|
| `vosk-model-it-0.22` | trascrizione italiano |
| `vosk-model-spk-0.4` | riconoscimento relatori |
| `oliverguhr/fullstop-punctuation-multilang-large` | punteggiatura |
| `Helsinki-NLP/opus-mt-it-en` | traduzione italiano → inglese |

Versione portatile: se accanto a `LiveCaption.exe` c'è una cartella `models`, usa quella.

## Impostazioni

Vengono salvate in `LiveCaption.settings.json`, accanto all'exe (oppure in `%LOCALAPPDATA%\LiveCaption` se la cartella non è scrivibile).

## Compilare dai sorgenti

Serve Python 3 a 64 bit.

```bat
powershell -ExecutionPolicy Bypass -File build.ps1
```

Crea `dist\LiveCaption\LiveCaption.exe`. Con `-Install` lo copia anche in `%LOCALAPPDATA%\Programs\LiveCaption` e aggiunge i collegamenti nel menu Start e sul desktop.

Per provarlo senza compilare: `python LiveCaption.py` (dopo `pip install -r requirements.txt`).

L'icona si rigenera con `python tools/make_icon.py` (richiede Pillow).

## Supporta il progetto

Se LiveCaption ti è utile, offrimi un caffè: [buymeacoffee.com/cin8](https://buymeacoffee.com/cin8)
