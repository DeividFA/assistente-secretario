"""Integração da memória com motores falsos, sem cofre, rede ou áudio reais."""

import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assistente_voz as motor
import extrator as extrator_real


@pytest.fixture
def ambiente(monkeypatch):
    chamadas, eventos, threads = [], [], []
    conhecimento = {"conceitos": [], "fatos_usuario": ["Deivid é programador."]}
    memoria = SimpleNamespace(
        preparar_cofre=lambda: chamadas.append(("preparar",)),
        indexar=lambda: chamadas.append(("indexar",)),
        contexto=lambda texto: chamadas.append(("contexto", texto)) or "Contexto relevante",
        registrar_diario=lambda *args: chamadas.append(("diario", *args)),
        aprender=lambda dados: chamadas.append(("aprender", dados)) or ["Perfil/Aprendizados.md"])
    extrator = SimpleNamespace(extrair=lambda *args: chamadas.append(("extrair", *args)) or conhecimento)

    class Thread:
        def __init__(self, target, daemon):
            assert daemon is True
            self.target = target

        def start(self):
            threads.append(self)

    monkeypatch.setattr(motor, "memoria", memoria)
    monkeypatch.setattr(motor, "extrator", extrator)
    monkeypatch.setattr(motor.threading, "Thread", Thread)
    monkeypatch.setattr(motor, "emitir", lambda **evento: eventos.append(evento))
    monkeypatch.setattr(motor, "registrar", lambda *args: chamadas.append(("log", *args)))
    monkeypatch.setattr(motor.registro, "inicio_tarefa",
                        lambda *args: chamadas.append(("inicio", *args)) or 1)
    monkeypatch.setattr(motor.registro, "fim_tarefa", lambda *args: None)
    assistente = motor.Assistente.__new__(motor.Assistente)
    assistente.trava = threading.RLock()
    assistente.ativo = True
    assistente.sessao = None
    assistente.sessoes_cli = {}
    assistente.historicos_api = {}
    assistente.pendentes_api = {}
    assistente.estado = lambda estado: None
    assistente.mensagem = lambda *args: None
    assistente.dizer = lambda texto: chamadas.append(("fala", texto))
    monkeypatch.setattr(motor._contexto, "trabalho", {}, raising=False)
    return SimpleNamespace(assistente=assistente, chamadas=chamadas, eventos=eventos,
                           threads=threads, memoria=memoria, conhecimento=conhecimento)


def test_preparar_memoria(ambiente):
    ambiente.assistente.preparar_memoria()
    assert ambiente.chamadas == [("preparar",), ("indexar",)]


@pytest.mark.parametrize("etapa", ["preparar_cofre", "indexar"])
def test_falha_inicializacao_so_registra(ambiente, monkeypatch, etapa):
    def falhar():
        raise OSError("cofre indisponível")
    monkeypatch.setattr(ambiente.memoria, etapa, falhar)
    ambiente.assistente.preparar_memoria()
    assert ambiente.chamadas[-1] == ("log", "ERRO", "Inicialização da memória: cofre indisponível")
    assert not ambiente.eventos


@pytest.mark.parametrize("nome", list(motor.provedores.MOTORES))
def test_respostas_de_todos_motores(ambiente, monkeypatch, nome):
    pedido, resposta = "Eu trabalho como programador.", "Entendido, Deivid."
    trabalho = dict(motor=nome, cancelado=False, derivada=False, sessao=None, proc=None)
    monkeypatch.setattr(motor._contexto, "trabalho", trabalho)

    def executar_cli(nome_motor, texto, ao_evento, **opcoes):
        assert texto == "Contexto relevante\n\nPedido: " + pedido
        return {"resposta": resposta, "sessao": None}

    def executar_api(texto, historico, memoria, chamar):
        assert texto == pedido
        assert memoria == "Contexto relevante"
        return {"texto": resposta, "passos": [], "pendente": None}

    class Processo:
        stdout = [json.dumps({"type": "result", "result": resposta})]
        returncode = 0

        def wait(self):
            return 0

        def poll(self):
            return 0

    def abrir(args, **opcoes):
        assert args[args.index("-p") + 1] == "Contexto relevante\n\nPedido: " + pedido
        return Processo()

    monkeypatch.setattr(motor.motores_cli, "executar", executar_cli)
    monkeypatch.setattr(motor.motores_cli, "resolver_executavel", lambda _: ["claude"])
    monkeypatch.setattr(motor.agente_local, "executar", executar_api)
    monkeypatch.setattr(motor.subprocess, "Popen", abrir)
    ambiente.assistente.tarefa(pedido)
    assert ambiente.chamadas == [("contexto", pedido), ("inicio", pedido, nome), ("fala", resposta)]
    assert len(ambiente.threads) == 1  # fala enfileirada antes de executar o aprendizado
    ambiente.threads[0].target()
    assert ambiente.chamadas[-3:] == [
        ("diario", pedido, resposta), ("extrair", pedido, resposta),
        ("aprender", ambiente.conhecimento)]
    assert ambiente.eventos == [{"evento": "memoria", "notas": ["Perfil/Aprendizados.md"]}]


