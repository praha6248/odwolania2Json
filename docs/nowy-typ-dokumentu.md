# Jak dodać nowy typ dokumentu

Nowy typ to jeden plik YAML w `config/document_types/`. Nie trzeba zmieniać kodu ani przebudowywać aplikacji: wystarczy ponowne uruchomienie albo *Przeładuj konfigurację* w interfejsie.

## Przykład: wezwanie do uzupełnienia wpisu

```yaml
name: wezwanie_wpis
label: Wezwanie do uzupełnienia wpisu
description: Pismo Prezesa KIO wzywające do uzupełnienia braku wpisu od odwołania.

classify:
  head_chars: 800
  head_keywords:
    wezwanie: 5
    uzupełnienia: 2
  keywords:
    wpis od odwołania: 3
    krajowa izba odwoławcza: 1
  filename_hints:
    wezwanie: 3
  require:
    - name: sygnatura KIO
      scope: all
      any: ['KIO\s*\d+/\d{2}']
  negative:
    '^\s*(?:WYROK|POSTANOWIENIE)\s*$': 30

sections:
  naglowek:
    start: '\A'
    end: ['^\s*WEZWANIE']

fields:
  sygnatura:
    description: Sygnatura sprawy KIO, np. KIO 1234/26.
    normalize: [strip]
    extract:
      - type: regex
        pattern: '(KIO\s*\d+/\d{2})'
  data_pisma:
    description: Data pisma (ISO).
    normalize: [date_iso]
    extract:
      - type: regex
        scope: naglowek
        pattern: 'dnia\s+(\d{1,2}\s+\w+\s+\d{4}|\d{2}\.\d{2}\.\d{4})'
  kwota:
    description: Kwota brakującego wpisu.
    normalize: [amount]
    extract:
      - type: label
        labels: ['kwot\w+', 'w wysokości']
        line_start: false
        value: '\d[\d  .,]*\d'
  termin_dni:
    normalize: [int]
    extract:
      - type: regex
        pattern: 'w terminie\s+(\d+)\s+dni'
      - type: const
        value: 3

llm:
  fields: [sygnatura, data_pisma, kwota]

template:
  Wezwanie:
    sygnatura: $sygnatura
    data: $data_pisma
    kwota: $kwota
    termin_dni: $termin_dni
```

Sprawdzenie:

```bash
python -m odwolania2json types                              # czy typ się wczytał
python -m odwolania2json extract wezwanie.pdf --trace       # wynik i źródło każdego pola
python -m odwolania2json eval katalog_z_przykladami         # F1, gdy są pliki referencyjne
```

## Elementy pliku

| Klucz | Znaczenie |
|---|---|
| `name` | identyfikator typu (używany w API i UI) |
| `label` | nazwa wyświetlana |
| `classify` | wagi słów i wzorców; dokument dostaje typ o najwyższej sumie, jeśli przekracza próg `min_classification_score`. `require`: warunki konieczne (`any`: lista wzorców, `scope`: `head` albo `all`); niespełniony oznacza 0 pkt. `negative`: wzorce cech innych dokumentów (np. `WYROK`, `Sygn. akt`) odejmujące punkty |
| `sections` | nazwane fragmenty dokumentu: `start`, `end` (regex lub lista), `include_start`, `max_chars` |
| `fields` | pola: `extract` (łańcuch ekstraktorów), `normalize`, `default`, `description` (opis dla człowieka i LLM) |
| `llm.fields` | pola, które model może uzupełnić, gdy reguły zostawią je puste |
| `template` | kształt wyniku JSON; napisy `$pole` są zastępowane wartościami |

Wzorce dopasowują się bez względu na wielkość liter i polskie znaki, więc `Odwołujący` znajdzie też `ODWOLUJACY` z OCR.

## Ekstraktory wbudowane

| `type` | Parametry | Działanie |
|---|---|---|
| `regex` | `pattern`, `group` (1), `occurrence` (0, może być ujemne), `scope`, `dotall` | grupa z n-tego dopasowania |
| `label` | `labels`, `value` (regex wartości), `until` (regex końca, dla wartości wieloliniowych), `line_start` (true), `scope` | wartość po etykiecie w tej samej lub następnej linii |
| `keyword_map` | `options: [{value, priority, keywords: [regex…]}]`, `scope` | wybór opcji o najwyższym priorytecie i najwcześniejszym dopasowaniu |
| `map` | `source`, `mapping` | słownik wartości innego pola (np. id → opis kanoniczny) |
| `ref` | `source`, `path` | kopia (fragmentu) innego pola |
| `present` | `source`, `yes`, `no` | flaga zależna od tego, czy inne pole ma wartość |
| `const` | `value` | stała |
| `appellants` | `label`, `stop` | odwołujący lub lider konsorcjum, z pełnomocnikiem, kancelarią i e-mailem |
| `contracting_authorities` | `label`, `stop` | zamawiający, także wspólni, z flagą prowadzącego |
| `principals` | `principal_leads` | mocodawcy (osoby prawne, przedsiębiorcy, konsorcja) z podpisującymi |
| `attorneys` | | pełnomocnicy z tytułem zawodowym i PESEL |
| `dated_event` | `pattern`, `scope` | pierwsza data zdarzenia w zakresie |

`scope` przyjmuje nazwę sekcji albo listę nazw (używana jest pierwsza znaleziona sekcja).

## Normalizatory

`strip`, `strip_quotes`, `digits`, `account`, `date_iso`, `amount`, `ted`, `bzp`, `int`, `person_name`, `entity_name`. Pełną listę wypisuje `python -m odwolania2json types`.

## Własny ekstraktor w Pythonie (gdy YAML nie wystarcza)

```python
# moje_wtyczki.py
from odwolania2json.engine import Evidence, extractor
from odwolania2json import fuzzy_re as fx

@extractor("sygnatura_kio")
def sygnatura_kio(ctx, spec):
    """Find a KIO case number such as 'KIO 1234/26'."""
    match = fx.search(r"KIO\s*(\d+/\d{2})", ctx.text)
    return (f"KIO {match.group(1)}", Evidence("sygnatura_kio", match.group(0), match.start(), match.end())) if match else (None, None)
```

```yaml
# config/settings.yaml
plugins:
  - odwolania2json.extractors
  - moje_wtyczki
```

Od tej chwili `type: sygnatura_kio` działa w każdym pliku YAML.
