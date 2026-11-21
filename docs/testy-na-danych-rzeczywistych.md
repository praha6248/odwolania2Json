# Testy na prawdziwych dokumentach z internetu

Data przebiegu: 2026-11-21, gałąź `test/real-world-documents`, kod z `main` (56011a5), tryb szybki (bez LLM).

## Podsumowanie

| Miara | Wynik |
|---|---|
| Rozpoznanie typu | **47/47** poprawnie (9 odwołań, 38 dokumentów spoza puli) |
| Ręcznie sprawdzone wartości JSON w odwołaniach | **76/99 (76,8%)** poprawnych |
| API webowe (upload 47 dokumentów + wszystkie endpointy tylko do odczytu) | bez błędów 5xx |
| Tryb wsadowy | każdy PDF dostał plik JSON |

Klasyfikacja jest odporna: wszystkie prawdziwe odwołania zostały rozpoznane, a wyroki i postanowienia KIO, ogłoszenia TED,
wyrok sądu okręgowego, wzór odpowiedzi na odwołanie i poradnik z pustymi wzorami pełnomocnictw dostały `{}`.
**Ekstrakcja pól jest wyraźnie słabsza niż deklarowane F1 = 1.000** na zbiorze UZP: prawdziwe pisma mają inne
sformułowania i układ niż dane treningowe. Poniżej 14 błędów z przyczyną w kodzie lub konfiguracji.

## Zbiór testowy

- **9 prawdziwych odwołań** opublikowanych przez zamawiających (kopie przekazywane wykonawcom, art. 514 Pzp):
  szpitale, gmina, miasto, centrum kultury, spółka samorządowa; lata 2020–2024, kancelarie i pracownicy firm.
- **38 dokumentów podobnych, które nie powinny zostać rozpoznane**: 28 orzeczeń KIO wybranych równomiernie z bazy
  orzeczenia.uzp.gov.pl, 5 innych wyroków i postanowień KIO (w tym postanowienia Prezesa KIO o zwrocie odwołania), 2 ogłoszenia
  TED, wyrok Sądu Okręgowego w Warszawie (skarga na wyrok KIO), wzór odpowiedzi na odwołanie i poradnik z wzorami pełnomocnictw.
- Prawdziwych pełnomocnictw i potwierdzeń przelewu nie udało się znaleźć w publicznym internecie (nie są publikowane),
  więc te dwa typy nie są objęte testem.

Listę adresów i ręcznie sprawdzone wartości zawiera [`tools/real_world_seeds.yaml`](../tools/real_world_seeds.yaml).
Wartości z imieniem i nazwiskiem osoby są zapisane jako skrót SHA-256, a same PDF-y nie trafiają do repozytorium.

## Znalezione błędy

Kolejność: od błędów, które psują najwięcej pól, do drobnych. Przykłady cytują fragment tekstu PDF; dane osób skrócone do inicjałów.

### 1. Lista sekcji w `scope` nie przechodzi do następnej sekcji, gdy w pierwszej nie ma wartości
`Context.scope` ([engine.py:66](../odwolania2json/engine.py)) zwraca **pierwszą istniejącą** sekcję z listy, a nie pierwszą,
w której ekstraktor coś znajdzie. Gdy dokument ma sekcję `first_act_item` bez daty, sekcja `first_act_sentence` z datą nie
jest już sprawdzana; gdy istnieje `dotyczy` bez numeru BZP, nagłówek nie jest przeszukiwany.
- Łapy: `czynnosc_dzien` = null, choć `first_act_sentence` zawiera „Zamawiający w dniu 14 grudnia 2022 r.”.

Poprawka: w ekstraktorach (`regex`, `dated_event`, `keyword_map`) próbować kolejnych sekcji aż do pierwszego trafienia.

### 2. Numery BZP i TED są szukane tylko w nagłówku, który kończy się na „Działając w imieniu”
`numer_bzp` i `numer_ted` mają `scope: [dotyczy, header]` i nie mają wariantu dla całego tekstu (w przeciwieństwie do
`numer_postepowania`). W prawdziwych odwołaniach numer ogłoszenia często stoi w pierwszym akapicie albo w uzasadnieniu.
- Imielin: „Ogłoszenie o zamówieniu zostało zamieszczone w Biuletynie Zamówień Publicznych … pod numerem 2022/BZP 00151734/01” → `numer_bzp` = null.
- Łapy: „ogłoszonym w Dzienniku Urzędowym Unii Europejskiej w dniu 14 września 2022 r. pod nr 2022/S 177-500295” → `numer_ted` = null.

