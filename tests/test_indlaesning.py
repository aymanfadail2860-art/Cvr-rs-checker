from __future__ import annotations

from pathlib import Path

from cvr_aarsvaerk_checker.indlaesning import er_gyldigt_cvr, laes_cvr_numre


def test_tekstfil_med_kommentarer_dubletter_og_ugyldige(tmp_path: Path) -> None:
    fil = tmp_path / "cvr.txt"
    fil.write_text("# liste\n12345678\n\n 87654321 \n12345678\n0123456\n1234567X\nDK11223344\n", encoding="utf-8")
    r = laes_cvr_numre(fil)
    assert r.gyldige == ["12345678", "87654321", "11223344"]
    assert r.ugyldige == ["0123456", "1234567X"]
    assert r.antal_dubletter == 1


def test_csv_med_overskrift_bruger_cvr_kolonnen(tmp_path: Path) -> None:
    fil = tmp_path / "cvr.csv"
    fil.write_text('"Firma";"CVR nr."\n"Æble ApS";"1234 5678"\nBanan A/S;87654321\n', encoding="utf-8-sig")
    r = laes_cvr_numre(fil)
    assert r.gyldige == ["12345678", "87654321"]


def test_csv_med_komma_og_uden_overskrift(tmp_path: Path) -> None:
    fil = tmp_path / "cvr.csv"
    fil.write_text("12345678,Firma A\n87654321,Firma B\n", encoding="utf-8")
    assert laes_cvr_numre(fil).gyldige == ["12345678", "87654321"]


def test_excel_csv_i_windows_tegnsaet(tmp_path: Path) -> None:
    fil = tmp_path / "cvr.csv"
    fil.write_bytes("cvr;navn\n12345678;Søren Å ApS\n".encode("cp1252"))
    assert laes_cvr_numre(fil).gyldige == ["12345678"]


def test_cvr_validering() -> None:
    assert er_gyldigt_cvr("10582989")
    assert not er_gyldigt_cvr("01234567")  # må ikke starte med 0
    assert not er_gyldigt_cvr("1234567")
    assert not er_gyldigt_cvr("123456789")
    assert not er_gyldigt_cvr("")


# --- Fund fra review --------------------------------------------------------


def test_komma_i_adresse_og_beloeb_forskyder_ikke_kolonnen(tmp_path: Path) -> None:
    fil = tmp_path / "cvr.csv"
    fil.write_text(
        "Navn;Adresse;Omsætning;CVR-nummer\n"
        "A ApS;Vestergade 12, 1. th.;1234,5;11111111\n"
        "B ApS;Hovedgaden 3;7,0;22222222\n",
        encoding="utf-8",
    )
    r = laes_cvr_numre(fil)
    assert r.gyldige == ["11111111", "22222222"]
    assert r.ugyldige == []


def test_citerede_felter_med_komma(tmp_path: Path) -> None:
    fil = tmp_path / "cvr.csv"
    fil.write_text('"Firma","CVR"\n"Hansen, Jensen & Co ApS","11111111"\n', encoding="utf-8")
    assert laes_cvr_numre(fil).gyldige == ["11111111"]


def test_utf16_unicode_tekst_fra_excel(tmp_path: Path) -> None:
    fil = tmp_path / "cvr.txt"
    fil.write_bytes("CVR\tNavn\r\n11111111\tÆble ApS\r\n22222222\tB ApS\r\n".encode("utf-16"))
    assert laes_cvr_numre(fil).gyldige == ["11111111", "22222222"]


def test_dos_tegnsaet_crasher_ikke(tmp_path: Path) -> None:
    fil = tmp_path / "cvr.csv"
    fil.write_bytes("Navn;CVR\r\nØstergaard ApS;11111111\r\nÅen A/S;22222222\r\n".encode("cp850"))
    assert laes_cvr_numre(fil).gyldige == ["11111111", "22222222"]


def test_tomme_celler_springes_over(tmp_path: Path) -> None:
    fil = tmp_path / "cvr.csv"
    fil.write_text("Navn;CVR\r\nA ApS;11111111\r\nC ApS;\r\nD ApS;\r\n;\r\n;\r\n", encoding="utf-8")
    r = laes_cvr_numre(fil)
    assert r.gyldige == ["11111111"]
    assert r.ugyldige == []
    assert r.antal_dubletter == 0
    assert r.antal_tomme == 4


def test_excel_talformater_accepteres(tmp_path: Path) -> None:
    fil = tmp_path / "cvr.csv"
    fil.write_text("CVR\n11111111.0\n33.333.333\nDK-44444444\ndk:55555555\n2,22E+07\n", encoding="utf-8")
    r = laes_cvr_numre(fil)
    assert r.gyldige == ["11111111", "33333333", "44444444", "55555555"]
    assert r.ugyldige == ["2,22E+07"]  # videnskabelig notation har mistet cifre
