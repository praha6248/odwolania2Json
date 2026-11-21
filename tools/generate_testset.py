"""Generate a synthetic, labelled test set of KIO appeal cases full of edge cases.

Each case folder holds odwolanie.pdf, pelnomocnictwo.pdf and potwierdzenie_przelewu.pdf (text layer) together with the
expected odwolanie.json, pelnomocnictwo.json and przelew.json, so it can be scored with:

    python -m odwolania2json eval data_synth/cases

A sibling folder data_synth/negatives holds look-alike documents that must not be classified.

Usage: python tools/generate_testset.py [--cases 120] [--seed 2026] [--out data_synth]

The phrasing is written independently of the extraction rules (layouts and wording seen in public appeals and in the
UZP training data) so that the score measures generalization, not memorization.
"""

from __future__ import annotations

import argparse
import json
import random
import textwrap
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("C:/Windows/Fonts"), Path("/Library/Fonts")]
MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września", "października", "listopada", "grudnia"]
FIRST_M = ["Piotr", "Tomasz", "Paweł", "Michał", "Łukasz", "Krzysztof", "Andrzej", "Grzegorz", "Jakub", "Sławomir", "Bartosz", "Wojciech", "Maciej", "Zbigniew", "Jerzy"]
FIRST_F = ["Anna", "Katarzyna", "Małgorzata", "Agnieszka", "Joanna", "Ewa", "Magdalena", "Żaneta", "Aleksandra", "Natalia", "Beata", "Dorota", "Urszula", "Halina", "Olga"]
LAST_M = ["Nowak", "Kowalski", "Wiśniewski", "Wójcik", "Kamiński", "Lewandowski", "Zieliński", "Szymański", "Woźniak", "Dąbrowski", "Kozłowski", "Jankowski", "Mazur-Kwiatkowski", "Łęcki", "Bąk"]
LAST_F = ["Nowak", "Kowalska", "Wiśniewska", "Wójcik", "Kamińska", "Lewandowska", "Zielińska", "Szymańska", "Woźniak", "Dąbrowska", "Kozłowska", "Jankowska", "Mazur-Kwiatkowska", "Łęcka", "Bąk"]
STEMS = ["Arvento", "Bialtech", "Corvix", "Delmara", "Elkopol", "Fenwar", "Gryfmed", "Hydrobud", "Instalex", "Jurmet", "Kalvia", "Lumaris", "Mostrol", "Novatrans", "Orbitex", "Pomtel", "Quanta", "Rexbud", "Silvanet", "Termoplus", "Ultrax", "Vistula", "Wodmar", "Zenbet"]
TRADES = ["Budownictwo", "Serwis", "Technologie", "Instalacje", "Medical", "Logistyka", "Energia", "Systemy", "Infrastruktura", "Dystrybucja"]
FORMS = ["sp. z o.o.", "S.A.", "sp. j.", "sp. k.", "Spółka z ograniczoną odpowiedzialnością", "sp. z o.o. sp.k."]
AUTHORITIES = ["Gmina {c}", "Powiat {c}ski", "Szpital Wojewódzki w {c}", "Zarząd Dróg Miejskich w {c}", "Uniwersytet {c}ski", "Wodociągi Miejskie w {c} sp. z o.o.", "Miejski Ośrodek Sportu i Rekreacji w {c}", "Regionalny Zarząd Gospodarki Wodnej w {c}"]
CITIES = [("Warszawa", "00-950"), ("Kraków", "31-004"), ("Łódź", "90-001"), ("Wrocław", "50-001"), ("Poznań", "61-001"), ("Gdańsk", "80-001"), ("Szczecin", "70-001"), ("Lublin", "20-001"), ("Białystok", "15-001"), ("Rzeszów", "35-001"), ("Toruń", "87-100"), ("Kielce", "25-001"), ("Opole", "45-001"), ("Zielona Góra", "65-001"), ("Bielsko-Biała", "43-300"), ("Nowy Sącz", "33-300")]
CITY_ADJ = {"Warszawa": "Warszaw", "Kraków": "Krakow", "Łódź": "Łódz", "Wrocław": "Wrocław", "Poznań": "Poznań", "Gdańsk": "Gdań", "Szczecin": "Szczeciń", "Lublin": "Lubel", "Białystok": "Białostock", "Rzeszów": "Rzeszow", "Toruń": "Toruń", "Kielce": "Kieleck", "Opole": "Opol", "Zielona Góra": "Zielonogór", "Bielsko-Biała": "Bielsk", "Nowy Sącz": "Nowosądeck"}
CITY_LOC = {"Warszawa": "Warszawie", "Kraków": "Krakowie", "Łódź": "Łodzi", "Wrocław": "Wrocławiu", "Poznań": "Poznaniu", "Gdańsk": "Gdańsku", "Szczecin": "Szczecinie", "Lublin": "Lublinie", "Białystok": "Białymstoku", "Rzeszów": "Rzeszowie", "Toruń": "Toruniu", "Kielce": "Kielcach", "Opole": "Opolu", "Zielona Góra": "Zielonej Górze", "Bielsko-Biała": "Bielsku-Białej", "Nowy Sącz": "Nowym Sączu"}
STREETS = ["ul. Długa", "ul. Kwiatowa", "al. Jana Pawła II", "ul. Polna", "pl. Wolności", "ul. Przemysłowa", "ul. Ogrodowa", "ul. Słoneczna"]
TITLES = [
    "Budowa sali gimnastycznej wraz z infrastrukturą towarzyszącą",
    "Dostawa sprzętu komputerowego i oprogramowania dla jednostek oświatowych",
    "Kompleksowe utrzymanie czystości w obiektach Zamawiającego w latach 2027–2029",
    "Przebudowa drogi powiatowej nr 1234K na odcinku Nowa Wieś – Stara Wieś",
    "Dostawa produktów leczniczych w podziale na 14 pakietów",
    "Świadczenie usług odbioru i zagospodarowania odpadów komunalnych",
    "Termomodernizacja budynków użyteczności publicznej wraz z instalacją pomp ciepła",
    "Pełnienie funkcji inżyniera kontraktu dla zadania „Rozbudowa oczyszczalni ścieków”",
]
REASONS = {
    1: ("Decyzja o odrzuceniu oferty", ["poinformował o odrzuceniu oferty złożonej przez Odwołującego", "odrzucił ofertę Odwołującego"], ["odrzuceniu oferty Odwołującego na podstawie art. 226 ust. 1 pkt 5 Pzp"]),
    2: ("Ogłoszenie wyboru oferty", ["dokonał wyboru oferty najkorzystniejszej", "ogłosił wybór oferty wykonawcy {w}"], ["wyborze jako najkorzystniejszej oferty wykonawcy {w}"]),
    3: ("Decyzja o wykluczeniu wykonawcy", ["wykluczył Odwołującego z postępowania", "poinformował o wykluczeniu Odwołującego z postępowania"], ["wykluczeniu Odwołującego z postępowania na podstawie art. 109 ust. 1 pkt 7 Pzp"]),
    4: ("Publikacja specyfikacji warunków zamówienia (SWZ)", ["opublikował Specyfikację Warunków Zamówienia", "udostępnił na stronie internetowej Specyfikację Warunków Zamówienia"], ["ustaleniu treści Specyfikacji Warunków Zamówienia w zakresie warunków udziału"]),
    5: ("Modyfikacja treści SWZ", ["zmodyfikował treść Specyfikacji Warunków Zamówienia", "dokonał modyfikacji treści SWZ"], ["modyfikacji treści SWZ bez przedłużenia terminu składania ofert"]),
    6: ("Odpowiedzi i wyjaśnienia do SWZ", ["udzielił odpowiedzi na pytania wykonawców do treści SWZ", "przekazał wykonawcom odpowiedzi i wyjaśnienia do treści Specyfikacji Warunków Zamówienia"], ["udzieleniu odpowiedzi na pytania wykonawców w sposób zmieniający treść SWZ"]),
    7: ("Zaniechanie odrzucenia oferty", ["nie odrzucił oferty wykonawcy {w}", "zaniechał odrzucenia oferty wykonawcy {w}"], ["zaniechaniu odrzucenia oferty wykonawcy {w} jako niezgodnej z warunkami zamówienia"]),
    8: ("Zaniechanie wykluczenia wykonawcy", ["nie wykluczył z postępowania wykonawcy {w}", "zaniechał wykluczenia wykonawcy {w}"], ["zaniechaniu wykluczenia z postępowania wykonawcy {w}"]),
    9: ("Decyzja o unieważnieniu postępowania", ["unieważnił postępowanie", "poinformował o unieważnieniu postępowania"], ["unieważnieniu postępowania na podstawie art. 255 pkt 6 Pzp"]),
    10: ("Zaniechanie unieważnienia postępowania", ["zaniechał unieważnienia postępowania", "nie unieważnił postępowania mimo wady"], ["zaniechaniu unieważnienia postępowania obarczonego wadą niemożliwą do usunięcia"]),
    12: ("Projektowane postanowienia umowy", ["opublikował projektowane postanowienia umowy", "udostępnił wzór umowy stanowiący załącznik do SWZ"], ["ustaleniu projektowanych postanowień umowy w zakresie kar umownych", "określeniu istotnych postanowień umowy w sposób rażąco niekorzystny"]),
    11: ("Opis przedmiotu zamówienia (OPZ)", ["udostępnił Opis Przedmiotu Zamówienia", "opublikował Opis Przedmiotu Zamówienia"], ["opisaniu przedmiotu zamówienia w sposób utrudniający uczciwą konkurencję"]),
}
FILLER = (
    "Zamawiający, działając w sposób sprzeczny z zasadą uczciwej konkurencji i równego traktowania wykonawców, "
    "dopuścił się naruszenia przepisów ustawy, co miało istotny wpływ na wynik postępowania. Odwołujący ma interes "
    "w uzyskaniu zamówienia i może ponieść szkodę w wyniku naruszenia przez Zamawiającego przepisów ustawy. "
)