### 3. Drugi wzorzec TED wymaga formy „Dzienniku Urzędowym” tuż przed numerem
[odwolanie.yaml:174](../config/document_types/odwolanie.yaml): `Dzienniku\s+Urzędowym … (?:nr|pod\s+numerem)?(\d{5,7}-\d{4})`.
- Otwock: „w Suplemencie do Dziennika Urzędowego Unii Europejskiej w dniu 24 lipca 2024 roku pod numerem: 444695-2024” →
  `numer_ted` = null (dopełniacz, data w środku, dwukropek po „numerem”).

### 4. Numer postępowania: spacje wokół ukośników i etykieta „znak postępowania”
Wzorzec przechwytuje `[A-Za-z0-9][A-Za-z0-9./\-_]*[A-Za-z0-9]`, więc spacja kończy numer; brak etykiety „znak postępowania”.
- ZWPS Katowice: „Numer sprawy: ZP / D / 8 / 22.” → `numer_postepowania` = **"ZP"**. Taki skrócony numer jest kluczem
  grupowania spraw, więc różne postępowania z numerem „ZP / …” trafiłyby do jednej sprawy.
- Kielce: „(znak postępowania: ZP-KCK/13/2022)” → null.

### 5. Imię pełnomocnika w dopełniaczu lub bierniku
Po „reprezentowany przez” imię i nazwisko stoi w bierniku, a `nominative()` działa tylko po tytule z listy `OBLIQUE_TITLE`
([extractors.py:267](../odwolania2json/extractors.py)), który nie obejmuje skrótu „r.pr.” ani braku tytułu.
- ZWPS: „reprezentowany przez: Roberta K.” → "Roberta K…" zamiast "Robert K…".
- Łapy: „reprezentowany przez r.pr. Rafała Z.” → "Rafała Z…".
- Sośnicowice: „r.pr. Annę S.” → "Annę S…".

Poprawka: po „przez” zawsze sprowadzać imię do mianownika (Morfeusz już jest zależnością).

### 6. Pełnomocnik-pracownik: „reprezentowana przez pracownika – Imię Nazwisko”
Wzorzec `reprezentowan\w*\s+przez\s*:?\s*(tytuł)?(Imię Nazwisko)` ([extractors.py:265](../odwolania2json/extractors.py))
nie dopuszcza słowa „pracownika” ani myślnika. Wynik jest wewnętrznie sprzeczny: `przez-pelnomocnika: 1`, a `imie_nazwisko`, `nazwa`, `mail` = null.
- Otwock i Kolno (dwa odwołania tej samej grupy firm).

### 7. Adres doklejony do nazwy odwołującego i kancelarii
`ADDRESS_STOP` ([extractors.py:27](../odwolania2json/extractors.py)) nie zatrzymuje się na kodzie pocztowym na początku
nowej linii ani na „ul .” ze spacją; wzorzec kancelarii po „adres do korespondencji” nie zatrzymuje się na nowej linii z „ul.”.
- ZWPS: `nazwa` = "MAR-FOUR MARIAN SIEKIERSKI 95-050 Konstantynów Łódzki, ul . Srebrzyńska 5/7".
- Sośnicowice: `pelnomocnik.nazwa` = "Dentons Europe Dąbrowski i Wspólnicy sp. k. ul. Zajęcza 4".

### 8. Konsorcjum numerowane „1.”, „2.” zamiast „1)”, „2)”
`split_members` ([extractors.py:292](../odwolania2json/extractors.py)) rozpoznaje tylko numerację z nawiasem.
- Kolno: `nazwa` = "1. CATERMED Spółka Akcyjna" (numer w nazwie; drugi członek konsorcjum nierozpoznany).

### 9. Powód czynności: typowe sformułowania nie pasują do słów kluczowych
[odwolanie.yaml:107–116](../config/document_types/odwolanie.yaml):
- Imielin: „zaniechanie czynności odrzucenia oferty” — wzorzec `zaniecha\w*\s+odrzucenia` nie dopuszcza słowa „czynności” → null (powinno być 7).
- Kielce: „składamy odwołanie wobec treści ogłoszenia o zamówieniu oraz postanowień specyfikacji istotnych warunków zamówienia”
  — sekcja `appeal_against` zaczyna się tylko od „wnoszę|składam|wnosi” (brak liczby mnogiej „składamy/wnosimy”), a wzorzec
  `Specyfikacj\w*\s+Warunków` nie dopuszcza „istotnych” (SIWZ) → null (powinno być 4).
- Otwock: „zaniechanie zastrzeżenia w załączniku nr 5 do Specyfikacji Warunków Zamówienia (dalej jako SWZ) - projekcie umowy”
  → 4 zamiast 12: słowo „Specyfikacji Warunków” (priorytet 1) wygrywa z „projekcie umowy” (też priorytet 1), bo stoi wcześniej.

