"""Configuração e correção sem dispositivos nem arquivos reais."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assistente_voz as motor


@pytest.mark.parametrize('chave,valor', [
    ('motor_padrao', 'claude'), ('modelo_whisper', 'small'),
    ('transcricao', 'groq'), ('modo_microfone', 'sob_demanda'),
    ('mic_em_chamada', 'compartilhar'), ('pausa_auto', False),
    ('idiomas', ['pt', 'en']), ('pasta_backup_extra', None),
])
def test_config_aceita(chave, valor):
    motor.validar_config(chave, valor)


@pytest.mark.parametrize('chave,valor', [
    ('chave_api', 'segredo'), ('perfil_inicial', True), ('ponte_ativa', True),
    ('motor_padrao', 'inventado'), ('modelo_whisper', []),
    ('transcricao', 'nuvem'), ('modo_microfone', True),
    ('mic_em_chamada', 'outro'), ('pausa_auto', 1),
    ('idiomas', 'pt'), ('idiomas', []), ('idiomas', ['pt', 'pt']),
    ('idiomas', ['pt', 1]), ('idiomas', ['../../x']),
    ('pasta_backup', None), ('pasta_backup', '../fora'),
    ('pasta_backup_extra', ''), (None, 1), ([], 1),
])
def test_config_rejeita_sem_gravar(tmp_path, chave, valor):
    caminho = tmp_path / 'config.json'
    caminho.write_text('{"outra":42}', encoding='utf-8')
    with pytest.raises(ValueError):
        motor.salvar_config(chave, valor, caminho)
    assert caminho.read_text(encoding='utf-8') == '{"outra":42}'


def test_config_preserva_chaves(tmp_path):
    caminho = tmp_path / 'config.json'
    caminho.write_text('{"outra":{"x":42}}', encoding='utf-8')
    motor.salvar_config('pasta_backup', str(tmp_path), caminho)
    motor.salvar_config('pausa_auto', True, caminho)
    assert json.loads(caminho.read_text(encoding='utf-8')) == {
        'outra': {'x': 42}, 'pasta_backup': str(tmp_path), 'pausa_auto': True}


def test_config_falha_atomica(tmp_path, monkeypatch):
    caminho = tmp_path / 'config.json'
    caminho.write_text('{"outra":42}', encoding='utf-8')
    def falhar(*args):
        raise OSError('falha simulada')
    monkeypatch.setattr(motor.os, 'replace', falhar)
    with pytest.raises(OSError):
        motor.salvar_config('pausa_auto', False, caminho)
    assert caminho.read_text(encoding='utf-8') == '{"outra":42}'
    assert list(tmp_path.iterdir()) == [caminho]


@pytest.mark.parametrize('antes,depois,pares', [
    ('abre meu linketim agora', 'abre meu LinkedIn agora', [('linketim', 'LinkedIn')]),
    ('abre x e fecha y', 'abre X e fecha Y', [('x', 'X'), ('y', 'Y')]),
    ('igual', 'igual', []), ('abre agora', 'abre isso agora', []),
    ('abre isso agora', 'abre agora', []), ('', 'novo', []),
    ('um dois errado aqui fim', 'um dois correto ali fim', [('errado aqui', 'correto ali')]),
])
def test_diff(antes, depois, pares):
    assert motor.diff_correcao(antes, depois) == pares


def test_comando_correcao_usa_filtro_t31(monkeypatch):
    chamadas = []
    monkeypatch.setattr(motor.padrao_fala, 'aprender_pronuncia',
                        lambda a, b: chamadas.append((a, b)) or False)
    monkeypatch.setattr(motor, 'emitir', lambda **ev: None)
    monkeypatch.setattr(motor.sys, 'stdin', [json.dumps({
        'cmd': 'correcao', 'errado': 'abre link', 'certo': 'abre LinkedIn'})])
    falso = SimpleNamespace(sair=lambda: None)
    motor.Assistente.ler_app(falso)
    assert chamadas == [('link', 'LinkedIn')]


def test_comando_config_valida_no_motor(tmp_path, monkeypatch):
    monkeypatch.setattr(motor, 'BASE', tmp_path)
    eventos = []
    monkeypatch.setattr(motor, 'emitir', lambda **ev: eventos.append(ev))
    comandos = [
        {'cmd': 'config', 'chave': 'pausa_auto', 'valor': False},
        {'cmd': 'config', 'chave': 'chave_api', 'valor': 'segredo'},
        {'cmd': 'config', 'chave': 'pausa_auto', 'valor': 1},
    ]
    monkeypatch.setattr(motor.sys, 'stdin', [json.dumps(c) for c in comandos])
    falso = SimpleNamespace(config_mic={}, emitir_configuracoes=lambda: None, sair=lambda: None)
    motor.Assistente.ler_app(falso)
    assert json.loads((tmp_path / 'config.json').read_text(encoding='utf-8')) == {'pausa_auto': False}
    assert falso.config_mic == {'pausa_auto': False}
    assert len(eventos) == 2
    assert 'segredo' not in json.dumps(eventos)


def test_diff_rejeita_tipo_invalido():
    with pytest.raises(ValueError):
        motor.diff_correcao(None, 'texto')


def test_diff_respeita_palavra_comum_t31(monkeypatch):
    chamadas = []
    monkeypatch.setattr(motor.vocabulario, 'aprender_correcao', lambda a, b: chamadas.append((a, b)))
    for antes, depois in motor.diff_correcao('abre link', 'abre LinkedIn'):
        assert motor.padrao_fala.aprender_pronuncia(antes, depois) is False
    for antes, depois in motor.diff_correcao('abre linketim', 'abre LinkedIn'):
        assert motor.padrao_fala.aprender_pronuncia(antes, depois) is True
    assert chamadas == [('linketim', 'LinkedIn')]
