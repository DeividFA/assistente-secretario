"""Distribuição sem motores, dispositivos ou banco reais."""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assistente_voz as motor


@pytest.mark.parametrize('preferido,ocupacao,disponiveis,ordem,esperado', [
    ('claude', {}, {'claude', 'codex'}, ['codex'], 'claude'),
    ('claude', {'claude': 2}, {'claude', 'codex'}, ['codex'], 'codex'),
    ('claude', {}, {'gemma'}, ['codex', 'gemma'], 'gemma'),
    ('claude', {'claude': 2, 'codex': 1}, {'claude', 'codex'}, ['codex'], None),
    ('gemma', {'gemma': 1}, {'gemma'}, ['gemma'], None),
    ('gpt', {'gpt': 1, 'grok': 2}, {'gpt', 'grok'}, ['grok'], 'gpt'),
    ('gpt', {'gpt': 2}, {'gpt', 'grok'}, ['grok'], 'grok'),
    ('qwen', {}, {'qwen'}, [], None),
])
def test_escolher_motor(preferido, ocupacao, disponiveis, ordem, esperado):
    vagas = dict(motor.config.PADROES['vagas'], gemma=5)
    antes = (ocupacao.copy(), disponiveis.copy(), ordem[:], vagas.copy())
    assert motor.escolher_motor(preferido, ocupacao, disponiveis, ordem, vagas) == esperado
    assert (ocupacao, disponiveis, ordem, vagas) == antes


@pytest.mark.parametrize('reparando,dependente', [(False, False), (True, False), (False, True)])
def test_despachante_com_tarefas_falsas(tmp_path, monkeypatch, reparando, dependente):
    banco = tmp_path / 'fila.db'
    for numero in range(5):
        motor.fila.adicionar(f'pedido {numero}', prioridade=numero % 4,
                             motor='gemma', banco=banco)
    listar = motor.fila.listar
    monkeypatch.setattr(motor.fila, 'BANCO', banco)
    def pendentes():
        tarefas = listar(banco=banco)
        if dependente:
            for tarefa in tarefas:
                if tarefa['id'] == 2:
                    tarefa['depende_sessao'] = True
        return tarefas

    monkeypatch.setattr(motor.fila, 'listar', pendentes)
    monkeypatch.setattr(motor.provedores, 'disponivel', lambda nome: (True, ''))
    eventos, iniciadas = [], []
    monkeypatch.setattr(motor, 'emitir', lambda **evento: eventos.append(evento))
    assistente = motor.Assistente.__new__(motor.Assistente)
    assistente.ativo = True
    assistente.reparando = reparando
    assistente.motor = 'claude'
    assistente.sessao = 'sessao-original'
    assistente.trabalhos = {}
    assistente.trava = threading.RLock()
    assistente.config_mic = motor.config.PADROES.copy()
    assistente.acordar = SimpleNamespace(clear=lambda: None,
                                        wait=lambda _: setattr(assistente, 'ativo', False))
    # O primeiro pedido veio do celular; recebe as mesmas vagas.
    assistente.ponte = SimpleNamespace(origem=lambda id: 'telefone' if id == 1 else None)
    assistente.emitir_fila = lambda: motor.emitir(evento='fila', tarefas=listar(banco=banco))

    class Thread:
        def __init__(self, target, args, daemon):
            self.trabalho = args[0]

        def start(self):
            iniciadas.append(self.trabalho)

    monkeypatch.setattr(motor.threading, 'Thread', Thread)
    assistente.despachar()
    if reparando:
        assert iniciadas == []
        assert all(t['status'] == 'pendente' for t in listar(banco=banco))
        return
    assert [t['id'] for t in iniciadas] == ([1, 5, 3, 4] if dependente else [1, 5, 2, 3])
    assert [t['motor'] for t in iniciadas] == ['claude', 'claude', 'codex', 'gemma']
    assert iniciadas[0]['origem'] == 'celular'
    assert iniciadas[2]['derivada'] and iniciadas[2]['sessao'] == 'sessao-original'
    assert all(t['simultanea'] for t in iniciadas)
    assert len([t for t in listar(banco=banco) if t['status'] == 'pendente']) == 1
    assert {t['motor'] for t in eventos[-1]['tarefas'] if t['status'] == 'rodando'} == {
        'claude', 'codex', 'gemma'}


def test_gemma_escolhido_nunca_transborda_para_a_nuvem():
    from assistente_voz import escolher_motor
    vagas = {"claude": 2, "codex": 1, "gemma": 1}
    disponiveis = {"claude", "codex", "gemma"}
    assert escolher_motor("gemma", {}, disponiveis, ["claude", "codex", "gemma"], vagas) == "gemma"
    assert escolher_motor("gemma", {"gemma": 1}, disponiveis, ["claude", "codex", "gemma"], vagas) is None
