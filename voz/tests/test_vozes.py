"""Vozes com rede, síntese e reprodução falsas."""

import io
import json
import queue
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
import vozes
import falar_proc


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(vozes, "pasta_modelos", lambda: tmp_path)
    return tmp_path


def rede_falsa(monkeypatch, configuracao=b'{"audio":{"sample_rate":22050}}'):
    chamadas = []

    def abrir(url, timeout):
        chamadas.append(url)
        dados = configuracao if url.endswith(".json") else b'x' * 140000
        resposta = io.BytesIO(dados)
        resposta.headers = {"Content-Length": str(len(dados))}
        return resposta

    monkeypatch.setattr(vozes.urllib.request, "urlopen", abrir)
    return chamadas


def test_catalogo_urls():
    assert len(vozes.CATALOGO) == 10
    assert len({v['id'] for v in vozes.CATALOGO}) == 10
    assert vozes.urls('piper:pt_BR-faber-medium')[0].endswith(
        '/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx')
    assert 'tug%C3%A3o' in vozes.urls('piper:pt_PT-tugão-medium')[0]
    for voz in vozes.CATALOGO:
        assert {'id', 'nome', 'tipo', 'idioma', 'tamanho', 'online'} <= voz.keys()
    with pytest.raises(ValueError):
        vozes.urls('https://exemplo/voz.onnx')


def test_baixar_listar_remover(pasta, monkeypatch):
    chamadas = rede_falsa(monkeypatch)
    id = 'piper:pt_BR-faber-medium'
    eventos = []

    def progresso(feito, total):
        assert (pasta / 'pt_BR-faber-medium.onnx.part').exists()
        assert not vozes.caminhos(id)[0].exists()
        eventos.append((feito, total))

    assert not next(v for v in vozes.listar() if v['id'] == id)['instalada']
    vozes.baixar(id, progresso)
    assert len(chamadas) == 2
    assert len(eventos) > 2
    assert eventos[-1][0] == eventos[-1][1]
    assert all(a[0] <= b[0] for a, b in zip(eventos, eventos[1:]))
    assert next(v for v in vozes.listar() if v['id'] == id)['instalada']
    assert all(v['instalada'] for v in vozes.listar() if v['tipo'] != 'piper')
    assert not list(pasta.glob('*.part'))
    monkeypatch.setattr(vozes.config, 'carregar', lambda: {'voz': 'windows'})
    vozes.remover(id)
    assert not any(p.exists() for p in vozes.caminhos(id))


@pytest.mark.parametrize('dados', [b'invalido', b'[]'])
def test_json_invalido_preserva_arquivos(pasta, monkeypatch, dados):
    rede_falsa(monkeypatch, dados)
    id = 'piper:pt_BR-cadu-medium'
    for arquivo in vozes.caminhos(id):
        arquivo.write_bytes(b'anterior')
    with pytest.raises(ValueError):
        vozes.baixar(id)
    assert all(p.read_bytes() == b'anterior' for p in vozes.caminhos(id))
    assert not list(pasta.glob('*.part'))


def test_id_invalido_sem_rede(pasta, monkeypatch):
    chamadas = rede_falsa(monkeypatch)
    with pytest.raises(ValueError):
        vozes.baixar('../fora')
    assert chamadas == []


def test_velocidade():
    assert vozes.escala_piper(380) == .5
    assert vozes.escala_piper(95) == 2
    assert vozes.taxa_edge(190) == '+0%'
    assert vozes.taxa_edge(285) == '+50%'
    assert vozes.taxa_edge(95) == '-50%'


def test_piper_reutiliza_modelo(pasta, monkeypatch):
    cargas, escalas = [], []

    def sintetizar(texto, syn_config):
        escalas.append(syn_config.length_scale)
        yield SimpleNamespace(audio_float_array=np.array([.1, .2], dtype=np.float32))

    modelo = SimpleNamespace(config=SimpleNamespace(sample_rate=22050), synthesize=sintetizar)
    def carregar(*args, **kwargs):
        cargas.append(args)
        return modelo

    monkeypatch.setitem(sys.modules, 'piper', SimpleNamespace(
        PiperVoice=SimpleNamespace(load=carregar), SynthesisConfig=SimpleNamespace))
    monkeypatch.setattr(vozes, '_modelo_id', None)
    monkeypatch.setattr(vozes, '_modelo', None)
    for _ in range(2):
        audio, taxa = vozes.sintetizar('Olá.', 'piper:pt_BR-faber-medium', 380)
        assert audio.dtype == np.float32
        assert taxa == 22050
    assert len(cargas) == 1
    assert escalas == [.5, .5]


def test_edge_decodifica_mp3(monkeypatch):
    chamadas = []

    class Comunicador:
        def __init__(self, texto, voz, rate):
            chamadas.append((texto, voz, rate))

        async def stream(self):
            yield {'type': 'audio', 'data': b'mp3'}

    def decodificar(dados, **kwargs):
        assert dados == b'mp3'
        assert kwargs['output_format'] == 'float32'
        assert kwargs['nchannels'] == 1
        return SimpleNamespace(samples=[.1], sample_rate=24000)

    monkeypatch.setitem(sys.modules, 'edge_tts', SimpleNamespace(Communicate=Comunicador))
    monkeypatch.setitem(sys.modules, 'miniaudio', SimpleNamespace(
        decode=decodificar, SampleFormat=SimpleNamespace(FLOAT32='float32')))
    audio, taxa = vozes.sintetizar('Olá.', 'edge:pt-BR-AntonioNeural', 95)
    assert chamadas == [('Olá.', 'pt-BR-AntonioNeural', '-50%')]
    assert taxa == 24000 and audio.dtype == np.float32