def test_sem_mudancas_nao_emite_memoria(ambiente, monkeypatch):
    vazio = {"conceitos": [], "fatos_usuario": []}
    monkeypatch.setattr(motor.extrator, "extrair", lambda *args: vazio)
    recebidos = []
    monkeypatch.setattr(ambiente.memoria, "aprender", lambda dados: recebidos.append(dados) or [])
    ambiente.assistente.aprender_resposta("abre a calculadora", "Pronto.")
    ambiente.threads[0].target()
    assert recebidos == [vazio]  # respeita o resultado filtrado pelo extrator
    assert not ambiente.eventos


@pytest.mark.parametrize("etapa", ["registrar_diario", "extrair", "aprender"])
def test_falha_aprendizado_so_registra(ambiente, monkeypatch, etapa):
    def falhar(*args):
        raise OSError("falha simulada")
    modulo = motor.extrator if etapa == "extrair" else ambiente.memoria
    monkeypatch.setattr(modulo, etapa, falhar)
    ambiente.assistente.aprender_resposta("pedido", "resposta")
    ambiente.threads[0].target()
    assert ambiente.chamadas[-1] == ("log", "ERRO", "Aprendizado da memória: falha simulada")
    assert not ambiente.eventos


@pytest.mark.parametrize("pedido, fatos, esperados", [
    ("abre a calculadora", ["Deivid é programador."], []),
    ("Eu trabalho como programador.",
     ["Deivid pediu para abrir a calculadora.", "Deivid é programador."],
     ["Deivid é programador."]),
])
def test_integracao_respeita_filtros(ambiente, monkeypatch, pedido, fatos, esperados):
    chamadas_modelo, aprendidos = [], []

    def chamar(mensagens):
        chamadas_modelo.append(mensagens)
        return json.dumps({"conceitos": [], "fatos_usuario": fatos})

    monkeypatch.setattr(extrator_real, "_chamar", chamar)
    monkeypatch.setattr(motor, "extrator", extrator_real)
    monkeypatch.setattr(ambiente.memoria, "aprender", lambda dados: aprendidos.append(dados) or [])
    ambiente.assistente.aprender_resposta(pedido, "Entendido.")
    ambiente.threads[0].target()
    assert aprendidos == [{"conceitos": [], "fatos_usuario": esperados}]
    assert bool(chamadas_modelo) is not extrator_real.comando_operacional(pedido)
    assert ambiente.chamadas[0] == ("diario", pedido, "Entendido.")


def test_busca_singular_plural_e_resumo(tmp_path):
    import memoria
    memoria.preparar_cofre(tmp_path)
    (tmp_path / "Conceitos" / "Bíblia.md").write_text(
        "---\nassunto: Religião\n---\n# Bíblia\n\nLida aos domingos de manhã.\n", encoding="utf-8")
    (tmp_path / "Inscrições.md").write_text(
        "# Inscrições\n\n| Data | Nota |\n|---|---|\n", encoding="utf-8")
    memoria.indexar(tmp_path)
    assert "Bíblia" in memoria.contexto("o que eu faço no domingo?", cofre=tmp_path)
    # Linha de tabela não vira resumo, então "notas" não puxa a nota Inscrições.
    assert "Inscrições" not in memoria.contexto("abre o bloco de notas", cofre=tmp_path)
