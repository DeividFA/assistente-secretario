"""Git real somente em tmp_path; Codex, backup e verificações sempre falsos."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnostico
import registro
import reparo


def git(repo, *args):
    return subprocess.run(['git', '-c', 'core.hooksPath=NUL', *args], cwd=repo,
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def ambiente(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-b', 'main')
    git(repo, 'config', 'user.name', 'Teste')
    git(repo, 'config', 'user.email', 'teste@example.invalid')
    git(repo, 'config', 'commit.gpgsign', 'false')
    git(repo, 'config', 'core.hooksPath', str(tmp_path / 'sem-hooks'))
    (repo / 'codigo.py').write_text('valor = 0\n', encoding='utf-8')
    (repo / 'voz' / 'tests').mkdir(parents=True)
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'Inicial')
    banco = tmp_path / 'bugs.db'
    id = diagnostico.registrar_bug('teste', ValueError('valor errado'), banco=banco)
    return repo, banco, id


def executor(nome, pedido, ao_evento, pasta):
    assert nome == 'codex'
    assert 'Não faça commit' in pedido
    (pasta / 'codigo.py').write_text('valor = 1\n', encoding='utf-8')
    (pasta / 'voz' / 'tests' / 'test_valor.py').write_text('def test_valor():\n    assert True\n')
    return {'resposta': 'Corrigido'}


def executar(ambiente, **opcoes):
    repo, banco, id = ambiente
    return reparo.executar(id, 'Só o valor.', repo=repo, banco=banco, executor=executor,
                          fazer_backup=lambda motivo: None, **opcoes)


def test_sucesso_commit_main(ambiente):
    repo, banco, id = ambiente
    ordem = []
    resultado = reparo.executar(id, aprovado=True, repo=repo, banco=banco, executor=executor,
                              fazer_backup=lambda motivo: ordem.append(motivo),
                              testar=lambda pasta: ordem.append('testes'))
    assert resultado['ok']
    assert ordem == ['antes_reparo', 'testes']
    assert git(repo, 'branch', '--show-current') == 'main'
    assert git(repo, 'rev-parse', 'HEAD') == resultado['commit']
    assert registro.detalhe_bug(id, banco)['estado'] == 'corrigido'


def test_falha_main_intacta_branch_apagado(ambiente):
    repo, banco, id = ambiente
    antes = git(repo, 'rev-parse', 'HEAD')
    def falhar(pasta):
        raise RuntimeError('Teste falhou')
    for _ in range(2):
        assert not executar(ambiente, aprovado=True, testar=falhar)['ok']
        assert git(repo, 'branch', '--show-current') == 'main'
        assert git(repo, 'rev-parse', 'HEAD') == antes
        assert not git(repo, 'branch', '--list', f'reparo/{id}')
        assert not git(repo, 'status', '--porcelain')
    assert registro.detalhe_bug(id, banco)['tentativas'] == 2
    assert not executar(ambiente, aprovado=True, testar=lambda pasta: None)['ok']


def test_sujo_recusa_sem_alterar(ambiente):
    repo, banco, id = ambiente
    (repo / 'pessoal.txt').write_text('preservar')
    assert not executar(ambiente, aprovado=True, testar=lambda pasta: None)['ok']
    assert (repo / 'pessoal.txt').read_text() == 'preservar'
    assert registro.detalhe_bug(id, banco)['tentativas'] == 0


def test_sem_aprovacao_nao_executa(ambiente):
    assert not executar(ambiente, testar=lambda pasta: pytest.fail('Não deveria testar'))['ok']


def test_outro_reparo_recusa(ambiente):
    reparo._trava.acquire()
    try:
        assert not executar(ambiente, aprovado=True, testar=lambda pasta: None)['ok']
    finally:
        reparo._trava.release()
