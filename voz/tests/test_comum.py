import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from assistente_voz import ATIVACAO
from comum import normalizar, texto_para_fala


@pytest.mark.parametrize("texto, esperado", [
    ("  Secretário, AÇÃO!  ", "secretario acao"),
    ("Olá: café, açúcar e pão.", "ola cafe acucar e pao"),
    ("ac\u0327a\u0303o", "acao"),
    ("Arquivo_2  versão 10", "arquivo_2  versao 10"),
    ("", ""),
])
def test_normalizar(texto, esperado):
    assert normalizar(texto) == esperado


@pytest.mark.parametrize("texto, esperado", [
    ("# Título\n**negrito** e _itálico_ com `código`", "Título negrito e itálico com código"),
    ("Antes\n```python\nprint('segredo')\n```\nDepois", "Antes Depois"),
    ("Veja [a documentação](https://exemplo.com/docs).", "Veja a documentação."),
    ("> Uma citação\n---\n| coluna | valor |", "Uma citação coluna valor"),
    ("Abra https://exemplo.com e http://exemplo.org/pagina", "Abra link e link"),
    ("  Texto\n\n com\t espaços.  ", "Texto com espaços."),
    ("", ""),
])
def test_texto_para_fala(texto, esperado):
    assert texto_para_fala(texto) == esperado


def test_texto_para_fala_preserva_limite_exato():
    texto = "a" * 700
    assert texto_para_fala(texto) == texto


def test_texto_para_fala_corta_texto_acima_do_limite():
    texto = "a" * 701
    assert texto_para_fala(texto) == "a" * 700 + " Os detalhes estão na tela."


def test_texto_para_fala_corta_no_fim_da_frase():
    frase = "a" * 250 + "."
    texto = frase + " " + "b" * 500
    assert texto_para_fala(texto) == frase + " Os detalhes estão na tela."


@pytest.mark.parametrize("texto, comando", [
    ("Secretário, abre", "abre"),
    ("secretaria abre", "abre"),
    ("SECRETARIO: x", "x"),
])
def test_ativacao_reconhece_palavra_e_separador(texto, comando):
    achou = ATIVACAO.search(texto)
    assert achou is not None
    assert texto[achou.end():] == comando


@pytest.mark.parametrize("texto", ["secretariado", "secretariado abre", "subsecretario abre"])
def test_ativacao_nao_reconhece_parte_de_palavra(texto):
    assert ATIVACAO.search(texto) is None
