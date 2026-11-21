# LLM: prototyp na stacjonarce i wersja do oceny

Reguły z YAML działają bez modelu. LLM uzupełnia tylko pola, które reguły zostawiły puste (sekcja `llm.fields` każdego typu). Najczęściej dotyczy to skanów i nietypowych układów.

**Kryterium UZP:** 1–20 pkt za „moc” modelu, przy czym **im mniejszy model, tym więcej punktów**. Dlatego domyślnie używamy małego polskiego modelu **Bielik-4.5B-v3.0-Instruct**. Do porównań nadają się też Bielik-1.5B (jeszcze więcej punktów) i Bielik-11B (dokładniejszy).

## 1. Stacjonarka: Ollama

### Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl edit ollama
```

W edytorze dopisz:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

### Windows

Zainstaluj Ollamę z ollama.com. W *Zmiennych środowiskowych* ustaw `OLLAMA_HOST=0.0.0.0:11434`, a potem uruchom Ollamę ponownie (zamknij ją w zasobniku i otwórz jeszcze raz).

### Modele

```bash
ollama pull hf.co/speakleash/Bielik-4.5B-v3.0-Instruct-GGUF:Q8_0
ollama pull hf.co/speakleash/Bielik-1.5B-v3.0-Instruct-GGUF:Q8_0
ollama list
```

### Dostęp z sieci lokalnej

- Linux (ufw): `sudo ufw allow from 192.168.0.0/16 to any port 11434`
- Windows: reguła przychodząca w Zaporze dla TCP 11434, profil *Prywatny*

Nie wystawiaj portu 11434 do internetu. Ollama nie ma uwierzytelniania.

Adres IP stacjonarki: `ip -4 addr` (Linux) albo `ipconfig` (Windows).

## 2. Laptop: konfiguracja aplikacji

Plik `.env` w katalogu projektu (wzór: `.env.example`):

```bash
O2J_LLM_ENABLED=true
O2J_LLM_URL=http://<IP-stacjonarki>:11434/v1
O2J_LLM_MODEL=hf.co/speakleash/Bielik-4.5B-v3.0-Instruct-GGUF:Q8_0
O2J_LLM_API_KEY=
```

Sprawdzenie połączenia, odpowiedzi w JSON i czasu:

```bash
python -m odwolania2json llm-check
```

Użycie:

```bash
python -m odwolania2json extract plik.pdf --llm --trace       # pola z source: "llm" są oznaczone
python -m odwolania2json run --llm
python -m odwolania2json eval <dane> --llm --errors 30        # porównanie z wynikiem bez LLM
```

W interfejsie webowym status modelu widać w prawym górnym rogu, a pola uzupełnione przez model mają w zakładce *Źródła* źródło `llm`.

## 3. Wersja do oceny: API w UE/EOG

Na komputerze testowym (16 GB RAM, i7, bez GPU) model ma działać przez **API firmy z serwerami w UE/EOG**, z kluczem dostarczonym w rozwiązaniu. Aplikacja używa standardu OpenAI (`/v1/chat/completions`), więc zmieniają się tylko trzy zmienne:

```bash
O2J_LLM_URL=https://<endpoint-dostawcy>/v1
O2J_LLM_MODEL=<nazwa-małego-otwartego-modelu>
O2J_LLM_API_KEY=<klucz>
```

Kandydaci (sprawdź aktualną ofertę modeli i lokalizację serwerów): OVHcloud AI Endpoints (FR), Scaleway Generative APIs (FR), a także własna instancja Ollamy lub vLLM u dostawcy chmury w UE. Wybierz najmniejszy model, który na `eval` daje zysk względem samych reguł.

Klucza nie commituj do publicznego repozytorium. Do zgłoszenia dołącz go jako plik `.env` przekazany organizatorom albo jako klucz z limitem i krótkim terminem ważności, wygenerowany specjalnie na czas testów.

## 4. Wyniki pomiaru (tryb „tylko LLM”)

`tools/eval_llm.py`: reguły tylko klasyfikują dokument, a wszystkie pola z `llm.fields` wypełnia model. 16 spraw (8 treningowych UZP + 8 syntetycznych), 48 dokumentów, RTX 5060 Ti przez Ollamę, kwantyzacja Q8_0 (Qwen2.5 Q4_K_M).

| Model | Licencja | F1 | Precyzja | Czułość | s / dokument |
|---|---|---|---|---|---|
| **Reguły z YAML (bez LLM)** | – | **1.000** | 1.000 | 1.000 | ok. 0,1 |
| Bielik-4.5B-v3.0-Instruct | Apache 2.0 | 0.781 | 0.729 | 0.842 | 5,0 |
| Qwen3-1.7B | Apache 2.0 | 0.642 | 0.595 | 0.696 | 14,3 |
| Qwen3-0.6B | Apache 2.0 | 0.529 | 0.452 | 0.638 | 8,6 |
| Bielik-1.5B-v3.0-Instruct | Apache 2.0 | 0.465 | 0.435 | 0.498 | 1,7 |
| Qwen2.5-1.5B-Instruct | Apache 2.0 | 0.374 | 0.466 | 0.312 | 1,2 |

**Wniosek:** wynik JSON pochodzi z reguł, a LLM jest domyślnie wyłączony. Zgodnie z kryteriami UZP rozwiązanie bez LLM dostaje maksimum punktów za „moc modelu”. W trybie dokładnym LLM jest tylko niezależnym weryfikatorem (rozbieżności trafiają do ręcznej weryfikacji, nie do wyniku), autorem streszczeń i asystentem z cytatami. Do tych zastosowań zalecamy Bielik-4.5B: najlepszy wynik i dobra znajomość polszczyzny przy 4,5 mld parametrów.
