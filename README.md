# Odwołania2JSON

Zamiana dokumentów sprawy odwoławczej KIO (PDF) na kanoniczny JSON zgodny ze schematami UZP — wyzwanie **ODWOŁANIA2JSON, HackNation 2026**.

Aplikacja przyjmuje PDF, **rozpoznaje rodzaj dokumentu** (odwołanie, pełnomocnictwo, potwierdzenie przelewu), **wyodrębnia dane** i zapisuje **JSON nazwany jak plik źródłowy**. Każda wartość ma zapisane źródło (fragment i pozycja w tekście), więc ekstrakcja jest w pełni przejrzysta. Nowe typy dokumentów i pola dodaje się w plikach YAML, bez zmian w kodzie.

| | |
|---|---|
| Język | Python 3.13+ |
| Zależności | `requirements.txt`, wyłącznie open source |
| Sprzęt | CPU, bez GPU (OCR na ONNX Runtime / Tesseract) |
| LLM | opcjonalny, otwarty model przez API zgodne z OpenAI |
| Wynik na zbiorze treningowym | **F1 = 1.000** (180 dokumentów, 2032 pola) |

## Szybki start

```bash
pip install -r requirements.txt
python -m odwolania2json run          # ./input  ->  ./output
```

Albo skryptem, który sam tworzy środowisko przy pierwszym uruchomieniu:

```bash
./start.sh            # Linux / macOS
start.bat             # Windows
```

Pliki z `input/` trafiają do `output/` z zachowaniem struktury folderów:

```
input/case1/odwolanie_nr_1.pdf        ->  output/case1/odwolanie_nr_1.json
input/case1/pelnomocnictwo_nr_1.pdf   ->  output/case1/pelnomocnictwo_nr_1.json
input/case1/przelew_nr_1.pdf          ->  output/case1/przelew_nr_1.json
```

Typ dokumentu jest ustalany **z treści**, nie z nazwy pliku. Dokument nierozpoznany nie dostaje pliku JSON.

### Polecenia CLI

| Polecenie | Opis |
|---|---|
| `python -m odwolania2json run [-i input] [-o output] [--trace traces]` | tryb wsadowy, opcjonalnie z plikami śladu ekstrakcji |
| `python -m odwolania2json extract plik.pdf [--trace] [--type przelew]` | JSON lub ślad dla jednego pliku |
| `python -m odwolania2json serve [--port 8000]` | interfejs webowy |
| `python -m odwolania2json eval <katalog_z_danymi> [--errors 20] [--strict]` | precyzja, czułość i F1 względem plików referencyjnych |
| `python -m odwolania2json types` | lista typów dokumentów, ekstraktorów i normalizatorów |
| `python -m odwolania2json llm-check` | test połączenia z modelem językowym |

### Interfejs webowy

```bash
python -m odwolania2json serve        # http://127.0.0.1:8000
```

- **Dokumenty:** kafelki KPI, filtr typu, tabela z kompletnością pól i eksportem.
- **Szczegół:** podgląd PDF obok JSON; zakładka *Źródła* pokazuje metodę i fragment tekstu dla każdego pola, a kliknięcie podświetla go w tekście dokumentu; *Klasyfikacja* pokazuje punktację typów.

### Tryby pracy

- **Szybki** (domyślny): same reguły z YAML, bez sieci i bez LLM. Daje maksimum punktów za „moc modelu” w ocenie UZP.
- **Dokładny** (opcjonalny, *Ustawienia*): reguły plus niezależna weryfikacja każdego pola przez otwarty LLM. Rozbieżności trafiają do zakładki *Weryfikacja*, gdzie można poprawić wartość, wybrać wartość LLM albo zatwierdzić puste pole. Do tego **streszczenie dokumentu** i **Asystent**: pytania o wszystkie wgrane dokumenty (RAG z BM25 na CPU), z odpowiedzią wyłącznie z odnalezionych fragmentów i z klikalnymi źródłami.

**Sprawy:** dokumenty są automatycznie grupowane po numerze postępowania (sekcja `case:` w YAML). Interfejs pokazuje zgodność stron między odwołaniem, pełnomocnictwem i przelewem oraz brakujące dokumenty.

**Dokumenty spoza puli** dostają pusty JSON `{}` i komunikat „nie udało się dopasować typu dokumentu” (`unmatched_output` w `settings.yaml`).

### Docker Compose

```bash
docker compose up -d                              # UI na http://localhost:8000
docker compose --profile batch run --rm batch     # ./input -> ./output
```

### Aplikacja desktopowa i aktualizacje

Na stronie projektu (GitHub Pages) i w zakładce **Releases** są instalator Windows, paczka przenośna Windows (`.zip`) oraz paczka Linux (`.tar.gz`) z sumami SHA-256.

**Aktualizacje małymi łatkami:** każde wydanie zawiera też `Odwolania2JSON-<platforma>.pack` i `.manifest.json`. Zainstalowana aplikacja (dzwonek w prawym górnym rogu) porównuje swoje pliki z manifestem i **pobiera tylko pliki, które się zmieniły**, przez zapytania HTTP Range. Przy zmianie samego kodu to zwykle kilkaset kB. Każdy plik jest weryfikowany SHA-256, podmiana następuje po zamknięciu aplikacji, a foldery `config/`, `input/` i `output/` nie są ruszane. Instalator również nie nadpisuje lokalnej konfiguracji.

