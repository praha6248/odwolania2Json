"""Reading order reconstruction of OCR boxes."""

from odwolania2json.ocr import boxes_to_text, fix_ocr_text


def box(left, top, right, bottom):
    """Build a 4-point box from coordinates."""
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def test_label_centred_against_value_block_moves_above_it():
    """A left-column label vertically centred on a two-line value is emitted before the whole value."""
    boxes = [
        box(300, 100, 900, 130),
        box(50, 138, 220, 168),
        box(300, 140, 700, 170),
        box(300, 180, 500, 210),
    ]
    texts = ["Miejskie Przedsiębiorstwo Spółka z ograniczoną", "Zamawiający:", "odpowiedzialnością", "Warszawa"]
    assert boxes_to_text(boxes, texts).split("\n") == [
        "Zamawiający:",
        "Miejskie Przedsiębiorstwo Spółka z ograniczoną",
        "odpowiedzialnością",
        "Warszawa",
    ]


def test_regular_lines_keep_order():
    """Ordinary text lines stay in top-to-bottom, left-to-right order."""
    boxes = [box(50, 10, 200, 30), box(220, 12, 400, 32), box(50, 50, 300, 70)]
    assert boxes_to_text(boxes, ["Ala", "ma kota", "Drugi wiersz"]) == "Ala ma kota\nDrugi wiersz"


def test_label_does_not_pull_unrelated_block_from_other_column():
    """A label on its own line keeps its place below an address block printed in another column."""
    boxes = [box(600, 10, 900, 30), box(600, 40, 900, 60), box(50, 70, 220, 90), box(50, 100, 400, 120)]
    texts = ["ul. Postępu 17A", "02-676 Warszawa", "Zamawiający:", "Gmina Rudnik Wielki"]
    assert boxes_to_text(boxes, texts).split("\n") == texts


def test_ocr_fixes_legal_forms():
    """Frequent OCR confusions in legal forms are repaired."""
    assert fix_ocr_text("Spófka z ograniczona odpowiedzialnościa, z 0.o.") == "Spółka z ograniczoną odpowiedzialnością, z o.o."


def test_caption_row_pairs_with_value_row():
    """Bank forms with captions in one row and values below become caption-value lines."""
    boxes = [box(50, 10, 200, 30), box(500, 10, 650, 30), box(52, 40, 160, 60), box(505, 40, 640, 60)]
    texts = ["Kwota operacji", "Data transakcji", "200,00 PLN", "2026-03-21"]
    assert boxes_to_text(boxes, texts).split("\n") == ["Kwota operacji 200,00 PLN", "Data transakcji 2026-03-21"]


def test_signature_columns_are_unfolded():
    """Two signature columns headed by captions with colons are emitted one after another."""
    boxes = [box(50, 10, 200, 30), box(500, 10, 750, 30), box(50, 50, 220, 70), box(500, 50, 760, 70), box(50, 80, 200, 100)]
    texts = ["Mocodawca:", "Pełnomocnictwo przyjmuję:", "Oliwia Kaczmarek", "r. pr. Aleksandra Marciniak", "Prezes Zarządu"]
    assert boxes_to_text(boxes, texts).split("\n") == [
        "Mocodawca:", "Oliwia Kaczmarek", "Prezes Zarządu", "Pełnomocnictwo przyjmuję:", "r. pr. Aleksandra Marciniak",
    ]


def test_spelling_repair_restores_words_but_keeps_names():
    """OCR words outside the lexicon are repaired; real words and unknown proper names stay."""
    from odwolania2json.spell import correct_text

    assert correct_text("Wroctaw, Stawomir Ustugi, ODWOLANIE postepowania") == "Wrocław, Sławomir Usługi, ODWOŁANIE postępowania"
    assert correct_text("Kaczmark Belmoria Furman") == "Kaczmark Belmoria Furman"
