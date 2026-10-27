"""Catálogo, download e síntese das vozes de resposta."""

import asyncio
import json
import re
import threading
import unicodedata
import urllib.request
from pathlib import Path
from contextlib import ExitStack
from urllib.parse import quote

import config

CATALOGO = [{"id": "windows", "nome": "Windows / Maria", "tipo": "windows",
             "idioma": "pt-BR", "tamanho": 0, "online": False}]
for modelo in ("pt_BR-faber-medium", "pt_BR-cadu-medium", "pt_BR-jeff-medium",
               "pt_BR-edresson-low", "pt_PT-tugão-medium", "en_US-amy-medium"):
    local, nome, qualidade = modelo.split("-")
    CATALOGO.append({"id": "piper:" + modelo, "nome": nome.capitalize(), "tipo": "piper",
                     "idioma": local.replace("_", "-"),
                     "tamanho": 20 if qualidade == "low" else 63, "online": False})
for nome in ("FranciscaNeural", "AntonioNeural", "ThalitaMultilingualNeural"):
    CATALOGO.append({"id": "edge:pt-BR-" + nome,
                     "nome": nome.replace("MultilingualNeural", "").replace("Neural", ""),
                     "tipo": "edge", "idioma": "pt-BR", "tamanho": 0, "online": True})

TROCA_VOZ = re.compile(r"^(?:usa(?:r)? a voz|troca(?:r)? a voz para) (\w+)$")
_trava = threading.RLock()
_modelo = None
_modelo_id = None


def pasta_modelos():
    return Path(__file__).resolve().parent / "modelos_voz"


def obter(id):
    for voz in CATALOGO:
        if voz["id"] == id:
            return voz
    raise ValueError("Voz desconhecida.")


def caminhos(id):
    voz = obter(id)
    if voz["tipo"] != "piper":
        raise ValueError("Só vozes Piper têm arquivos locais.")
    modelo = pasta_modelos() / (id.split(":", 1)[1] + ".onnx")
    return modelo, Path(str(modelo) + ".json")


def urls(id):
    caminhos(id)
    modelo = id.split(":", 1)[1]
    local, nome, qualidade = modelo.split("-")
    alvo = f"{local.split('_')[0]}/{local}/{nome}/{qualidade}/{modelo}.onnx"
    url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/" + quote(alvo)
    return url, url + ".json"


def listar():
    return [dict(v, instalada=v["tipo"] != "piper" or
                 all(p.is_file() for p in caminhos(v["id"]))) for v in CATALOGO]


def baixar(id, progresso=None):
    with _trava:
        destinos = caminhos(id)
        enderecos = urls(id)
        pasta_modelos().mkdir(parents=True, exist_ok=True)
        partes = [Path(str(p) + ".part") for p in destinos]
        feito = 0
        total = 0
        try:
            with ExitStack() as pilha:
                respostas = [pilha.enter_context(urllib.request.urlopen(url, timeout=60))
                             for url in enderecos]
                tamanhos = [int(r.headers.get("Content-Length", 0)) for r in respostas]
                total = sum(tamanhos) if all(tamanhos) else 0
                for resposta, parte, tamanho in zip(respostas, partes, tamanhos):
                    with parte.open("wb") as saida:
                        while True:
                            bloco = resposta.read(65536)
                            if not bloco:
                                break
                            saida.write(bloco)
                            feito += len(bloco)
                            if progresso:
                                progresso(feito, total)
                    if not parte.stat().st_size or (tamanho and parte.stat().st_size != tamanho):
                        raise ValueError("Download incompleto.")
            with partes[1].open(encoding="utf-8") as entrada:
                dados = json.load(entrada)
            if not isinstance(dados, dict):
                raise ValueError("Configuração da voz inválida.")
            for parte, destino in zip(partes, destinos):
                parte.replace(destino)
        finally:
            for parte in partes:
                parte.unlink(missing_ok=True)


def remover(id):
    with _trava:
        for caminho in caminhos(id):
            caminho.unlink(missing_ok=True)
        if config.carregar().get("voz") == id:
            usar("windows")


def usar(id):
    obter(id)
    if not next(v for v in listar() if v["id"] == id)["instalada"]:
        raise ValueError("Essa voz ainda não foi baixada.")
    with _trava:
        dados = config.carregar()
        dados["voz"] = id
        arquivo = config.BASE / "config.json"
        parte = arquivo.with_suffix(".json.part")
        parte.write_text(json.dumps(dados, ensure_ascii=False, indent=4), encoding="utf-8")
        parte.replace(arquivo)


def pelo_nome(nome):
    def limpar(t):
        return "".join(c for c in unicodedata.normalize("NFD", t.lower())
                       if unicodedata.category(c) != "Mn")
    if limpar(nome) in ("windows", "maria"):
        return "windows"
    return next((v["id"] for v in CATALOGO if limpar(v["nome"]) == limpar(nome)), None)


def escala_piper(velocidade):
    return 190 / max(1, float(velocidade))


def taxa_edge(velocidade):
    return f"{round((max(1, float(velocidade)) / 190 - 1) * 100):+d}%"


def carregar_piper(id):
    global _modelo, _modelo_id
    from piper import PiperVoice
    if _modelo_id != id:
        modelo, ajustes = caminhos(id)
        _modelo = PiperVoice.load(modelo, config_path=ajustes)
        _modelo_id = id


def pedacos_piper(texto, id, velocidade):
    from piper import SynthesisConfig
    carregar_piper(id)
    for pedaco in _modelo.synthesize(texto, syn_config=SynthesisConfig(
            length_scale=escala_piper(velocidade))):
        yield pedaco.audio_float_array, _modelo.config.sample_rate


def sintetizar(texto, id, velocidade):
    import numpy as np
    tipo = obter(id)["tipo"]
    if tipo == "piper":
        pedacos = list(pedacos_piper(texto, id, velocidade))
        return np.concatenate([p[0] for p in pedacos]).astype(np.float32), pedacos[0][1]
    if tipo == "edge":
        import edge_tts
        import miniaudio

        async def audio():
            dados = bytearray()
            comunicador = edge_tts.Communicate(texto, id.split(":", 1)[1], rate=taxa_edge(velocidade))
            async for pedaco in comunicador.stream():
                if pedaco["type"] == "audio":
                    dados.extend(pedaco["data"])
            return bytes(dados)

        som = miniaudio.decode(asyncio.run(audio()), output_format=miniaudio.SampleFormat.FLOAT32,
                               nchannels=1, sample_rate=24000)
        return np.asarray(som.samples, dtype=np.float32), som.sample_rate
    raise ValueError("Windows usa SAPI diretamente.")