## Architektura

```
PDF ──► pdftext ──► classifier ──► engine (+ extractors) ──► [llm] ──► JSON
         │ OCR        YAML: classify   YAML: sections, fields,     opcjonalnie     template
         ▼            (słowa klucz.)   extract chains, normalize   uzupełnia null
      ocr.py
```

| Moduł | Rola |
|---|---|
| `pdftext.py` | tekst z PDF (`pypdf`), czyszczenie Unicode, stopki „Strona X z Y”, akcenty z LaTeX-a; strony bez tekstu idą do OCR |
| `ocr.py` | OCR na CPU: Tesseract (`pol`), jeśli jest zainstalowany, inaczej RapidOCR (PP-OCRv5 Latin, ONNX); cache na dysku, poprawki typowych pomyłek |
| `fuzzy_re.py` | wyrażenia regularne niewrażliwe na polskie znaki (OCR często je gubi); wartości są wycinane z oryginalnego tekstu |
| `classifier.py` | punktacja słów kluczowych i wzorców z sekcji `classify` każdego typu, próg w `settings.yaml` |
| `engine.py` | silnik: sekcje dokumentu, łańcuchy ekstraktorów, normalizacja, szablon wyniku, ślad (metoda, fragment, pozycja) |
| `extractors.py` | ekstraktory domenowe (strony postępowania, mocodawcy z podpisującymi, pełnomocnicy, data czynności), rejestrowane po nazwie |
| `normalizers.py` | daty, kwoty, rachunki, KRS/NIP, numery BZP/TED, imiona i nazwiska |
| `llm.py` | opcjonalne uzupełnianie pustych pól przez otwarty model (Ollama, vLLM, llama.cpp lub dostawca w UE) |
| `pipeline.py` | przetwarzanie pliku i drzewa katalogów, zapis JSON i śladów |
| `evaluate.py` | F1 zgodne z zasadami UZP: zła wartość = FP, brak = FN, długie napisy zaliczane przy ≥ 80% podobieństwa |
| `web/` | FastAPI i jednostronicowy interfejs bez zewnętrznych zasobów |

Pełny opis: [docs/architektura.md](docs/architektura.md).

## Dodanie nowego typu dokumentu

Wystarczy nowy plik `config/document_types/<typ>.yaml`. Przykład i opis wszystkich ekstraktorów: [docs/nowy-typ-dokumentu.md](docs/nowy-typ-dokumentu.md). Zmiany są widoczne po ponownym uruchomieniu albo po kliknięciu *Przeładuj konfigurację* w interfejsie.

## LLM (opcjonalnie)

Reguły nie potrzebują sieci ani GPU, a LLM jest **opcjonalny i domyślnie wyłączony**. Włącza się go w interfejsie (*Ustawienia*: przełącznik, adres, model, klucz i przycisk „Testuj połączenie”), dla pojedynczego dokumentu przyciskiem *Uzupełnij przez LLM*, w CLI flagą `--llm` albo zmiennymi środowiskowymi (wzór w `.env.example`):

```bash
O2J_LLM_ENABLED=true
O2J_LLM_URL=http://localhost:11434/v1        # Ollama / vLLM / llama.cpp / dostawca w UE
O2J_LLM_MODEL=hf.co/speakleash/Bielik-4.5B-v3.0-Instruct-GGUF:Q8_0
O2J_LLM_API_KEY=...
```

Model uzupełnia tylko pola wskazane w sekcji `llm.fields` danego typu, które reguły zostawiły puste. Takie pola są oznaczone w śladzie jako `source: llm`. Połączenie sprawdzisz poleceniem `python -m odwolania2json llm-check`. Konfiguracja Ollamy na własnym komputerze i wybór dostawcy w UE: [docs/llm.md](docs/llm.md).

## Jakość

```bash
python -m odwolania2json eval <katalog dane/ z repozytorium UZP>
```

| Zbiór | F1 |
|---|---|
| 60 zestawów treningowych UZP (180 dokumentów) | 1.000 |
| 150 syntetycznych spraw z haczykami (`tools/generate_testset.py`) | 1.000 |
| 12 dokumentów spoza puli UZP + 106 orzeczeń KIO + 5 innych pism | 100% odrzuconych |
| symulowane skany (150 DPI, rozmycie, obrót) | ok. 0.97 |

Same modele LLM bez reguł (`tools/eval_llm.py`, 16 spraw): Bielik-4.5B F1 0.78, Bielik-1.5B F1 0.47. Dlatego LLM służy tylko do weryfikacji i funkcji dodatkowych, a wynik JSON pochodzi z reguł.

## Rozwój

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m pyflakes odwolania2json tools packaging tests
```

Workflowy GitHub Actions:
- `checks`: testy i test wsadowy przy każdym pushu;
- `bump version`: wersja zawsze o jeden patch powyżej ostatniego wydania;
- `release`: budowa paczek PyInstaller i instalatora Inno Setup, publikacja wydania oraz obrazu Docker w GHCR;
- `download page`: strona z pobieraniem na GitHub Pages.