def register_font() -> tuple[str, str]:
    """Register a TrueType font with Polish glyphs and return (regular, bold) names."""
    for folder in FONT_DIRS:
        regular, bold = folder / "DejaVuSans.ttf", folder / "DejaVuSans-Bold.ttf"
        if regular.exists():
            pdfmetrics.registerFont(TTFont("Body", str(regular)))
            pdfmetrics.registerFont(TTFont("BodyBold", str(bold if bold.exists() else regular)))
            return "Body", "BodyBold"
    raise SystemExit("DejaVuSans.ttf not found; install fonts-dejavu")


def write_pdf(path: Path, lines: list[str], fonts: tuple[str, str], footer: bool = False) -> None:
    """Render lines (wrapped, '#' prefix = bold, '>' prefix = right aligned) to a multi-page A4 PDF."""
    regular, bold = fonts
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    pages: list[list[tuple[str, str]]] = [[]]
    for raw in lines:
        style = "b" if raw.startswith("#") else "r" if raw.startswith(">") else "n"
        text = raw.lstrip("#>") if style != "n" else raw
        for piece in textwrap.wrap(text, 92) or [""]:
            if len(pages[-1]) >= 52:
                pages.append([])
            pages[-1].append((style, piece))
    for number, page in enumerate(pages, 1):
        y = height - 56
        for style, text in page:
            pdf.setFont(bold if style == "b" else regular, 10)
            if style == "r":
                pdf.drawRightString(width - 56, y, text)
            else:
                pdf.drawString(56, y, text)
            y -= 14
        if footer:
            pdf.setFont(regular, 8)
            pdf.drawCentredString(width / 2, 30, f"Strona {number} z {len(pages)}")
        pdf.showPage()
    pdf.save()