def test_falha_volta_windows(monkeypatch, capsys):
    def falhar(*args):
        raise RuntimeError('sem internet')

    falas = []
    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace())
    monkeypatch.setattr(vozes, 'sintetizar', falhar)
    monkeypatch.setattr(falar_proc, 'falar_windows', lambda *args: falas.append(args))
    falar_proc.falar('Olá.', 'edge:pt-BR-FranciscaNeural', 190)
    assert falas == [('Olá.', 190)]
    assert 'sem internet' in capsys.readouterr().err


@pytest.mark.parametrize('texto,nome', [('usa a voz faber', 'faber'),
    ('troca a voz para cadu', 'cadu'), ('usa a voz maria', 'maria')])
def test_comando_voz(texto, nome):
    achou = vozes.TROCA_VOZ.fullmatch(texto)
    assert achou.group(1) == nome
    assert vozes.pelo_nome(nome)
    assert not vozes.TROCA_VOZ.fullmatch('explica como usa a voz faber')


def test_usar_preserva_config(pasta, monkeypatch):
    monkeypatch.setattr(vozes.config, 'BASE', pasta)
    monkeypatch.setattr(vozes.config, 'carregar', lambda: {'pasta_backup': 'backup', 'motor': 'codex'})
    vozes.usar('edge:pt-BR-AntonioNeural')
    dados = json.loads((pasta / 'config.json').read_text(encoding='utf-8'))
    assert dados['pasta_backup'] == 'backup' and dados['motor'] == 'codex'
    assert dados['voz'] == 'edge:pt-BR-AntonioNeural'
    with pytest.raises(ValueError):
        vozes.usar('piper:pt_BR-faber-medium')


def test_processo_persistente_interrupcao(monkeypatch):
    import comum

    class Saida:
        def __init__(self):
            self.linhas = queue.Queue()

        def __iter__(self):
            return self

        def __next__(self):
            linha = self.linhas.get(timeout=2)
            if linha is None:
                raise StopIteration
            return linha

        def close(self):
            pass

    processos = []

    class Processo:
        def __init__(self, *args, **kwargs):
            self.codigo = None
            self.stdout = Saida()
            self.pedidos = []
            self.stdin = SimpleNamespace(write=self.escrever, flush=lambda: None, close=lambda: None)
            processos.append(self)

        def escrever(self, linha):
            self.pedidos.append(json.loads(linha))

        def poll(self):
            return self.codigo

        def kill(self):
            self.codigo = -9
            self.stdout.linhas.put(None)

        def wait(self):
            return self.codigo

    monkeypatch.setattr(comum, '_processo_fala', None)
    monkeypatch.setattr(comum.subprocess, 'Popen', Processo)
    monkeypatch.setattr(comum.subprocess, 'CREATE_NO_WINDOW', 0, raising=False)
    monkeypatch.setattr(comum.config, 'carregar', lambda: {'voz': 'windows', 'velocidade_fala': 190})
    primeira = comum.falar('Primeira.', esperar=False)
    assert primeira.poll() is None
    processos[0].stdout.linhas.put('{"fim":true}\n')
    primeira.wait(2)
    assert primeira.poll() == 0 and processos[0].poll() is None
    segunda = comum.falar('Segunda.', esperar=False, voz='edge:pt-BR-AntonioNeural')
    assert len(processos) == 1
    primeira.kill()  # Uma fala concluída não interrompe a seguinte.
    assert segunda.poll() is None
    segunda.kill()
    segunda.wait(2)
    assert segunda.poll() == -9
    terceira = comum.falar('Terceira.', esperar=False)
    assert len(processos) == 2
    assert processos[0].pedidos[1]['voz'] == 'edge:pt-BR-AntonioNeural'
    comum.interromper_fala()
    terceira.wait(2)


def test_comando_pede_confirmacao_e_ativa_apos_download(pasta, monkeypatch):
    from assistente_voz import Assistente

    assistente = Assistente.__new__(Assistente)
    assistente.voz_pendente = None
    assistente.restauro_pendente = None
    assistente.banco_falho = False
    assistente.reparo_pendente = None
    assistente.reinicio_reparo = False
    falas, downloads = [], []
    assistente.dizer = falas.append
    assistente.mensagem = lambda *args: None
    assistente.baixar_voz = lambda id, ativar=False: downloads.append((id, ativar))
    assistente.executar('Troca a voz para Faber.')
    assert assistente.voz_pendente == 'piper:pt_BR-faber-medium'
    assert 'quer que eu baixe?' in falas[-1]
    assert not downloads
    assistente.executar('sim')
    assert downloads == [('piper:pt_BR-faber-medium', True)]
    assert assistente.voz_pendente is None
