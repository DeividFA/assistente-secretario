"""Memória em cofres temporários, sem carregar as dependências de áudio."""

import importlib.util
import json
import re
import sys
import types
import unicodedata
from datetime import date, datetime
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


def test_aprender_cria_conceito_hub_e_indice(tmp_path, memoria):
    alterados = memoria.aprender({"conceitos": [{
        "nome": "jesus cristo", "assunto": "Religião", "resumo": "Figura central.",
        "aliases": ["Jesus"], "fato": "Conversamos sobre suas parábolas.",
    }]}, tmp_path, hoje=date(2026, 10, 20))
    caminho = tmp_path / "Conceitos/Jesus Cristo.md"
    nota = memoria.ler_nota(caminho)
    assert nota["resumo"] == "Figura central."
    assert nota["frontmatter"]["atualizado"] == "2026-10-20"
    assert "- 2026-10-20 — Conversamos sobre suas parábolas." in caminho.read_text(encoding="utf-8")
    hub = (tmp_path / "Assuntos/Religião.md").read_text(encoding="utf-8")
    assert "- [[Jesus Cristo]] — Figura central." in hub
    assert "Conceitos/Jesus Cristo.md" in alterados
    assert "Assuntos/Religião.md" in alterados
    assert memoria.buscar("Jesus", tmp_path)


def test_aprender_alias_preserva_resumo_e_deduplica(cofre, memoria):
    conhecimento = {"conceitos": [{
        "nome": "JESUS", "assunto": "Religião", "resumo": "Resumo substituto.",
        "aliases": ["Salvador", "cristo"], "relacionados": ["Escrituras", "BÍBLIA"],
        "fato": "Deivid leu as parábolas.",
    }], "fatos_usuario": ["Gosta de estudar.", "gosta de estudar."]}
    memoria.aprender(conhecimento, cofre, hoje=date(2026, 10, 20))
    conhecimento["conceitos"][0]["nome"] = "salvador"
    conhecimento["conceitos"][0]["aliases"] = ["Mestre"]
    memoria.aprender(conhecimento, cofre, hoje=date(2026, 10, 21))
    caminho = cofre / "Conceitos/Jesus Cristo.md"
    texto = caminho.read_text(encoding="utf-8")
    nota = memoria.ler_nota(caminho)
    assert {p.stem for p in (cofre / "Conceitos").glob("*.md")} == {"Jesus Cristo", "Bíblia"}
    assert nota["resumo"] == "Figura central do cristianismo."
    assert {memoria.normalizar(a) for a in nota["frontmatter"]["aliases"]} == {
        "jesus", "cristo", "salvador", "mestre"}
    assert nota["frontmatter"]["atualizado"] == "2026-10-21"
    assert texto.count("Deivid leu as parábolas.") == 1
    assert texto.count("[[Bíblia") == 1
    assert (cofre / "Assuntos/Religião.md").read_text(encoding="utf-8").count("[[Jesus Cristo]]") == 1
    perfil = (cofre / "Perfil/Aprendizados.md").read_text(encoding="utf-8")
    assert perfil.count("—") == 1
    assert "2026-10-20 — Gosta de estudar." in perfil


def test_aprender_relacionado_minimo_e_assunto_invalido(tmp_path, memoria):
    memoria.aprender({"conceitos": [{
        "nome": "Python", "assunto": "Inexistente", "resumo": "Uma linguagem.",
        "relacionados": ["programação", "PROGRAMAÇÃO"],
    }]}, tmp_path, hoje=date(2026, 10, 20))
    for nome in ("Python", "Programação"):
        nota = memoria.ler_nota(tmp_path / "Conceitos" / f"{nome}.md")
        assert nota["frontmatter"]["assunto"] == "[[Outros]]"
    texto = (tmp_path / "Conceitos/Python.md").read_text(encoding="utf-8")
    assert texto.count("- [[Programação]]") == 1
    hub = (tmp_path / "Assuntos/Outros.md").read_text(encoding="utf-8")
    assert "[[Python]]" in hub
    assert "[[Programação]]" in hub


def test_aprender_reindexa_e_retorna_so_alterados(cofre, memoria, monkeypatch):
    chamadas = []
    monkeypatch.setattr(memoria, "indexar", lambda destino: chamadas.append(destino))
    assert memoria.aprender({}, cofre, hoje=date(2026, 10, 20)) == []
    assert chamadas == [cofre]


def test_diario_acumula_e_limita_cada_lado(tmp_path, memoria):
    memoria.registrar_diario("Pergunta\nem duas linhas", "Resposta", tmp_path,
                             agora=datetime(2026, 10, 20, 9, 5))
    memoria.registrar_diario("p" * 350, "r" * 350, tmp_path,
                             agora=datetime(2026, 10, 20, 10, 15))
    linhas = (tmp_path / "Diário/2026-10-20.md").read_text(encoding="utf-8").splitlines()
    assert linhas[0] == "# 2026-10-20"
    assert linhas[2] == "- 09:05 — **Você:** Pergunta em duas linhas → **Secretário:** Resposta"
    assert linhas[3] == "- 10:15 — **Você:** " + "p" * 300 + " → **Secretário:** " + "r" * 300
    assert len(list((tmp_path / "Diário").glob("*.md"))) == 1