@dataclass
class Entity:
    """A company or institution with identifiers."""

    name: str
    city: str
    postal: str
    street: str
    krs: str | None
    nip: str
    regon: str
    email: str


@dataclass
class Person:
    """A natural person."""

    first: str
    last: str
    female: bool

    @property
    def full(self) -> str:
        """Name in nominative."""
        return f"{self.first} {self.last}"


@dataclass
class Case:
    """All facts of one synthetic case; documents and expected JSON are rendered from it."""

    rng: random.Random
    appellants: list[Entity] = field(default_factory=list)
    sole_trader: Person | None = None
    authorities: list[Entity] = field(default_factory=list)
    attorneys: list[Person] = field(default_factory=list)
    attorney_pesel: dict[int, str] = field(default_factory=dict)
    law_firm: str | None = None
    firm_email: str | None = None
    signers: list[list[Person]] = field(default_factory=list)
    title: str = ""
    reference: str = ""
    bzp: str | None = None
    ted: tuple[str, str] | None = None
    place: str | None = None
    doc_date: date | None = None
    act_date: date = date(2026, 1, 1)
    reason: int = 1
    winner: str = ""
    amount: float = 0.0
    from_account: str = ""
    to_account: str = ""
    transfer_date: date = date(2026, 1, 1)
    transaction: str | None = None
    transfer_title: str = ""


def digits(rng: random.Random, n: int) -> str:
    """Random digit string."""
    return "".join(rng.choice("0123456789") for _ in range(n))


def person(rng: random.Random) -> Person:
    """Random person."""
    female = rng.random() < 0.5
    return Person(rng.choice(FIRST_F if female else FIRST_M), rng.choice(LAST_F if female else LAST_M), female)


def company(rng: random.Random, with_krs: bool = True) -> Entity:
    """Random company."""
    city, postal = rng.choice(CITIES)
    name = f"{rng.choice(STEMS)} {rng.choice(TRADES)} {rng.choice(FORMS)}"
    return Entity(name, city, postal, f"{rng.choice(STREETS)} {rng.randint(1, 180)}", "000" + digits(rng, 7) if with_krs else None,
                  digits(rng, 10), digits(rng, 9), f"biuro@{name.split()[0].lower()}.example")


def authority(rng: random.Random) -> Entity:
    """Random contracting authority; public bodies usually have no KRS."""
    city, postal = rng.choice(CITIES)
    template = rng.choice(AUTHORITIES)
    if "{c}ski" in template:
        name = template.format(c=CITY_ADJ[city])
    elif template.startswith("Gmina"):
        name = template.format(c=city)
    else:
        name = template.replace("w {c}", "w " + CITY_LOC[city])
    has_krs = "sp. z o.o." in name
    return Entity(name, city, postal, f"{rng.choice(STREETS)} {rng.randint(1, 60)}", "000" + digits(rng, 7) if has_krs else None,
                  digits(rng, 10), digits(rng, 9), f"zamowienia@{CITY_LOC[city].lower()[:6]}.example")


def pl_date(d: date, rng: random.Random) -> str:
    """Render a date in one of the Polish notations."""
    return rng.choice([f"{d.day} {MONTHS[d.month - 1]} {d.year}", f"{d.day:02d}.{d.month:02d}.{d.year}", f"{d.isoformat()}", f"{d.day:02d}-{d.month:02d}-{d.year}"])


