import zipfile
from pathlib import Path

import pytest

from feed_survey import tranco


def test_subdomain_cache_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(tranco, "CACHE_DIR", str(cache_dir))
    (cache_dir / tranco.TRANCO_SUBDOMAINS_CSV).write_text(
        "1,WWW.Example.COM\n2,foo.github.io\n3,shop.example\n",
        encoding="utf-8",
    )

    assert tranco.get_tranco_list(2, include_subdomains=True) == {
        "example.com",
        "foo.github.io",
    }


def test_standard_cache_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(tranco, "CACHE_DIR", str(cache_dir))
    (cache_dir / tranco.TRANCO_STANDARD_CSV).write_text(
        "1,example.com\n2,example.org\n",
        encoding="utf-8",
    )

    assert tranco.get_tranco_list(include_subdomains=False) == {
        "example.com",
        "example.org",
    }


def test_worker_alias_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tranco, "CACHE_DIR", str(tmp_path / "cache"))
    (tmp_path / tranco.TRANCO_STANDARD_CSV).write_text(
        "1,foo.github.io\n",
        encoding="utf-8",
    )

    assert tranco.get_tranco_list(include_subdomains=True) == {
        "foo.github.io",
    }


def test_extracts_first_csv_member(tmp_path: Path) -> None:
    zip_path = tmp_path / "tranco.zip"
    csv_path = tmp_path / "selected.csv"
    with zipfile.ZipFile(zip_path, "w") as zip_out:
        zip_out.writestr("README.txt", "ignored")
        zip_out.writestr("nested/top.csv", "1,example.com\n")

    tranco.extract_tranco_csv(str(zip_path), str(csv_path))

    assert csv_path.read_text(encoding="utf-8") == "1,example.com\n"
