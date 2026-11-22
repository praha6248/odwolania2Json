# Odwołania2JSON — uruchomienie oceny

Komenda (z katalogu `/opt/solution`):

```bash
sudo bash run.sh
```

- Przetwarza wszystkie pliki PDF z `/opt/solution/input` (także w podfolderach) i zapisuje do `/opt/solution/output` pliki JSON o tych samych nazwach, z zachowaniem struktury folderów (`input/sprawa1/odwolanie.pdf` → `output/sprawa1/odwolanie.json`).
- Dokument spoza wymaganych typów oraz plik, którego nie da się odczytać, dostaje plik zawierający `{}`.
- Nie wymaga interakcji, kończy się sama po przetworzeniu wszystkich plików.
- Nie korzysta z sieci, GPU, Dockera ani zewnętrznych API; nie potrzebuje kluczy ani pliku `.env`. Model językowy jest wyłączony (wynik pochodzi z reguł), OCR skanów działa lokalnie na CPU (RapidOCR, modele pobrane wcześniej do `repo/.venv`).
- Kod: `/opt/solution/repo` (https://github.com/praha6248/odwolania2Json), środowisko: Python 3.13 w `/opt/solution/repo/.venv`.
- Czas: PDF z warstwą tekstową to ułamki sekundy, skan kilka do kilkunastu sekund na stronę na 2 vCPU (226 PDF-ów ze zbioru UZP w 7 min 26 s). Każdy plik JSON jest zapisywany od razu po przetworzeniu PDF-a. Zabezpieczenie limitu 45 minut: pliki rozpoczęte po 40. minucie są czytane tylko z warstwy tekstowej, bez OCR.
