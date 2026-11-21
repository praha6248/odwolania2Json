"""Phrasing and layouts found in real appeals published by contracting authorities (docs/testy-na-danych-rzeczywistych.md).

The texts are fictional, but each reproduces a construction that the rules missed on a real document.
"""

from pathlib import Path

import pytest

from odwolania2json.config import load_settings
from odwolania2json.extractors import governed_nominative
from odwolania2json.pipeline import Processor


@pytest.fixture(scope="module")
def processor():
    """Processor without OCR and LLM."""
    settings = load_settings()
    settings.ocr["enabled"] = False
    return Processor(settings, use_llm=False)


def appeal(processor, text):
    """Extract the appeal JSON from a text."""
    result = processor.process_text(text, Path("odwolanie.pdf"), forced_type="odwolanie")
    return result.data


SOLE_TRADER = """Kraków, dnia 2024-03-18

Prezes Krajowej Izby Odwoławczej
ul. Postępu 17A, 02-676 Warszawa

Odwołujący:
ALFA-BUD JAN TESTOWY
30-001 Kraków, ul . Długa 5/7
reprezentowany przez:
r.pr. Roberta Nowaka
adres do korespondencji:
Kancelaria Radcy Prawnego Beta sp. k.
ul. Krótka 4, 00-351 Warszawa
e-mail: biuro@beta.example

Zamawiający:
Gmina Przykładowo
ul. Rynek 1, 44-100 Przykładowo

ODWOŁANIE
w postępowaniu pt. Budowa drogi gminnej w miejscowości Przykładowo. Numer sprawy: ZP / D / 8 / 24.

1. Działając w imieniu Odwołującego wnoszę odwołanie na niezgodną z przepisami ustawy czynność zamawiającego.
2. Ogłoszenie o zamówieniu zostało zamieszczone w Biuletynie Zamówień Publicznych w dniu 10 lutego 2024 r. pod numerem 2024/BZP 00151734/01.
3. Czynności lub zaniechania czynności Zamawiającego, którym Odwołujący zarzuca niezgodność z przepisami ustawy, to zaniechanie czynności odrzucenia oferty wykonawcy Gamma.
4. Zamawiający przekazał Odwołującemu informację stanowiącą podstawę do wniesienia odwołania
w dniu 13 marca 2024 r. przy użyciu środków komunikacji elektronicznej.
"""


def test_sole_trader_appeal(processor):
    """ISO date line, address after the name, accusative attorney, spaced reference, BZP in the body, art. 516 formula."""
    data = appeal(processor, SOLE_TRADER)
    head, party, order = data["OdwolanieKIO"], data["Odwolujacy"][0], data["ZamowieniePubliczne"]
    assert (head["data"], head["miejscowosc"]) == ("2024-03-18", "Kraków")
    assert party["nazwa"] == "ALFA-BUD JAN TESTOWY"
    assert party["pelnomocnik"]["imie_nazwisko"] == "Robert Nowak"
    assert party["pelnomocnik"]["nazwa"] == "Kancelaria Radcy Prawnego Beta sp. k."
    assert order["numer_postepowania"] == "ZP/D/8/24"
    assert order["numer_bzp"] == "2024/BZP00151734/01"
    assert order["tytul"] == "Budowa drogi gminnej w miejscowości Przykładowo"
    assert head["czynnosc_powod_id"] == 7
    assert head["czynnosc_dzien"] == "2024-03-13"


CONSORTIUM = """Łódź, dnia 5 sierpnia 2024 roku

Do: Prezes Krajowej Izby Odwoławczej

Zamawiający:
Powiat Przykładowy, 00-001 Przykładowo, ul. Główna 1
Szpital Powiatowy w Przykładowie, 00-002 Przykładowo, ul. Szpitalna 2
Zakład Opieki Zdrowotnej w Testowie
00-003 Testowo, ul. Leśna 3

Odwołujący: 1. DELTA Catering Spółka Akcyjna
z siedzibą w Łodzi
ul. Traktorowa 1, 91-204 Łódź
KRS: 0000123456
2. Epsilon spółka z ograniczoną odpowiedzialnością
ul. Banacha 1, 02-097 Warszawa
reprezentowana przez pracownika – Kamila Nowak

Dotyczy: postępowania prowadzonego w trybie przetargu nieograniczonego pn. Świadczenie usług żywienia pacjentów
(znak sprawy: SZP/2/2024), ogłoszonego w Suplemencie do Dziennika Urzędowego Unii Europejskiej w dniu 24 lipca 2024
roku pod numerem: 444695-2024.

ODWOŁANIE

Działając w imieniu Odwołujących wnoszę odwołanie na zaniechanie przez zamawiającego czynności tj.:
1. zaniechanie zastrzeżenia w załączniku nr 5 do Specyfikacji Warunków Zamówienia (dalej SWZ) - projekcie umowy - zasad zmiany wynagrodzenia.

II. zarzucam Zamawiającemu naruszenie art. 436 Pzp.
"""


