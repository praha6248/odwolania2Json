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

## Jak to działa

1. **Wgrywasz PDF-y sprawy:** przeciągasz je na stronę albo wrzucasz do folderu `input/`. Nazwy plików nie mają znaczenia.
2. **Tekst:** aplikacja czyta warstwę tekstową PDF. Strony bez tekstu (skany) przechodzą przez OCR na CPU z prostowaniem strony i słownikową korektą polskich słów.
3. **Rozpoznanie typu:** punktacja słów kluczowych, warunki konieczne i kary za cechy innych pism (np. „WYROK”, „Sygn. akt”), wszystko w YAML. Dokument spoza puli dostaje pusty JSON `{}`.
4. **Ekstrakcja:** dla rozpoznanego typu działają reguły z `config/document_types/<typ>.yaml` (sekcje dokumentu, etykiety, wzorce, słowniki, normalizacja dat, kwot, rachunków, numerów BZP i TED). Każde pole zapamiętuje, z którego fragmentu pochodzi.
5. **Wynik:** JSON zgodny ze schematem UZP, nazwany jak plik źródłowy, w tej samej strukturze folderów co wejście.
6. **Tryb dokładny (opcjonalny):** otwarty LLM niezależnie sprawdza pola. Rozbieżności trafiają do weryfikacji, a nie do wyniku. Do tego streszczenia i asystent z cytatami.

### Funkcje dodatkowe (bez modelu językowego)

- **Kontrola formalna sprawy:** dla każdej sprawy aplikacja sprawdza krzyżowo trzy dokumenty: czy odwołujący jest mocodawcą pełnomocnictwa, czy pełnomocnik z odwołania ma pełnomocnictwo, czy tytuł przelewu wskazuje postępowanie, czy opłata poprzedza odwołanie, czy opłata skarbowa pokrywa 17 zł na pełnomocnika i czy odwołanie mieści się w terminie z art. 515 Pzp (5 lub 10 dni, z przesunięciem na dzień roboczy po weekendach i świętach). Reguły są w `config/formal_checks.yaml`.
- **Źródło w PDF:** kliknięcie pola podświetla wartość bezpośrednio na stronie dokumentu.
- **Kreator nowego typu dokumentu:** wgrywasz przykład, zaznaczasz wartości myszką, a kreator proponuje reguły (etykieta, wzorzec, normalizacja), pokazuje wynik na żywo, sprawdza inne wgrane dokumenty i zapisuje zwykły plik YAML.
- **Eksport do Excela i CSV:** zestawienie dokumentów, arkusz na każdy typ z polami JSON w kolumnach i arkusz z kontrolą formalną.
- **Wyszukiwarka w dokumentach:** lokalne wyszukiwanie fragmentów (BM25) z podświetleniem słów. Z włączonym LLM ta sama zakładka odpowiada na pytania z cytatami.
- **Anonimizacja PDF (na żądanie):** przycisk „Anonimizuj PDF” albo polecenie `anonymize` tworzy osobną kopię z zaczernionymi imionami i nazwiskami osób (także w odmianie), numerami PESEL, e-mailami i telefonami. Strony kopii są obrazami, więc zakrytego tekstu nie da się skopiować. Oryginał i JSON pozostają bez zmian.

### Zrzuty ekranu

| | |
|---|---|
| ![Lista dokumentów](docs/screenshots/01-dokumenty.png) **Dokumenty:** strefa przeciągania, liczniki, tabela z typem, stroną, numerem postępowania i kompletnością pól, eksport JSON, Excel i CSV. | ![Dokument i JSON](docs/screenshots/02-dokument-json.png) **Analiza dokumentu:** strony PDF obok wyniku JSON. |
| ![Źródło w PDF](docs/screenshots/03-zrodlo-w-pdf.png) **Przejrzystość:** kliknięcie pola w zakładce *Źródła* zaznacza wartość na stronie PDF. | ![Weryfikacja](docs/screenshots/04-weryfikacja.png) **Weryfikacja:** pola puste, niejednoznaczne lub rozbieżne z LLM, z fragmentem, edycją i zaznaczeniem w PDF. |
| ![Sprawy i kontrola formalna](docs/screenshots/05-sprawy-kontrola.png) **Sprawy:** grupowanie po numerze postępowania, zgodność stron, brakujące dokumenty i kontrola formalna. | ![Wyszukiwarka](docs/screenshots/06-wyszukiwarka.png) **Wyszukiwarka bez LLM:** najtrafniejsze fragmenty wszystkich dokumentów. |
| ![Kreator typu](docs/screenshots/07-kreator-typu.png) **Kreator nowego typu:** zaznaczenie wartości w przykładzie tworzy pole z regułą. | ![Podgląd kreatora](docs/screenshots/08-kreator-podglad.png) **Podgląd na żywo:** wartości pól, wynik JSON, rozpoznanie przykładu i innych dokumentów. |
| ![Streszczenie](docs/screenshots/09-streszczenie.png) **Streszczenie (tryb dokładny):** zarzuty, żądania, terminy i kwoty. | ![Asystent](docs/screenshots/10-asystent-llm.png) **Asystent z LLM:** odpowiedź wyłącznie z odnalezionych fragmentów, z klikalnymi źródłami. |
| ![Ustawienia](docs/screenshots/11-ustawienia.png) **Ustawienia:** tryb szybki lub dokładny, model, klucz, test połączenia. | |

Na telefonie nawigacja jest na dole ekranu, a tabela zamienia się w listę kart:

<p>
<img src="docs/screenshots/12-telefon-dokumenty.png" alt="Dokumenty na telefonie" width="260">
<img src="docs/screenshots/13-telefon-sprawy.png" alt="Sprawy na telefonie" width="260">
</p>