def build_case(rng: random.Random) -> Case:
    """Draw all facts of one case."""
    case = Case(rng)
    kind = rng.choices(["single", "consortium", "sole"], [0.6, 0.25, 0.15])[0]
    if kind == "sole":
        case.sole_trader = person(rng)
        firm = company(rng, with_krs=False)
        firm.name = f"{rng.choice(STEMS).upper()}-{rng.choice(['BUD', 'TECH', 'SERWIS', 'MED'])} {case.sole_trader.full}"
        case.appellants = [firm]
    else:
        case.appellants = [company(rng) for _ in range(2 if kind == "consortium" else 1)]
    case.authorities = [authority(rng) for _ in range(rng.choices([1, 2], [0.85, 0.15])[0])]
    case.attorneys = [person(rng) for _ in range(rng.choice([0, 1, 1, 2, 2]))] if rng.random() > 0.1 else []
    if case.attorneys and rng.random() < 0.15:
        case.attorney_pesel[0] = digits(rng, 11)
    if case.attorneys:
        lead = case.attorneys[0]
        case.law_firm = rng.choice([f"Kancelaria Radcy Prawnego {lead.full}", "Kancelaria Adwokacka i Partnerzy sp.p.", f"{lead.last} Legal sp. z o.o.", "Kancelaria Prawna Lex sp.k."])
        case.firm_email = f"kancelaria{rng.randint(1, 99)}@prawo.example"
    case.signers = [[person(rng) for _ in range(rng.choice([1, 1, 2]))] for _ in case.appellants]
    if case.sole_trader:
        case.signers = [[case.sole_trader]]
    case.title = rng.choice(TITLES)
    case.reference = rng.choice([f"ZP.{rng.randint(1, 999)}.{rng.randint(1, 99)}.2026", f"DZP/{rng.randint(1, 99)}/2026", f"IR.271.{rng.randint(1, 40)}.2026", f"SZP-{rng.randint(1, 99)}/26"])
    case.bzp = f"2026/BZP {digits(rng, 8)}" + (rng.choice(["", "", "/01"])) if rng.random() < 0.8 else None
    case.ted = (str(rng.randint(100000, 999999)), "2026") if rng.random() < 0.45 else None
    case.doc_date = date(2026, 1, 1) + timedelta(days=rng.randint(20, 330)) if rng.random() < 0.8 else None
    case.place = rng.choice(CITIES)[0] if case.doc_date else None
    base = case.doc_date or date(2026, 6, 1)
    case.act_date = base - timedelta(days=rng.randint(2, 9))
    case.reason = rng.randint(1, 12)
    case.winner = company(rng).name
    case.amount = rng.choice([7500.0, 15000.0, 20000.0, 17.0, 34.0, 50.0, 100.0, 200.0, 1234.56])
    case.from_account = digits(rng, 26)
    case.to_account = digits(rng, 26)
    case.transfer_date = case.act_date + timedelta(days=rng.randint(0, 3))
    case.transaction = f"CEN{digits(rng, 13)}" if rng.random() < 0.85 else None
    names = " i ".join(a.full for a in case.attorneys) or "pełnomocnika"
    case.transfer_title = f"opłata skarbowa od pełnomocnictwa dla {names} w postępowaniu przed KIO w przetargu {case.reference}" + (f" {case.transaction}" if case.transaction and rng.random() < 0.5 else "")
    return case


def ids_line(e: Entity, rng: random.Random) -> list[str]:
    """Identifier lines in one of several layouts."""
    nip = e.nip if rng.random() < 0.8 else f"{e.nip[:3]}-{e.nip[3:6]}-{e.nip[6:8]}-{e.nip[8:]}"
    parts = ([f"KRS: {e.krs}"] if e.krs else []) + [f"NIP: {nip}", f"REGON: {e.regon}"]
    if rng.random() < 0.3:
        return parts
    return [", ".join(parts)]


_GEN = None


def genitive(p: Person) -> str:
    """Name in genitive generated with Morfeusz2 (falls back to nominative)."""
    global _GEN
    try:
        import morfeusz2

        _GEN = _GEN or morfeusz2.Morfeusz(generate=True)
    except Exception:
        return p.full
    gender = "f" if p.female else "m1"
    out = []
    for word in p.full.split(" "):
        parts = []
        for piece in word.split("-"):
            forms = [f[0] for f in _GEN.generate(piece) if f[2].startswith("subst:sg:gen") and gender in f[2].split(":")[-1].split(".")]
            parts.append(forms[0] if forms else piece)
        out.append("-".join(parts))
    return " ".join(out)


def title_word(p: Person, rng: random.Random) -> str:
    """Professional title before an attorney name."""
    return rng.choice(["adw.", "r. pr.", "radca prawny", "adwokat", "r.pr."])