def test_consortium_with_employee_and_joint_authorities(processor):
    """'1.' numbering, employee representative, authorities one per line, unquoted title, TED in genitive, contract terms."""
    data = appeal(processor, CONSORTIUM)
    party, order = data["Odwolujacy"][0], data["ZamowieniePubliczne"]
    assert [a["nazwa"] for a in data["Zamawiajacy"]] == ["Powiat Przykładowy", "Szpital Powiatowy w Przykładowie", "Zakład Opieki Zdrowotnej w Testowie"]
    assert (party["nazwa"], party["krs"]) == ("DELTA Catering Spółka Akcyjna", "0000123456")
    assert party["przez-pelnomocnika"] == 1
    assert party["pelnomocnik"]["imie_nazwisko"] == "Kamila Nowak"
    assert order["tytul"] == "Świadczenie usług żywienia pacjentów"
    assert order["numer_postepowania"] == "SZP/2/2024"
    assert order["numer_ted"] == "444695-2024"
    assert data["OdwolanieKIO"]["czynnosc_powod_id"] == 12


CONTRACT_TERMS = """Wrocław, dnia 16.03.2022 r.

Prezes Krajowej Izby Odwoławczej

Odwołujący:
Omega S.A.
ul. Prosta 1, 50-001 Wrocław

Zamawiający:
Centrum Kultury w Przykładowie
ul. Teatralna 2, 25-001 Przykładowo

Dotyczy: postępowania prowadzonego w trybie przetargu nieograniczonego pn. Ochrona fizyczna osób i mienia (znak postępowania: ZP-CK/13/2022), ogłoszonego w Biuletynie Zamówień Publicznych.

ODWOŁANIE

Działając na podstawie art. 513 ustawy Pzp, składamy odwołanie wobec treści ogłoszenia o zamówieniu oraz postanowień specyfikacji istotnych warunków zamówienia.

Zamówienie jest realizowane w ramach projektu pn.: „Modernizacja infrastruktury kultury w regionie”.
"""


def test_plural_appeal_against_siwz(processor):
    """'składamy odwołanie' against SIWZ, 'znak postępowania', and the project name later in the text is not the title."""
    data = appeal(processor, CONTRACT_TERMS)
    order = data["ZamowieniePubliczne"]
    assert order["tytul"] == "Ochrona fizyczna osób i mienia"
    assert order["numer_postepowania"] == "ZP-CK/13/2022"
    assert data["OdwolanieKIO"]["czynnosc_powod_id"] == 4


REJECTION = """Warszawa, dnia 27 grudnia 2022 r.

Prezes Krajowej Izby Odwoławczej

Zamawiający:
Szpital Miejski w Testowie
ul. Zdrowa 1, 18-100 Testowo

Odwołujący:
Sigma Diagnostics sp. z o.o.
ul. Polna 8, 00-728 Warszawa
NIP: 5272322068, KRS: 0000132695

O D W O Ł A N I E
Działając w imieniu Odwołującego wnoszę odwołanie wobec czynności Zamawiającego w postępowaniu pn. „Dostawa analizatora”, ogłoszonym w Dzienniku Urzędowym Unii Europejskiej w dniu 14 września 2022 r. pod nr 2022/S 177-500295.
Odwołujący podnosi niezgodność z ustawą czynności Zamawiającego polegających na:
1) odrzuceniu oferty Odwołującego w Pakiecie nr 1,
2) unieważnieniu postępowania w zakresie Pakietu nr 1.

UZASADNIENIE
Zamawiający w dniu 14 grudnia 2022 r. poinformował Odwołującego o odrzuceniu jego oferty.
"""


def test_next_section_is_tried_when_the_first_has_no_value(processor):
    """The act item has no date, so the date comes from the next listed section; TED number in the body is found."""
    data = appeal(processor, REJECTION)
    assert data["OdwolanieKIO"]["czynnosc_powod_id"] == 1
    assert data["OdwolanieKIO"]["czynnosc_dzien"] == "2022-12-14"
    assert data["ZamowieniePubliczne"]["numer_ted"] == "500295-2022"


@pytest.mark.parametrize(
    ("written", "expected"),
    [("Roberta Nowaka", "Robert Nowak"), ("Annę Kowalską", "Anna Kowalska"), ("Kamila Nowak", "Kamila Nowak"), ("Jan Nowak", "Jan Nowak")],
)
def test_name_after_przez_becomes_nominative_only_when_certain(written, expected):
    """A name governed by 'przez' is converted, but a nominative female name like 'Kamila' is not turned into 'Kamil'."""
    assert governed_nominative(written) == expected


@pytest.mark.parametrize("label", ["Pełnomocnik:", "reprezentowany przez pełnomocnika:", "reprezentowany ... przez:"])
def test_representative_labels_with_postcode_on_next_line(processor, label):
    text = SOLE_TRADER.replace("reprezentowany przez:\nr.pr. Roberta Nowaka", label + "\nr.pr. Jan Nowak")
    party = appeal(processor, text)["Odwolujacy"][0]
    assert party["pelnomocnik"]["imie_nazwisko"] == "Jan Nowak"
    assert "30-001" not in party["nazwa"]
