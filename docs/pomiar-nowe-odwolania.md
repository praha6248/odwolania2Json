# Pomiar na nowych odwołaniach – 21 listopada 2026

Wersja v0.1.5, commit a3a32e1. Z 34 ręcznie opisanych wartości aplikacja zwróciła 20 poprawnych, 6 pustych i 8 błędnie wypełnionych.

| Dokument źródłowy | Strona wzorca | Wejście | Rozpoznany typ | Poprawne | Puste | Błędne |
|---|---:|---|---|---:|---:|---:|
| [ERP, Wrocław 2026](https://bip.cui.wroclaw.pl/attachments/8218/download) | 1 | tekst | odwolanie | 9 | 0 | 0 |
| [Inżynier kontraktu, Ząbkowice 2024](https://bip.zabkowiceslaskie.pl/attachments/download/18442) | 1 | tekst | odwolanie | 5 | 1 | 1 |
| [Odbiór odpadów, Ząbkowice 2020](https://bip.zabkowiceslaskie.pl/attachments/download/10907) | 1 | skan | odwolanie | 4 | 3 | 1 |
| [Boisko, Ząbkowice 2022](https://bip.zabkowiceslaskie.pl/attachments/download/14130) | 3 | skan | odwolanie | 2 | 0 | 4 |
| [System informacji przestrzennej, Wrocław 2024](https://bip.cui.wroclaw.pl/attachments/4236/download) | 1 | skan | odwolanie | 0 | 2 | 2 |

## Metoda i zakres

Pliki pobrano z dwóch BIP-ów. Porównano SHA-256 z 1553 wcześniej dostępnymi plikami w data_real, data_train, data_synth, tests i input (tam, gdzie katalog istniał), z wyłączeniem nowej partii. Brak identycznych plików. Kontrola nie wyklucza innej kopii tego samego pisma ani wcześniejszej znajomości poza repozytorium.

Wartości odniesienia zapisano przed uruchomieniem ekstrakcji dla danego pisma. Pola pochodzą z pierwszej strony odwołania, w pakiecie z boiska ze strony 3. Skany sprawdzono na renderach. Użyto Processor(use_llm=False).process_pdf na pełnych plikach z domyślną klasyfikacją, limitem OCR 4 stron i dostępnym RapidOCR. Nie wymuszano typu, nie poprawiano reguł ani wyników. Nazwy plików testowych były neutralne.

Porównanie ignoruje wielkość liter i wielokrotne białe znaki. Daty i identyfikatory we wzorcu zapisano w formacie schematu. Literówki i błędne znaki diakrytyczne liczą się jako błędne. Brak wartości lub całego wyniku liczy się jako puste. Oceniono wyłącznie pola, dla których zapisano wartość obecną w źródle. Pomiar nie obejmuje wartości dopisanych w polach, które powinny pozostać puste, ani wszystkich pól schematu. Próba celowa, jeden oceniający, pięć spraw; trzy pochodzą od jednego zamawiającego.

## Audyt poszczególnych pól

W lokalnych wynikach zapisano oczekiwaną i zwróconą wartość każdego pola. Poniżej nazwy pól ocenionych w każdej kategorii.

| Sprawa | Poprawne | Puste | Błędne | SHA-256 pliku |
|---|---|---|---|---|
| ERP, Wrocław 2026 | date, city, party, buyer, ref, ted, nip, krs, regon | — | — | 33fc03d23c1c9d3a1c830f22b54e13e092f4dfed8217252fe4aa3f2618b352a0 |
| Inżynier kontraktu, Ząbkowice 2024 | date, city, party, ted, krs | ref | buyer | b92c4e70c7ffb2b59fa872cd6004299bad92dcff03bbd0bd7bfbd7649f4611b6 |
| Odbiór odpadów, Ząbkowice 2020 | date, city, party, ted | nip, krs, regon | buyer | 47d9e867a353db251b73084cbf5de7339d79c642b4a4fef70c58c6905fec6134 |
| Boisko, Ząbkowice 2022 | ref, nip | — | date, city, party, buyer | 703ab2c02f3adf2b123882848b7de801449c599c3cda0bae9580cd1fc3c4fc82 |
| System informacji przestrzennej, Wrocław 2024 | — | date, city | party, buyer | 55be1ef3059ee9f808920a5eb4341894696c35c4b4e2865f14652cf01a60370d |

Skróty: date i city oznaczają datę i miejscowość odwołania, party i buyer – nazwy pierwszego odwołującego i zamawiającego, ref i ted – numery postępowania i ogłoszenia TED. NIP, KRS i REGON dotyczą pierwszego odwołującego.

## Powtórzenie pomiaru po poprawkach

Na tych samych plikach i przy tych samych wzorcach poprawione reguły zwróciły 34/34 sprawdzonych wartości, w tym 18/18 na trzech skanach. Liczba pustych pól spadła z 6 do 0, błędnie wypełnionych z 8 do 0. Nazwy obu stron sprawdzono również z uwzględnieniem wielkości liter. Ta próba służyła do diagnozy błędów, więc po zmianach mierzy regresję na znanych sprawach. Nie dostarcza niezależnego oszacowania trafności na kolejnych odwołaniach. Rachunki bankowe są osobno objęte testami przelewów, poza tymi 34 wartościami.