def appeal_lines(case: Case, rng: random.Random) -> tuple[list[str], dict[str, Any]]:
    """Render the appeal and its expected JSON."""
    lines: list[str] = []
    kio = rng.choice([["Prezes Krajowej Izby Odwoławczej", "ul. Postępu 17A", "02-676 Warszawa"], ["Do:", "Krajowa Izba Odwoławcza", "ul. Postępu 17a, 02-676 Warszawa"]])
    date_line = None
    if case.doc_date:
        d = case.doc_date
        date_line = rng.choice([f"{case.place}, dnia {d.day} {MONTHS[d.month - 1]} {d.year} r.", f"{case.place}, {d.day:02d}.{d.month:02d}.{d.year}", f"{case.place}, dnia {d.day:02d}.{d.month:02d}.{d.year} roku", f"{case.place}, data {d.day:02d}.{d.month:02d}.{d.year} r."])
    date_pos = rng.choice(["top", "after_parties", "after_title"])
    if date_line and date_pos == "top":
        lines += [">" + date_line, ""]
    lines += [">" + k for k in kio] + [""]

    app_block = []
    if len(case.appellants) > 1:
        app_block.append("Odwołujący: Konsorcjum wykonawców wspólnie ubiegających się o udzielenie zamówienia w składzie:")
        for i, e in enumerate(case.appellants, 1):
            app_block.append(f"{i}) {'Lider Konsorcjum' if i == 1 else 'Partner Konsorcjum'}:")
            app_block += [e.name, f"{e.street}, {e.postal} {e.city}"] + ids_line(e, rng)
    else:
        e = case.appellants[0]
        label = rng.choice(["Odwołujący:", "Odwołujący:", "ODWOŁUJĄCY:", "Wykonawca wnoszący odwołanie (Odwołujący):"])
        if rng.random() < 0.3:
            app_block += [f"{label} {e.name}, {e.street}, {e.postal} {e.city}"] + ids_line(e, rng)
        else:
            app_block += [label, e.name, f"{e.street}, {e.postal} {e.city}"] + ids_line(e, rng)
    if case.attorneys:
        if rng.random() < 0.3:
            app_block.append(rng.choice(["reprezentowany przez radcę prawnego ", "reprezentowana przez adwokata "]) + genitive(case.attorneys[0]))
        else:
            app_block.append(rng.choice(["reprezentowany przez: ", "reprezentowana przez: "]) + ", ".join(f"{title_word(a, rng)} {a.full}" for a in case.attorneys))
        app_block.append(f"adres do korespondencji: {case.law_firm}, {rng.choice(STREETS)} {rng.randint(1, 99)}, {rng.choice(CITIES)[1]} {rng.choice(CITIES)[0]}")
        app_block.append(rng.choice([f"tel. 000 000 000, e-mail: {case.firm_email}", f"e-mail: {case.firm_email}", f"{case.firm_email}"]))
    else:
        app_block.append(f"e-mail: {case.appellants[0].email}")

    auth_block = []
    if len(case.authorities) > 1:
        auth_block.append("Zamawiający (zamawiający wspólnie przeprowadzający postępowanie):")
        for i, e in enumerate(case.authorities, 1):
            auth_block.append(f"{i}) {'Zamawiający – Lider, prowadzący postępowanie' if i == 1 else 'Zamawiający – Partner'}:")
            auth_block += [e.name, f"{e.street}, {e.postal} {e.city}"] + ids_line(e, rng)
    else:
        e = case.authorities[0]
        label = rng.choice(["Zamawiający:", "ZAMAWIAJĄCY:"])
        if rng.random() < 0.3:
            auth_block += [f"{label} {e.name}, {e.street}, {e.postal} {e.city}"] + ids_line(e, rng) + [e.email]
        else:
            auth_block += [label, e.name, f"{e.street}, {e.postal} {e.city}"] + ids_line(e, rng) + [e.email]
    blocks = [app_block, auth_block] if rng.random() < 0.5 else [auth_block, app_block]
    lines += blocks[0] + [""] + blocks[1] + [""]
    if date_line and date_pos == "after_parties":
        lines += [">" + date_line, ""]

    quote = rng.choice([("„", "”"), ('"', '"')])
    ref_label = rng.choice(["nr referencyjny:", "znak sprawy:", "numer postępowania:", "nr referencyjny sprawy:"])
    dot = f"dotyczy: postępowania o udzielenie zamówienia publicznego prowadzonego w trybie {rng.choice(['przetargu nieograniczonego', 'podstawowym bez negocjacji', 'negocjacji z ogłoszeniem'])} pn. {quote[0]}{case.title}{quote[1]}, {ref_label} {case.reference}"
    if case.bzp:
        dot += f", ogłoszenie o zamówieniu w Biuletynie Zamówień Publicznych nr {case.bzp}"
    if case.ted:
        dot += rng.choice([f", ogłoszenie w Dzienniku Urzędowym Unii Europejskiej nr 2026/S {rng.randint(1, 250):03d}-{case.ted[0]}", f", numer ogłoszenia TED: {case.ted[0]}-{case.ted[1]}"])
    lines += [dot, ""]
    if rng.random() < 0.5:
        lines += [f"Wpis od odwołania: {rng.choice(['7 500,00 zł', '15 000,00 zł', '20 000,00 zł'])}", ""]
    lines.append("#" + rng.choice(["ODWOŁANIE", "O D W O Ł A N I E", "ODWOŁANIE od czynności Zamawiającego"]))
    if date_line and date_pos == "after_title":
        lines += [">" + date_line]
    lines.append("")
    name = " oraz ".join(e.name for e in case.appellants)
    lines.append(f"Działając w imieniu {name} (dalej: „Odwołujący”), na podstawie art. 505 ust. 1 i art. 513 pkt 1 i 2 ustawy z dnia 11 września 2019 r. – Prawo zamówień publicznych (dalej: „Pzp”), wnoszę odwołanie wobec czynności i zaniechań Zamawiającego.")
    lines.append(f"Uprzednio, w dniu {pl_date(case.act_date - timedelta(days=30), rng)} r., Zamawiający wszczął postępowanie (sygn. poprzedniej sprawy KIO {rng.randint(100, 4000)}/25).")
    verb = rng.choice(REASONS[case.reason][1]).format(w=case.winner)
    item = rng.choice(REASONS[case.reason][2]).format(w=case.winner)
    other = rng.choice([r for r in REASONS if r != case.reason])
    other_item = rng.choice(REASONS[other][2]).format(w=case.winner)
    if rng.random() < 0.5:
        lines.append(f"Zamawiający w dniu {pl_date(case.act_date, rng)} roku {verb}.")
        lines.append(f"Zarzut nr 1 dotyczy czynności opisanej powyżej. Ponadto Zamawiający dopuścił się {other_item}.")
    else:
        lines.append("Odwołanie wnoszę wobec czynności i zaniechań Zamawiającego, polegających na:")
        lines.append(f"1) {item} z dnia {pl_date(case.act_date, rng)} r.;")
        lines.append(f"2) {other_item};")
    lines.append("Zarzucam Zamawiającemu naruszenie art. 16 pkt 1 i 2 Pzp.")
    lines += [FILLER * rng.randint(4, 12), "", "Wnoszę o uwzględnienie odwołania w całości.", "", ">" + (case.attorneys[0].full if case.attorneys else case.appellants[0].name)]

    t = case.ted
    expected = {
        "OdwolanieKIO": {
            "data": case.doc_date.isoformat() if case.doc_date else None,
            "czynnosc_dzien": case.act_date.isoformat(),
            "czynnosc_powod_id": case.reason,
            "czynnosc_opis": REASONS[case.reason][0],
            "miejscowosc": case.place,
        },
        "Odwolujacy": [{
            "krs": case.appellants[0].krs,
            "nazwa": case.appellants[0].name,
            "nip": case.appellants[0].nip,
            "regon": case.appellants[0].regon,
            "przez-pelnomocnika": 1 if case.attorneys else 0,
            "pelnomocnik": {
                "imie_nazwisko": case.attorneys[0].full if case.attorneys else None,
                "nazwa": case.law_firm,
                "mail": case.firm_email,
            },
        }],
        "Zamawiajacy": [{
            "krs": e.krs, "nazwa": e.name, "nip": e.nip, "regon": e.regon,
            "prowadzacy_postepowanie": (1 if i == 0 else 0) if len(case.authorities) > 1 else None,
        } for i, e in enumerate(case.authorities)],
        "ZamowieniePubliczne": {
            "numer_bzp": case.bzp.replace(" ", "") if case.bzp else None,
            "numer_postepowania": case.reference,
            "numer_ted": f"{t[0]}-{t[1]}" if t else None,
            "tytul": case.title,
        },
    }
    return lines, expected