### 10. Data czynności: typowe zwroty o dniu przekazania informacji nie są obsługiwane
- Imielin: „Zamawiający przekazał Odwołującemu informacje stanowiącą podstawę do wniesienia odwołania w dniu 1 czerwca 2022 r.” —
  `first_act_sentence` dopuszcza najwyżej 6 słów między „Zamawiający” a „w dniu”.
- Kętrzyn: „Wiadomość o okolicznościach stanowiących podstawę do wniesienia odwołania Odwołujący powziął w dniu 27.05.2022 r.”
- Łapy: zob. błąd 1.

Bez daty czynności kontrola formalna terminu z art. 515 Pzp jest pomijana (`termin: skip`) w 5 z 7 spraw z numerem postępowania;
dwa pozostałe odwołania nie mają numeru i nie dostają kontroli wcale (błąd 14).

### 11. Data w formacie ISO w linii „miejscowość, data”
Wzorce `data` i `miejscowosc` ([odwolanie.yaml:69](../config/document_types/odwolanie.yaml)) obsługują `dd.mm.rrrr`
i „d miesiąca rrrr”, ale nie `rrrr-mm-dd`.
- Kamsoft: „Katowice, dnia 2020-09-17” → `data` = null, `miejscowosc` = null.

### 12. Tytuł zamówienia z innego miejsca dokumentu
Drugi wzorzec `tytul` szuka „pn. „…”” w całym tekście i bierze pierwsze trafienie; „pn.” bez cudzysłowu i „pt.” nie są obsługiwane.
- Kamsoft: w sekcji „Dotyczy” jest „pn. Dostawa, instalacja i wdrożenie Lokalnego Oprogramowania Komunikacyjnego … - ETAP I”
  (bez cudzysłowu), więc wzięty został cytat z 13 370. znaku: nazwa **projektu unijnego** „Wyposażenie środowisk informatycznych …”.
  To wartość błędna, a nie pusta, więc w ocenie UZP liczy się podwójnie (FP i FN).
- ZWPS: „pt. Zakup 3 mikrotomów saneczkowych …” → null.

### 13. Wielu zamawiających (zamówienie wspólne)
Kamsoft: 15 zamawiających w kolejnych liniach bloku „Zamawiający:”, w JSON jest tylko pierwszy („Województwo Wielkopolskie”).

### 14. Sprawy: odwołanie bez numeru postępowania nie dostaje kontroli formalnej
`group_cases` ([cases.py](../odwolania2json/cases.py)) odkłada dokumenty bez `numer_postepowania` do grupy „bez numeru”,
bez listy brakujących dokumentów i bez kontroli formalnej. Otwock nie ma numeru referencyjnego (tylko numer TED), więc nigdy
nie połączy się z pełnomocnictwem i przelewem. Można grupować zapasowo po numerze BZP/TED albo po nazwie odwołującego.

### Do decyzji (nie oznaczone jako błąd)
- Oficjalny formularz UZP ma pole „Przedstawiciel (imię i nazwisko)” / „Imię i nazwisko przedstawiciela Odwołującego”
  (Kielce, Kętrzyn). Aplikacja ustawia wtedy `przez-pelnomocnika: 0` i gubi nazwisko. Warto ustalić, czy to pełnomocnik w rozumieniu schematu.
- Pierwsze OCR strony przez RapidOCR trwało ok. 25 s (jedna zeskanowana strona w ZWPS); kolejne przebiegi korzystają z cache (2 s).

## Co działa dobrze

- Klasyfikacja: 0 fałszywych trafień na 38 podobnych dokumentach i 0 pominiętych odwołań, także przy innym układzie nagłówka
  (Zamawiający przed Odwołującym, „Do:”, „O D W O Ł A N I E” rozstrzelone, numer strony nad datą).
- Identyfikatory KRS i NIP: wszystkie 15 sprawdzonych wartości poprawne.
- API: upload, lista, szczegóły, JSON, podgląd stron, lokalizacja każdego pola w PDF, anonimizacja, sprawy, eksport XLSX/CSV
  i wyszukiwarka działają na wszystkich dokumentach; anonimizacja dokumentu z OCR zgodnie z założeniem zwraca 400.

## Jak powtórzyć

```bash
python -I tools/real_world_test.py fetch    # pobiera dokumenty do data_real/real_world/ (robots.txt, 2 s odstępu)
python -I tools/real_world_test.py run      # pipeline + API + tryb wsadowy, raport w data_real/real_world/report.md
```

Sześć adresów z listy i 2 identyfikatory z próbki KIO były niedostępne w dniu testu (404, błąd certyfikatu, strona HTML
zamiast PDF); skrypt je pomija.
