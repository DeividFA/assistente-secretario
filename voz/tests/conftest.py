"""Isolamento comum: nenhum teste lê ou grava as falas reais do Deivid."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def banco_de_falas_isolado(tmp_path, monkeypatch):
    # vocabulario.termos() soma as palavras mais faladas do banco real (T31); sem isto, os
    # testes passam ou falham conforme o que foi dito ao secretário no dia.
    import padrao_fala
    monkeypatch.setattr(padrao_fala, "BANCO", tmp_path / "falas_teste.db")