Widoki mają własne adresy (np. `#/sprawy`, `#/dokument/<id>/weryfikacja`), więc przetrwają odświeżenie strony.

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

Typ dokumentu jest ustalany **z treści**, nie z nazwy pliku. Dokument spoza puli dostaje plik z pustym JSON `{}`.

### Polecenia CLI

| Polecenie | Opis |
|---|---|
| `python -m odwolania2json run [-i input] [-o output] [--trace traces]` | tryb wsadowy, opcjonalnie z plikami śladu ekstrakcji |
| `python -m odwolania2json extract plik.pdf [--trace] [--type przelew]` | JSON lub ślad dla jednego pliku |
| `python -m odwolania2json serve [--port 8000]` | interfejs webowy |
| `python -m odwolania2json eval <katalog_z_danymi> [--errors 20] [--strict]` | precyzja, czułość i F1 względem plików referencyjnych |
| `python -m odwolania2json check [input]` | kontrola formalna każdej sprawy (folderu) według `config/formal_checks.yaml` |
| `python -m odwolania2json anonymize [input] [-o output_anonimizacja]` | kopie PDF z zaczernionymi danymi osobowymi |
| `python -m odwolania2json types` | lista typów dokumentów, ekstraktorów i normalizatorów |
| `python -m odwolania2json llm-check` | test połączenia z modelem językowym |

### Interfejs webowy

```bash
python -m odwolania2json serve        # http://127.0.0.1:8000
```

- **Dokumenty:** kafelki KPI, filtr typu, tabela z kompletnością pól i eksportem.
- **Szczegół:** podgląd PDF obok JSON; zakładka *Źródła* pokazuje metodę i fragment tekstu dla każdego pola, a kliknięcie zaznacza wartość na stronie PDF; *Klasyfikacja* pokazuje punktację typów; przycisk *Anonimizuj PDF* pobiera kopię z zaczernionymi danymi osobowymi.
- **Sprawy:** grupowanie, zgodność stron i kontrola formalna każdej sprawy.
- **Asystent:** wyszukiwarka fragmentów bez LLM, a z LLM odpowiedzi z cytatami.
- **Typy dokumentów:** lista typów z YAML i kreator nowego typu.

### Tryby pracy

- **Szybki** (domyślny): same reguły z YAML, bez sieci i bez LLM. Daje maksimum punktów za „moc modelu” w ocenie UZP.
- **Dokładny** (opcjonalny, *Ustawienia*): reguły plus niezależna weryfikacja każdego pola przez otwarty LLM. Rozbieżności trafiają do zakładki *Weryfikacja*, gdzie można poprawić wartość, wybrać wartość LLM albo zatwierdzić puste pole. Do tego **streszczenie dokumentu** i odpowiedzi **Asystenta** na pytania o wszystkie wgrane dokumenty (RAG z BM25 na CPU), wyłącznie z odnalezionych fragmentów i z klikalnymi źródłami.

**Sprawy:** dokumenty są automatycznie grupowane po numerze postępowania (sekcja `case:` w YAML). Interfejs pokazuje zgodność stron między odwołaniem, pełnomocnictwem i przelewem oraz brakujące dokumenty.

**Dokumenty spoza puli** dostają pusty JSON `{}` i komunikat „nie udało się dopasować typu dokumentu” (`unmatched_output` w `settings.yaml`).

### Docker Compose

```bash
docker compose up -d                              # UI na http://localhost:8000
docker compose --profile batch run --rm batch     # ./input -> ./output
```

### Aplikacja desktopowa i aktualizacje

Na stronie projektu (GitHub Pages) i w zakładce **Releases** są instalator Windows, paczka przenośna Windows (`.zip`) oraz paczka Linux (`.tar.gz`) z sumami SHA-256. W folderze aplikacji są dwa programy: `Odwolania2JSON` otwiera okno (bez konsoli), a `odwolania2json-cli` działa w terminalu z tymi samymi poleceniami co `python -m odwolania2json` (np. `odwolania2json-cli run -i input -o output`).

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

Wersja zgłoszona do oceny działa **bez LLM**: reguły osiągają F1 1.000 na zbiorze UZP, nie potrzebują sieci, GPU ani klucza API i nie generują kosztów. LLM jest **opcjonalny i domyślnie wyłączony**; służy do funkcji dodatkowych (tryb dokładny, streszczenia, asystent RAG). Włącza się go w interfejsie (*Ustawienia*: przełącznik, adres, model, klucz i przycisk „Testuj połączenie”), dla pojedynczego dokumentu przyciskiem *Uzupełnij przez LLM*, w CLI flagą `--llm` albo zmiennymi środowiskowymi (wzór w `.env.example`):

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
| 12 dokumentów spoza puli UZP + 1032 orzeczenia KIO + 5 innych pism | 100% odrzuconych |
| skany UZP (`dane/skany`) i symulowane skany (`tools/simulate_scans.py`) | ok. 0.96–0.98 |

Same modele LLM bez reguł (`tools/eval_llm.py`, 16 spraw): Bielik-4.5B F1 0.78, Qwen3-1.7B 0.64, Qwen3-0.6B 0.53, Bielik-1.5B 0.47, Qwen2.5-1.5B 0.37 (szczegóły i opis wykorzystanego LLM: [docs/llm.md](docs/llm.md)). Dlatego LLM służy tylko do weryfikacji i funkcji dodatkowych, a wynik JSON pochodzi z reguł.

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

## Licencja

Apache License 2.0, pełny tekst w pliku [LICENSE](LICENSE). Wszystkie zależności są open source.
