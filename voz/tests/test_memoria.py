"""Memória em cofres temporários, sem carregar as dependências de áudio."""

import importlib.util
import json
import re
import sys
import types
import unicodedata
from pathlib import Path

import pytest


@pytest.fixture
def memoria(monkeypatch):
    def normalizar_falso(texto):
        texto = unicodedata.normalize("NFD", texto)
        texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
        return re.sub(r"[^\w\s]", "", texto.lower()).strip()

    monkeypatch.setitem(sys.modules, "comum", types.SimpleNamespace(normalizar=normalizar_falso))
    caminho = Path(__file__).resolve().parents[1] / "memoria.py"
    spec = importlib.util.spec_from_file_location("memoria_t8", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def escrever(cofre, caminho, texto):
    destino = cofre / caminho
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    return destino


@pytest.fixture
def cofre(tmp_path, memoria):
    memoria.preparar_cofre(tmp_path)
    escrever(tmp_path, "Conceitos/Jesus Cristo.md", '''---
tipo: conceito
assunto: "[[Religião]]"
aliases: [Jesus, "Cristo"]
---
# Jesus Cristo

Figura central do cristianismo.

## Relacionados
- [[Bíblia|Escrituras]]
''')
    escrever(tmp_path, "Conceitos/Bíblia.md", '''---
tipo: conceito
assunto: '[[Religião]]'
aliases:
  - Escrituras
  - "Livro Sagrado"
---
# Bíblia

Conjunto de textos religiosos.
''')
    return tmp_path


def test_preparar_cofre_idempotente(tmp_path, memoria):
    memoria.preparar_cofre(tmp_path)
    hub = tmp_path / "Assuntos" / "Religião.md"
    original = hub.read_text(encoding="utf-8")
    assert "tipo: assunto" in original
    assert "## Conceitos" in original
    hub.write_text(original + "\nAnotação pessoal.\n", encoding="utf-8")
    antes = {p: p.read_bytes() for p in tmp_path.rglob("*.md")}
    memoria.preparar_cofre(tmp_path)
    assert antes == {p: p.read_bytes() for p in tmp_path.rglob("*.md")}
    assert {p.stem for p in (tmp_path / "Assuntos").glob("*.md")} == set(memoria.ASSUNTOS)
    assert (tmp_path / "Conceitos").is_dir()
    assert (tmp_path / ".secretario").is_dir()


def test_ler_nota_listas_links_e_resumo(cofre, memoria):
    jesus = memoria.ler_nota(cofre / "Conceitos/Jesus Cristo.md")
    biblia = memoria.ler_nota(cofre / "Conceitos/Bíblia.md")
    assert jesus["titulo"] == "Jesus Cristo"
    assert jesus["frontmatter"]["aliases"] == ["Jesus", "Cristo"]
    assert jesus["frontmatter"]["assunto"] == "[[Religião]]"
    assert biblia["frontmatter"]["aliases"] == ["Escrituras", "Livro Sagrado"]
    assert jesus["links"] == ["Religião", "Bíblia"]
    assert jesus["resumo"] == "Figura central do cristianismo."


def test_ler_nota_sem_frontmatter_e_resumo_limitado(tmp_path, memoria):
    caminho = escrever(tmp_path, "Nota.md", "# Título\n\n" + "a" * 220 +
                       "\ncontinuação\n\nOutro parágrafo. [[Alvo]] [[Alvo|nome]]")
    nota = memoria.ler_nota(caminho)
    assert nota["titulo"] == "Nota"
    assert nota["frontmatter"] == {}
    assert nota["resumo"] == "a" * 200
    assert nota["links"] == ["Alvo"]


def test_indexar_exclui_modelos_e_pastas_ocultas(cofre, memoria):
    for pasta in ("Modelos", ".oculta", "Conceitos/.interna", "Pasta/Modelos"):
        escrever(cofre, f"{pasta}/Ignorada.md", "# Ignorada\n\nNão indexar.")
    indice = memoria.indexar(cofre)
    assert all(nota["titulo"] != "Ignorada" for nota in indice["notas"])
    assert indice["termos"]["jesus"] == ["Conceitos/Jesus Cristo.md"]
    assert indice["termos"]["biblia"] == ["Conceitos/Bíblia.md"]
    nota = next(n for n in indice["notas"] if n["titulo"] == "Jesus Cristo")
    assert nota["assunto"] == "Religião"
    assert json.loads((cofre / ".secretario/indice.json").read_text(encoding="utf-8")) == indice


def test_buscar_encontra_conceitos_e_hub(cofre, memoria):
    notas = memoria.buscar("o que a bíblia fala de jesus", cofre)
    assert {n["titulo"] for n in notas} == {"Jesus Cristo", "Bíblia", "Religião"}
    assert all(n["pontos"] > 0 for n in notas)
    assert [n["pontos"] for n in notas] == sorted((n["pontos"] for n in notas), reverse=True)
    assert len(memoria.buscar("Jesus", cofre, limite=1)) == 1
    assert memoria.buscar("Jesus", cofre, limite=0) == []


def test_buscar_sem_relacao_e_palavras_inteiras(cofre, memoria):
    assert memoria.buscar("astronautas exploram satélites", cofre) == []
    assert memoria.buscar("jesusinho bibliografia", cofre) == []
    assert memoria.contexto("astronautas exploram satélites", cofre) == ""


def test_pontuacao_e_expansao_de_um_salto(tmp_path, memoria):
    escrever(tmp_path, "Conceitos/Primeiro.md", "# Primeiro\n\nResumo.\n\n- [[Segundo]]")
    escrever(tmp_path, "Conceitos/Segundo.md", "# Segundo\n\nResumo.\n\n- [[Terceiro]]")
    escrever(tmp_path, "Conceitos/Terceiro.md", "# Terceiro\n\nResumo.")
    notas = memoria.buscar("primeiro", tmp_path)
    assert [(n["titulo"], n["pontos"]) for n in notas] == [("Primeiro", 4), ("Segundo", 2)]


def test_buscar_aproveita_indice(cofre, memoria, monkeypatch):
    memoria.indexar(cofre)

    def nao_indexar(*args):
        raise AssertionError("O índice existente deve ser reutilizado")

    monkeypatch.setattr(memoria, "indexar", nao_indexar)
    assert memoria.buscar("ESCRITURAS", cofre)


def test_contexto_respeita_limite(cofre, memoria):
    completo = memoria.contexto("Jesus", cofre)
    assert completo.startswith("Memória relevante (cofre Obsidian):\n")
    assert "Jesus Cristo [Religião]: Figura central do cristianismo." in completo
    assert "Ligado a: Religião, Bíblia" in completo
    for limite in (0, 1, 40, 1200):
        assert memoria.contexto("Jesus", cofre, max_chars=limite) == completo[:limite]
