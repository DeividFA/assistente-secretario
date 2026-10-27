import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
import padrao_fala
import vocabulario


def test_filtro_pronuncia(monkeypatch):
    pares = []
    monkeypatch.setattr(vocabulario, 'aprender_correcao', lambda *p: pares.append(p))
    assert not padrao_fala.aprender_pronuncia('link', 'LinkedIn')
    assert not padrao_fala.aprender_pronuncia('gemas', 'Gemma')
    assert padrao_fala.aprender_pronuncia('linketim', 'LinkedIn')
    assert padrao_fala.aprender_pronuncia('meu link', 'meu LinkedIn')
    assert len(pares) == 2


def test_resumo_nota_e_privacidade(tmp_path):
    banco = tmp_path / 'fala.db'
    cofre = tmp_path / 'cofre'
    texto = 'Hoje quero pesquisar astronomia com telescópio'
    for _ in range(2):
        padrao_fala.registrar_fala(texto, [{'palavra': 'telescópio', 'prob': .3}],
                                   [.2, .8], banco=banco, cofre=cofre)
    padrao_fala.registrar_correcao('telescopio', 'Telescópio', banco)
    padrao_fala.registrar_correcao(texto, 'uma frase inteira que não deve ir para o cofre', banco)
    dados = padrao_fala.resumo(banco)
    assert ('astronomia', 2) in dados['palavras']
    assert dados['pausa_p90'] == .8
    assert dados['correcoes']
    padrao_fala.atualizar_nota(cofre, banco)
    nota = (cofre / 'Perfil' / 'Fala.md').read_text(encoding='utf-8')
    assert 'astronomia: 2' in nota
    assert 'telescopio → Telescópio' in nota
    assert texto not in nota
    assert 'uma frase inteira' not in nota


def test_pausa_limites_e_config_preservado(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'BASE', tmp_path)
    arquivo = tmp_path / 'config.json'
    original = {'pausa_auto': False, 'pausa_fala': 1.4, 'extra': {'x': 42}}
    arquivo.write_text(json.dumps(original), encoding='utf-8')
    padrao_fala.ajustar_pausa(2)
    assert json.loads(arquivo.read_text()) == original
    original['pausa_auto'] = True
    arquivo.write_text(json.dumps(original), encoding='utf-8')
    padrao_fala.ajustar_pausa(9)
    dados = json.loads(arquivo.read_text())
    assert dados['extra'] == {'x': 42}
    assert dados['pausa_fala'] == 2.2
    assert padrao_fala.pausa_adaptativa(0) == 1.0
    assert padrao_fala.pausa_adaptativa(1) == 1.3


def test_escolha_idioma():
    chamadas = []
    def transcrever(idioma):
        chamadas.append(idioma)
        return {'texto': 'hello' if idioma is None else 'alô', 'palavras': [],
                'idioma': idioma or 'en', 'prob_idioma': .9 if idioma is None else .3}
    assert padrao_fala.escolher_idioma(transcrever, ['pt'])['idioma'] == 'pt'
    assert chamadas == ['pt']
    chamadas.clear()
    assert padrao_fala.escolher_idioma(transcrever, ['pt', 'en'])['idioma'] == 'en'
    assert chamadas == ['pt', None]
    assert padrao_fala.escolher_idioma(transcrever, ['pt', 'es'])['idioma'] == 'pt'


def test_cadencia(tmp_path, monkeypatch):
    ajustes = []
    notas = []
    monkeypatch.setattr(config, 'carregar', lambda: {'pausa_auto': True})
    monkeypatch.setattr(padrao_fala, 'ajustar_pausa', ajustes.append)
    original = padrao_fala.atualizar_nota
    def atualizar(cofre, banco):
        notas.append(True)
        original(cofre, banco)
    monkeypatch.setattr(padrao_fala, 'atualizar_nota', atualizar)
    for _ in range(50):
        padrao_fala.registrar_fala('astronomia', [], [.6],
                                   banco=tmp_path / 'fala.db', cofre=tmp_path / 'cofre')
    assert ajustes == [.6]
    assert len(notas) == 2


def test_termos_do_vocabulario_nao_sao_duvidosos():
    import padrao_fala
    palavras = [{"palavra": "LinkedIn", "prob": 0.01}, {"palavra": "Gemma.", "prob": 0.03},
                {"palavra": "abriu", "prob": 0.3}, {"palavra": "meu", "prob": 0.9}]
    assert padrao_fala.duvidosas(palavras, ["LinkedIn", "Gemma"]) == ["abriu"]


def test_palavras_calibracao_filtra_titulos_ruins(tmp_path):
    import json, padrao_fala, vocabulario
    (tmp_path / '.secretario').mkdir()
    titulos = ['00 - Índice', 'LinkedIn carrossel - 2026-10-27', 'Bíblia', 'Casa', 'Montes Claros',
               'Uma frase longa demais aqui']
    (tmp_path / '.secretario' / 'indice.json').write_text(
        json.dumps({'notas': [{'titulo': t} for t in titulos]}), encoding='utf-8')
    extras = padrao_fala.palavras_calibracao(tmp_path)[len(vocabulario.FIXOS):]
    assert extras == ['Bíblia', 'Montes Claros']


def test_calibracao_registra_data_e_preserva_nota(tmp_path):
    import padrao_fala
    (tmp_path / 'Perfil').mkdir()
    (tmp_path / 'Perfil' / 'Fala.md').write_text('# Fala\n\n- LinkedIn\n\nÚltima calibração: antiga\n', encoding='utf-8')
    padrao_fala.registrar_calibracao(tmp_path)
    texto = (tmp_path / 'Perfil' / 'Fala.md').read_text(encoding='utf-8')
    assert '- LinkedIn' in texto and 'antiga' not in texto and texto.count('Última calibração:') == 1


def test_pausa_da_calibracao_grava_mesmo_sem_pausa_auto(tmp_path, monkeypatch):
    import json, config, padrao_fala
    monkeypatch.setattr(config, 'BASE', tmp_path)
    (tmp_path / 'config.json').write_text(json.dumps({'pausa_auto': False, 'voz': 'windows'}), encoding='utf-8')
    assert padrao_fala.ajustar_pausa(1.5) is None
    assert padrao_fala.ajustar_pausa(1.5, calibracao=True) == 1.8
    dados = json.loads((tmp_path / 'config.json').read_text(encoding='utf-8'))
    assert dados['pausa_fala'] == 1.8 and dados['voz'] == 'windows'
