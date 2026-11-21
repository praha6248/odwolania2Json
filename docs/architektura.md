# Architektura Odwołania2JSON

## Przepływ

```
            ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐   ┌─────────┐   ┌──────────┐
 PDF  ───►  │ pdftext      │──►│ classifier   │──►│ engine                   │──►│ llm     │──►│ template │──► JSON
            │ + ocr        │   │ (YAML)       │   │ sections → fields → norm │   │ (opcja) │   │ (YAML)   │
            └──────────────┘   └──────────────┘   └──────────────────────────┘   └─────────┘   └──────────┘
                                                            │
                                                            └──► ślad: metoda, fragment, pozycja (UI / --trace)
```

1. **Tekst** (`pdftext.py`). `pypdf` wyciąga warstwę tekstową stron. Tekst jest normalizowany: NFC, scalanie akcentów z generatorów typu LaTeX (`˛a` → `ą`), usuwanie miękkich dzielników i stopek „Strona X z Y”. Strony z mniej niż `ocr.min_chars_per_page` znakami trafiają do OCR.
2. **OCR** (`ocr.py`). Strona jest renderowana przez `pypdfium2`. Silnik wybierany jest według `ocr.engines`: Tesseract z modelem `pol`, jeśli jest dostępny (obraz Docker), inaczej RapidOCR (PP-OCRv5 Latin, ONNX Runtime, CPU). Wynik trafia do cache po SHA-1 pliku i przechodzi poprawki typowych pomyłek (`o.0.` → `o.o.`, `ž` → `ż`, cyfry/litery).
3. **Klasyfikacja** (`classifier.py`). Każdy typ ma w YAML sekcję `classify` z wagami: słowa w nagłówku (`head_keywords`), w całym tekście (`keywords`), wyrażenia regularne (`patterns`) i wskazówki z nazwy pliku (`filename_hints`). Porównanie ignoruje wielkość liter, odstępy i polskie znaki. Wygrywa najwyższy wynik powyżej `min_classification_score`; poniżej progu dokument nie dostaje JSON.
4. **Ekstrakcja** (`engine.py`). Dla wybranego typu:
   - **sekcje**: fragmenty dokumentu wyznaczone regexami `start` i `end` (np. nagłówek, blok „dotyczy”, pierwszy zarzut), do których zawężane są wyszukiwania;
   - **pola**: każde pole ma łańcuch ekstraktorów (`extract`), próbowanych po kolei do pierwszej niepustej wartości, po czym działają normalizatory (`normalize`);
   - **szablon**: struktura wyniku z odwołaniami `$pole`, odpowiadająca schematowi UZP 1:1.
5. **LLM** (`llm.py`, opcjonalnie). Pola z `llm.fields`, które reguły zostawiły puste, wysyłane są z opisami (`description`) do modelu przez API zgodne z OpenAI. Odpowiedź przechodzi przez te same normalizatory, a pola pochodne (`map`, `ref`, `present`) są przeliczane ponownie.
6. **Zapis** (`pipeline.py`). `output/` odwzorowuje strukturę `input/`, a plik JSON ma nazwę pliku PDF. Opcjonalnie powstaje `*.trace.json` z pełnym śladem ekstrakcji.

## Przejrzystość ekstrakcji

Każde pole niesie `FieldResult`: wartość, źródło (`rules` albo `llm`), nazwę metody (np. `label:Rachunek odbiorcy`, `keyword:zaniechał unieważnienia`), fragment tekstu i pozycję w dokumencie. Ślad jest dostępny:
- w interfejsie (zakładka *Źródła*; kliknięcie podświetla fragment w tekście),
- w CLI: `python -m odwolania2json extract plik.pdf --trace` albo `run --trace traces/`.

## Odporność na OCR

`fuzzy_re.py` składa tekst i wzorzec do liter bazowych znak po znaku (`ł` → `l`, `ą` → `a`, …). Długość tekstu się nie zmienia, więc pozycje dopasowań wskazują wprost na oryginalny tekst, a wartości zachowują oryginalną pisownię. Wszystkie ekstraktory korzystają z tego mechanizmu, dlatego wzorce w YAML pisze się normalnie, z polskimi znakami.

## Rozszerzalność

| Co | Gdzie | Zmiana kodu? |
|---|---|---|
| nowy typ dokumentu | `config/document_types/<typ>.yaml` | nie |
| nowe pole w istniejącym typie | sekcje `fields` i `template` w YAML | nie |
| nowe słowa kluczowe / etykiety / wzorce | YAML | nie |
| nowy ekstraktor w Pythonie | dowolny moduł z `@extractor("nazwa")`, wpisany w `plugins` w `settings.yaml` | tylko ten moduł |
| nowy normalizator | `@normalizer("nazwa")` w module wtyczki | tylko ten moduł |
| inny model LLM / dostawca | `.env` albo `settings.yaml` | nie |
| inny silnik OCR / kolejność | `ocr.engines` w `settings.yaml` | nie |

## Wydajność

PDF z warstwą tekstu: ok. 0,01–0,15 s na dokument na zwykłym CPU. OCR: kilka do kilkunastu sekund na stronę, z cache przy ponownym przetwarzaniu.

## Dystrybucja

- `start.sh` / `start.bat`: lokalne środowisko i tryb wsadowy;
- `Dockerfile` i `docker-compose.yml`: interfejs webowy oraz profil `batch` (Tesseract `pol` w obrazie);
- `tools/build.py`: PyInstaller (`--onedir`), paczki `.zip` / `.tar.gz` z SHA-256, instalator Inno Setup (`packaging/installer.iss`);
- GitHub Actions: `checks`, `bump version`, `release` (Windows i Linux, GHCR), `download page` (GitHub Pages);
- `update_check.py`: aplikacja porównuje swoją wersję z `releases/latest`.
