from datetime import datetime

import pytest

from app import db, services
from app.agent import _trim, build_system_prompt
from app.privacy_guard import redact
from app.services import BookingError
from app.tools import execute_tool

NOW = datetime(2026, 10, 14, 10, 0)  # mercoledì
SAT = "2026-10-17"
MON = "2026-10-19"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    db.init_db(c)
    yield c
    c.close()


def book(conn, time="20:00", party=2, date=SAT, name="[NOME_AAAAAA]"):
    return services.create_reservation(conn, date, time, party, name, now=NOW)


def test_seed(conn):
    assert conn.execute("SELECT COUNT(*) FROM restaurant_tables").fetchone()[0] == 13
    assert "Primi" in services.get_menu(conn)
    assert services.get_info(conn)["orari"]["lunedi"] == "chiuso"


def test_menu_diet_filter(conn):
    vegan = services.get_menu(conn, diet="vegano")
    names = [p["piatto"] for items in vegan.values() for p in items]
    assert "Gnocchi al pomodoro" in names and "Parmigiana di melanzane" not in names
    gf_primi = services.get_menu(conn, "Primi", "celiaco")
    assert [p["piatto"] for p in gf_primi["Primi"]] == ["Risotto alla milanese"]
    assert "nota" in services.get_menu(conn, "Secondi", "vegano")
    with pytest.raises(BookingError):
        services.get_menu(conn, diet="carnivoro")
    with pytest.raises(BookingError):
        services.get_menu(conn, "Pizze")


def test_parsing():
    assert services.parse_time("20") == "20:00"
    assert services.parse_time("20.30") == "20:30"
    assert services.parse_date("17/10/2026").isoformat() == SAT
    with pytest.raises(BookingError):
        services.parse_time("venti")
    with pytest.raises(BookingError):
        services.parse_party_size(11)


@pytest.mark.parametrize("date,time", [(MON, "20:00"), ("2026-10-13", "20:00"), (SAT, "17:00"),
                                       (SAT, "22:30"), ("2026-10-14", "09:00"), ("2027-06-01", "20:00")])
def test_invalid_slots(conn, date, time):
    with pytest.raises(BookingError):
        services.check_availability(conn, date, time, 2, now=NOW)


def test_create_get_modify_cancel(conn):
    res = book(conn)
    assert len(res["codice"]) == 6 and res["stato"] == "confermata" and res["tavolo"] == "T1"
    assert services.get_reservation(conn, res["codice"])["ora"] == "20:00"
    mod = services.modify_reservation(conn, res["codice"], time_str="21:00", party_size=4, now=NOW)
    assert mod["ora"] == "21:00" and mod["persone"] == 4 and mod["tavolo"] == "T5"
    with pytest.raises(BookingError):
        services.modify_reservation(conn, res["codice"], time_str="21:00", party_size=4, now=NOW)
    assert services.cancel_reservation(conn, res["codice"], now=NOW)["stato"] == "cancellata"
    with pytest.raises(BookingError):
        services.cancel_reservation(conn, res["codice"], now=NOW)


def test_overlap_and_alternatives(conn):
    for _ in range(4):  # 4 tavoli da 2 + quelli da 4/6 accettabili per 2 persone
        book(conn)
    while True:
        try:
            book(conn)
        except BookingError as exc:
            assert "Orari liberi" in str(exc)
            break
    av = services.check_availability(conn, SAT, "20:00", 2, now=NOW)
    assert av["disponibile"] is False and av["orari_alternativi_stesso_giorno"]
    # due ore dopo il tavolo è di nuovo libero
    assert services.check_availability(conn, SAT, "22:00", 2, now=NOW)["disponibile"] is True


def test_modify_keeps_own_table(conn):
    res = book(conn, party=10)
    mod = services.modify_reservation(conn, res["codice"], time_str="20:30", now=NOW)
    assert mod["tavolo"] == "T13"


def test_failed_modify_leaves_original(conn):
    res = book(conn, party=10)
    other = book(conn, time="13:00", party=10)
    with pytest.raises(BookingError):
        services.modify_reservation(conn, other["codice"], time_str="20:00", now=NOW)
    assert services.get_reservation(conn, other["codice"])["ora"] == "13:00"
    assert services.get_reservation(conn, res["codice"])["ora"] == "20:00"


def test_name_required(conn):
    with pytest.raises(BookingError):
        book(conn, name="  ")


def test_tool_dispatcher_never_raises(conn):
    assert execute_tool(conn, "get_reservation", {"code": "000000"})["ok"] is False
    assert execute_tool(conn, "check_availability", {"date": "boh"})["ok"] is False
    assert execute_tool(conn, "nope", {})["ok"] is False
    assert execute_tool(conn, "get_menu", {"category": "null"})["ok"] is True


def test_privacy_guard():
    text, found = redact("scrivete a mario.rossi@gmail.com o 333 123 4567, codice 482913, il 17/10/2026")
    assert "gmail" not in text and "4567" not in text and "482913" in text and "17/10/2026" in text
    assert set(found) == {"EMAIL", "TEL"}
    assert redact("[NOME_1A2B3C] [TEL_9F8E7D]")[1] == []


def test_system_prompt_calendar():
    p = build_system_prompt("voice", NOW)
    assert "mercoledì 2026-10-14 (oggi)" in p and "lunedì 2026-10-19 - CHIUSO" in p and "VOCALE" in p


def test_trim_starts_with_user(monkeypatch):
    from app import config
    monkeypatch.setattr(config, "SESSION_MAX_MESSAGES", 3)
    h = [{"role": "user"}, {"role": "assistant"}, {"role": "tool"}, {"role": "assistant"}, {"role": "user"}]
    assert _trim(h)[0]["role"] == "user"


def test_validate_phone():
    from app.services import validate_phone
    # Numeri validi
    assert validate_phone("340 1234567") == "340 1234567"
    assert validate_phone("+39 0734 678910") == "+39 0734 678910"
    assert validate_phone("[TEL_9D54F8]") == "[TEL_9D54F8]"
    assert validate_phone("[TEL_OSCURATO]") == "[TEL_OSCURATO]"

    # Numeri non validi
    for bad in ["456", "[TEL_456]", "123", "ciao", "12345"]:
        with pytest.raises(BookingError):
            validate_phone(bad)