def poa_lines(case: Case, rng: random.Random) -> tuple[list[str], dict[str, Any]]:
    """Render the power of attorney and its expected JSON."""
    d = case.act_date + timedelta(days=1)
    lines = [">" + f"{case.appellants[0].city}, {pl_date(d, rng)}", "", "#" + rng.choice(["PEŁNOMOCNICTWO", "P E Ł N O M O C N I C T W O", "PEŁNOMOCNICTWO PROCESOWE"]), ""]
    attorneys = case.attorneys or [person(rng)]
    who = []
    for i, a in enumerate(attorneys):
        pesel = f", PESEL {case.attorney_pesel[i]}" if i in case.attorney_pesel else ""
        who.append(f"{title_word(a, rng)} {a.full}{pesel} (nr wpisu na listę: {rng.choice(['WA', 'KR', 'PO', 'GD'])}-{rng.randint(100, 9999)})")
    grant = rng.choice(["udzielam pełnomocnictwa", "ustanawiam pełnomocnikiem", "niniejszym upoważniam"])
    if case.sole_trader:
        e = case.appellants[0]
        lines.append(f"Ja, niżej podpisany {case.sole_trader.full}, prowadzący działalność gospodarczą pod firmą {e.name}, {e.street}, {e.postal} {e.city}, NIP {e.nip}, REGON {e.regon} (dalej: „Mocodawca”), {grant}: {', '.join(who)}.")
    elif len(case.appellants) > 1:
        parts = "; ".join(f"{i}) {e.name}, {e.street}, {e.postal} {e.city}, KRS {e.krs}, NIP {e.nip}, REGON {e.regon}" for i, e in enumerate(case.appellants, 1))
        lines.append(f"Wykonawcy wspólnie ubiegający się o udzielenie zamówienia (Konsorcjum): {parts} (dalej łącznie: „Mocodawca”), reprezentowani przez osoby podpisane poniżej, udzielają pełnomocnictwa: {', '.join(who)}.")
    else:
        e = case.appellants[0]
        lead = rng.choice([f"Mocodawcą jest {e.name}, {e.street}, {e.postal} {e.city}, KRS {e.krs}, NIP {e.nip}, REGON {e.regon}.", f"{e.name}, {e.street}, {e.postal} {e.city}, KRS {e.krs}, NIP {e.nip}, REGON {e.regon} (dalej: „Mocodawca”), reprezentowana przez osoby podpisane poniżej,"])
        lines.append(f"{lead} {grant}: {', '.join(who)}.")
    lines += ["", f"Pełnomocnictwo udzielone zostaje do reprezentowania Mocodawcy w postępowaniu pn. „{case.title}”, numer postępowania: {case.reference}, prowadzonym przez {case.authorities[0].name}, w tym do wniesienia odwołania do Prezesa Krajowej Izby Odwoławczej.", ""]
    if len(case.appellants) > 1:
        for e, signers in zip(case.appellants, case.signers):
            lines.append(f"W imieniu {e.name}:")
            for s in signers:
                lines += ["............................................", s.full, rng.choice(["Prezes Zarządu", "Członek Zarządu", "Prokurent", "Wspólnik"])]
    else:
        lines.append("Mocodawca:")
        for s in case.signers[0]:
            lines += ["............................................", s.full, rng.choice(["Prezes Zarządu", "Prokurent", "Właściciel"]) if not case.sole_trader else ""]
    lines += ["", "Pełnomocnictwo przyjmuję:"]
    for a in attorneys:
        lines += ["............................................", f"{title_word(a, rng)} {a.full}"]
    expected = {
        "mocodawca": [{
            "data": {
                "imie_nazwisko": case.sole_trader.full if case.sole_trader else None,
                "krs": e.krs,
                "nazwa": e.name,
                "nip": e.nip,
                "typ": "osoba_fizyczna" if case.sole_trader else "osoba_prawna",
            },
            "podpisujacy": [{"imie_nazwisko": s.full} for s in signers],
        } for e, signers in zip(case.appellants, case.signers)],
        "pelnomocnicy": [{"imie_nazwisko": a.full, "pesel": case.attorney_pesel.get(i)} for i, a in enumerate(attorneys)],
    }
    return lines, expected


