"""Processo persistente de reprodução, encerrado para interromper a fala."""

import json
import sys

import vozes

_windows = None


def falar_windows(texto, velocidade):
    # SAPI direto: o pyttsx3 reaproveitado no mesmo processo fica mudo a partir da 2ª fala.
    global _windows
    if _windows is None:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        _windows = win32com.client.Dispatch("SAPI.SpVoice")
        for token in _windows.GetVoices():
            descricao = token.GetDescription()
            if "Portug" in descricao or "Maria" in descricao:
                _windows.Voice = token
                break
    # SAPI vai de -10 a 10; 0 ≈ 190 palavras por minuto.
    _windows.Rate = max(-10, min(10, round((float(velocidade) - 190) / 20)))
    _windows.Speak(texto)


def falar(texto, id, velocidade):
    if id == "windows":
        falar_windows(texto, velocidade)
        return
    try:
        import sounddevice as sd
        tipo = vozes.obter(id)["tipo"]
        pedacos = (vozes.pedacos_piper(texto, id, velocidade) if tipo == "piper"
                   else [vozes.sintetizar(texto, id, velocidade)])
        for amostras, taxa in pedacos:
            sd.play(amostras, taxa)
            sd.wait()
    except Exception as erro:
        print(f"Voz {id}: {erro}; usando Windows.", file=sys.stderr, flush=True)
        falar_windows(texto, velocidade)


def main():
    for linha in sys.stdin:
        try:
            pedido = json.loads(linha)
            if pedido.get("carregar"):  # aquece o modelo Piper sem falar
                if vozes.obter(pedido["carregar"])["tipo"] == "piper":
                    vozes.carregar_piper(pedido["carregar"])
                continue
            falar(pedido["texto"], pedido.get("voz", "windows"), pedido.get("velocidade", 190))
        except Exception as erro:
            print(f"Fala: {erro}", file=sys.stderr, flush=True)
        finally:
            print(json.dumps({"fim": True}), flush=True)


if __name__ == "__main__":
    main()
