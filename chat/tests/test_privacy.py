import pytest

from chat_app.privacy import Pseudonymizer, find_personal_data


@pytest.fixture
def p(tmp_path):
    return Pseudonymizer(tmp_path / "vault.json", b"chiave-di-test")


def types(text):
    return [(text[a:b], t) for a, b, t in find_personal_data(text)]


@pytest.mark.parametrize("text,expected", [
    ("Mi chiamo Mario Rossi e vorrei prenotare", [("Mario Rossi", "NOME")]),
    ("mi chiamo mario rossi e vorrei prenotare", [("mario rossi", "NOME")]),
    ("A nome di Bianchi per 4 persone", [("Bianchi", "NOME")]),
    ("Sono Giulia Verdi, il mio numero è 333 123 4567", [("Giulia Verdi", "NOME"), ("333 123 4567", "TEL")]),
    ("prenota per Luca sabato", [("Luca", "NOME")]),
    ("contattatemi a giulia.verdi@example.com", [("giulia.verdi@example.com", "EMAIL")]),
    ("cell +39 347 1234567", [("+39 347 1234567", "TEL")]),
    ("il mio CF è RSSMRA80A01F205X", [("RSSMRA80A01F205X", "CF")]),
    ("carta 4111 1111 1111 1111", [("4111 1111 1111 1111", "CARTA")]),
    ("IBAN IT60X0542811101000000123456", [("IT60X0542811101000000123456", "IBAN")]),
])
def test_detects_personal_data(text, expected):
    assert types(text) == expected


@pytest.mark.parametrize("text", [
    "Vorrei prenotare per sabato 17/10/2026 alle 20:30 per 4 persone",
    "Sono 4 persone, uno è celiaco",
    "sono interessato al menu vegetariano",
    "Vorrei cancellare la prenotazione 887649",
    "il 17.10.2026 alle 20.30",
    "Quanto costa la cotoletta? 26 euro?",
    "Vorrei un tavolo per due domani a pranzo",
    "il nome del piatto con le vongole?",
    "A nome mio",
])
def test_no_false_positives(text):
    assert types(text) == []


def test_roundtrip_and_determinism(p, tmp_path):
    masked, replaced = p.pseudonymize("Mi chiamo Mario Rossi, tel 333 1234567")
    assert "Mario" not in masked and "333" not in masked
    assert [r["type"] for r in replaced] == ["NOME", "TEL"]
    # stesso dato => stesso segnaposto, anche con formattazione diversa
    again, _ = p.pseudonymize("a nome mario  rossi, numero +39 333-123-4567")
    assert replaced[0]["token"] in again and replaced[1]["token"] in again
    reply = f"Prenotazione confermata per {replaced[0]['token']}, la contatteremo al {replaced[1]['token']}."
    assert p.reidentify(reply) == "Prenotazione confermata per Mario Rossi, la contatteremo al 333 1234567."
    # il vault persiste su disco
    p2 = Pseudonymizer(tmp_path / "vault.json", b"chiave-di-test")
    assert p2.reidentify(replaced[0]["token"]) == "Mario Rossi"


def test_existing_tokens_untouched(p):
    masked, _ = p.pseudonymize("Mi chiamo Anna")
    assert p.pseudonymize(masked) == (masked, [])


def test_different_secret_different_token(tmp_path):
    a = Pseudonymizer(tmp_path / "a.json", b"k1").pseudonymize("Mi chiamo Anna")[0]
    b = Pseudonymizer(tmp_path / "b.json", b"k2").pseudonymize("Mi chiamo Anna")[0]
    assert a != b


def test_reidentify_without_brackets(p):
    token = p.pseudonymize("Sono Marco")[1][0]["token"]
    assert p.reidentify("Grazie " + token.strip("[]")) == "Grazie Marco"