def money(value: float, rng: random.Random) -> str:
    """Render an amount in one of several notations."""
    whole, cents = f"{value:.2f}".split(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    return rng.choice([f"{grouped},{cents} PLN", f"PLN {whole}.{cents}", f"{grouped},{cents} zł", f"{whole},{cents}", f"{grouped},{cents} zł (słownie: {whole} złotych {cents}/100)"])


def account(number: str, rng: random.Random) -> str:
    """Render an account number with or without PL prefix and spaces."""
    spaced = number[:2] + " " + " ".join(number[i:i + 4] for i in range(2, 26, 4))
    return rng.choice([f"PL{number}", spaced, f"PL{spaced}", number, f"PL {spaced}"])


def transfer_lines(case: Case, rng: random.Random) -> tuple[list[str], dict[str, Any]]:
    """Render the bank transfer confirmation in one of five layouts and its expected JSON."""
    payer, payee = case.appellants[0], case.authorities[0]
    d = pl_date(case.transfer_date, rng)
    ref = case.transaction
    layout = rng.choice(["colon", "nextline", "dots", "letter", "columns"])
    bank = rng.choice(["Bank Północny S.A.", "Kredyt Mazowsze", "Bank Spółdzielczy w Opolu", "Nova Bank Polska"])
    if layout == "colon":
        lines = [f"#{bank} – Potwierdzenie wykonania przelewu", "", f"Nazwa zleceniodawcy: {payer.name}", f"Rachunek zleceniodawcy: {account(case.from_account, rng)}",
                 f"Nazwa odbiorcy: {payee.name}", f"Rachunek odbiorcy: {account(case.to_account, rng)}", f"Kwota: {money(case.amount, rng)}", f"Data operacji: {d}",
                 f"Tytuł przelewu: {case.transfer_title}"] + ([f"Numer referencyjny: {ref}"] if ref else []) + ["Status: Zrealizowany"]
    elif layout == "nextline":
        lines = [f"#{bank}", "POTWIERDZENIE WYKONANIA PRZELEWU", "", "Zleceniodawca", payer.name, "Rachunek nadawcy", account(case.from_account, rng), "Odbiorca", payee.name,
                 "Rachunek odbiorcy", account(case.to_account, rng), "Kwota operacji", money(case.amount, rng), "Data transakcji", d, "Tytuł przelewu", case.transfer_title] + (["Identyfikator operacji", ref] if ref else [])
    elif layout == "dots":
        lines = [f"#{bank.upper()}", "POTWIERDZENIE REALIZACJI POLECENIA PRZELEWU", "-" * 60, f"KWOTA PRZELEWU ........................ {money(case.amount, rng)}",
                 f"DATA REALIZACJI ....................... {d}", "RACHUNEK NADAWCY", account(case.from_account, rng), "RACHUNEK ODBIORCY", account(case.to_account, rng), payee.name,
                 "TYTUŁ PRZELEWU:", case.transfer_title] + ([f"NR REF. ............................... {ref}"] if ref else []) + ["STATUS .............................. Wykonany"]
    elif layout == "letter":
        amount_text = f"{case.amount:.2f}".replace(".", ",")
        lines = [f"#{bank}", "Centrum Obsługi Klienta", "", payer.name, "", "Dotyczy: potwierdzenie realizacji polecenia przelewu", "",
                 f"Bank potwierdza, że w dniu {d} z rachunku nr {account(case.from_account, rng)}, prowadzonego dla {payer.name}, wykonano przelew krajowy w kwocie {amount_text} na rachunek nr {account(case.to_account, rng)}, prowadzony dla {payee.name}.",
                 f"Tytuł przelewu: „{case.transfer_title}”."] + ([f"Numer referencyjny operacji: {ref}."] if ref else []) + ["", "Z poważaniem", "Dział Rozliczeń"]
    else:
        lines = [f"#{bank}", "Potwierdzenie transakcji", "", f"Płatnik: {payer.name}", f"Rachunek obciążany: {account(case.from_account, rng)}", f"Beneficjent: {payee.name}",
                 f"Rachunek uznawany: {account(case.to_account, rng)}", f"Kwota operacji: {money(case.amount, rng)}", f"Data wykonania: {d}", "Opis", case.transfer_title] + ([f"Nr ref. {ref}"] if ref else [])
    expected = {"przelew_bankowy": {
        "data_operacji": case.transfer_date.isoformat(),
        "kwota": case.amount,
        "na_rachunek": case.to_account,
        "numer_transakcji": ref,
        "tytul": case.transfer_title,
        "z_rachunku": case.from_account,
    }}
    return lines, expected


def negatives(rng: random.Random) -> dict[str, list[str]]:
    """Look-alike documents that must stay unclassified."""
    a, z = company(rng), authority(rng)
    return {
        "wyrok_kio.pdf": [f"Sygn. akt: KIO {rng.randint(100, 4000)}/26", "#WYROK", "Warszawa, dnia 3 marca 2026 r.", "Krajowa Izba Odwoławcza - w składzie:", "Przewodniczący: Jan Kowalski", "Protokolant: Anna Nowak",
                          f"po rozpoznaniu odwołania wniesionego przez wykonawcę {a.name} w postępowaniu prowadzonym przez {z.name}", "orzeka:", "1. oddala odwołanie,", FILLER],
        "odpowiedz_na_odwolanie.pdf": [">Warszawa, dnia 5 marca 2026 r.", "Prezes Krajowej Izby Odwoławczej", "Odwołujący:", a.name, "Zamawiający:", z.name, "", "#ODPOWIEDŹ NA ODWOŁANIE",
                                       "Działając w imieniu Zamawiającego wnoszę o oddalenie odwołania w całości.", FILLER],
        "przystapienie.pdf": [">Kraków, 6 marca 2026 r.", "Prezes Krajowej Izby Odwoławczej", "Odwołujący:", a.name, "Zamawiający:", z.name, "", "#PRZYSTĄPIENIE DO POSTĘPOWANIA ODWOŁAWCZEGO",
                              "Wykonawca zgłasza przystąpienie do postępowania odwoławczego po stronie Zamawiającego.", FILLER],
        "faktura.pdf": ["#FAKTURA VAT nr 12/03/2026", f"Sprzedawca: {a.name}, NIP {a.nip}", f"Nabywca: {z.name}", f"Rachunek: PL{digits(rng, 26)}", "Do zapłaty: 1 230,00 zł", "Termin płatności: 14 dni"],
        "pismo.pdf": [">Lublin, 2 lutego 2026 r.", f"{z.name}", "", "#Informacja o wyborze najkorzystniejszej oferty", f"Zamawiający informuje, że w postępowaniu pn. „{rng.choice(TITLES)}” wybrano ofertę wykonawcy {a.name}.", FILLER],
    }


def main(argv: list[str] | None = None) -> int:
    """Generate the test set."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=int, default=120)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=Path("data_synth"))
    args = parser.parse_args(argv)
    rng = random.Random(args.seed)
    fonts = register_font()
    for index in range(1, args.cases + 1):
        case = build_case(rng)
        folder = args.out / "cases" / f"synt_{index:03d}"
        folder.mkdir(parents=True, exist_ok=True)
        for pdf_name, json_name, render in (("odwolanie.pdf", "odwolanie.json", appeal_lines), ("pelnomocnictwo.pdf", "pelnomocnictwo.json", poa_lines), ("potwierdzenie_przelewu.pdf", "przelew.json", transfer_lines)):
            lines, expected = render(case, rng)
            write_pdf(folder / pdf_name, lines, fonts, footer=pdf_name == "odwolanie.pdf")
            (folder / json_name).write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
    negative_dir = args.out / "negatives"
    negative_dir.mkdir(parents=True, exist_ok=True)
    for name, lines in negatives(rng).items():
        write_pdf(negative_dir / name, lines, fonts)
    print(f"Wrote {args.cases} cases to {args.out / 'cases'} and {len(negatives(rng))} negatives to {negative_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
