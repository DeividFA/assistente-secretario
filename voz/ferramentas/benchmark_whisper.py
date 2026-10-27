"""Compara o Whisper em CPU com frases sintetizadas pela voz do Windows.

Uso: python voz/ferramentas/benchmark_whisper.py --modelos small,medium,large-v3-turbo
Os modelos ausentes podem ser baixados pelo faster-whisper.
"""

import argparse
import gc
import sys
import tempfile
import time
import wave
from pathlib import Path


FRASES = (
    "Secretário, abre o navegador e pesquisa a previsão do tempo para amanhã.",
    "Deivid tem uma reunião de trabalho às quinze horas na próxima terça-feira.",
    "Quero estudar tecnologia e organizar minhas anotações no Obsidian.",
)


def gerar_audios(pasta):
    """Salva as três frases sem reproduzir som nem acessar o microfone."""
    import pyttsx3

    voz = pyttsx3.init("sapi5")
    try:
        for opcao in voz.getProperty("voices"):
            idiomas = str(opcao.languages).lower()
            nome = opcao.name.lower()
            if any(termo in idiomas + " " + nome for termo in (
                "portugu", "brazil", "pt-br", "pt_br", "pt-pt", "pt_pt", "0416", "0816",
            )):
                voz.setProperty("voice", opcao.id)
                break
        else:
            raise RuntimeError("Nenhuma voz portuguesa do Windows foi encontrada.")
        voz.setProperty("rate", 190)
        caminhos = []
        for numero, frase in enumerate(FRASES, 1):
            caminho = pasta / f"frase_{numero}.wav"
            voz.save_to_file(frase, str(caminho))
            caminhos.append(caminho)
        voz.runAndWait()
        for caminho in caminhos:
            with wave.open(str(caminho), "rb") as audio:
                if audio.getnframes() == 0:
                    raise RuntimeError(f"Áudio vazio: {caminho.name}")
        return caminhos
    finally:
        voz.stop()


def medir_modelo(nome, caminhos):
    from faster_whisper import WhisperModel

    modelo = None
    try:
        inicio = time.perf_counter()
        modelo = WhisperModel(nome, device="cpu", compute_type="int8")
        carga = time.perf_counter() - inicio
        tempos = []
        for numero, caminho in enumerate(caminhos, 1):
            inicio = time.perf_counter()
            segmentos, _ = modelo.transcribe(
                str(caminho), language="pt", beam_size=1,
                condition_on_previous_text=False,
            )
            # A transcrição só ocorre ao consumir o gerador de segmentos.
            texto = " ".join(segmento.text.strip() for segmento in segmentos).strip()
            tempos.append(time.perf_counter() - inicio)
            print(f"  Frase {numero} ({tempos[-1]:.2f} s): {texto}", flush=True)
        return carga, sum(tempos) / len(tempos)
    finally:
        del modelo
        gc.collect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modelos", default="small,medium,large-v3-turbo",
        help="Nomes dos modelos separados por vírgula (padrão: %(default)s).",
    )
    argumentos = parser.parse_args()
    modelos = list(dict.fromkeys(
        nome.strip() for nome in argumentos.modelos.split(",") if nome.strip()
    ))
    if not modelos:
        parser.error("Informe pelo menos um modelo em --modelos.")

    resultados = []
    with tempfile.TemporaryDirectory(prefix="benchmark_whisper_") as pasta:
        print("Gerando três frases com a voz portuguesa do Windows...", flush=True)
        caminhos = gerar_audios(Path(pasta))
        for numero, frase in enumerate(FRASES, 1):
            print(f"Referência {numero}: {frase}")
        print("CPU / int8; média de três transcrições, sem aquecimento.")
        print("A carga inclui eventual download do modelo.", flush=True)
        for nome in modelos:
            print(f"\nModelo: {nome}", flush=True)
            try:
                carga, media = medir_modelo(nome, caminhos)
                resultados.append((nome, f"{carga:.2f}", f"{media:.2f}", "ok"))
            except Exception as erro:
                print(f"  Falha: {erro}", file=sys.stderr, flush=True)
                resultados.append((nome, "—", "—", "erro"))

    largura = max(len("Modelo"), *(len(nome) for nome in modelos))
    print("\nResultado final (segundos)")
    print(f"{'Modelo':<{largura}}  {'Carga':>10}  {'Média transcrição':>18}  Estado")
    for nome, carga, media, estado in resultados:
        print(f"{nome:<{largura}}  {carga:>10}  {media:>18}  {estado}")
    return int(any(estado != "ok" for _, _, _, estado in resultados))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as erro:
        print(f"Falha no benchmark: {erro}", file=sys.stderr)
        sys.exit(1)
