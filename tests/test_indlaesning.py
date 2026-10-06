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
