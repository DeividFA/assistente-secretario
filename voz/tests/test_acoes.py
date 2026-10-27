import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import acoes


@pytest.mark.parametrize("cmd", [
    "Get-Date", " get-process | Select-Object Name | Sort-Object Name ",
    'Get-ChildItem "C:\\Meus arquivos" | Measure-Object',
    "Get-Content arquivo.txt | Where-Object Length -gt 3 | Format-Table",
    "Test-Path C:\\Windows", "Get-Clipboard | Format-List",
    "Get-ComputerInfo", "Get-Volume", "Get-NetIPAddress",
])
def test_comando_seguro_aceita_leitura(cmd):
    assert acoes.comando_seguro(cmd)


@pytest.mark.parametrize("cmd", [
    "", None, "Remove-Item arquivo", "Get-Date; Remove-Item arquivo",
    "Get-Date & calc", "Get-Date > arquivo", "Get-Date `n calc",
    "Get-Content $(calc)", "Get-Date | Start-Process calc",
    "Get-Date | Get-Process", "Get-Date |", "Get-Date\ncalc",
    "Get-Date | Where-Object { calc }", 'Get-Content "$(calc)"',
    "Get-Date | Select-Object (calc)", "Get-Date | Invoke-Expression",
    "Get-Date | Remove-Item", "Get-Date | Set-Content arquivo",
    "Get-Date | Stop-Process", "& Get-Date", 'Get-Content "arquivo',
])
def test_comando_seguro_recusa_execucao_arbitraria(cmd):
    assert not acoes.comando_seguro(cmd)


@pytest.mark.parametrize("nome,args", [
    ("inexistente", {}), (None, {}), ([], {}), ("abrir", None),
    ("abrir", {}), ("abrir", {"alvo": "calc", "extra": True}),
    ("abrir", {"alvo": 12}), ("clicar", {"x": True, "y": 1}),
    ("digitar", {"texto": "oi", "enter": "sim"}),
])
def test_executar_valida_sem_acionar_dispositivos(monkeypatch, nome, args):
    def proibido(*args, **kwargs):
        pytest.fail("Não deve chamar sentidos.")
    monkeypatch.setattr(acoes, "_sentidos", proibido)
    resultado = acoes.executar(nome, args)
    assert resultado["ok"] is False
    assert isinstance(resultado["texto"], str)
    assert resultado["imagem"] is None


def test_foto_sem_pedido_e_recusada(monkeypatch):
    monkeypatch.setitem(acoes.ACOES["foto_camera"], "funcao",
                        lambda: pytest.fail("Não deve abrir câmera."))
    assert not acoes.executar("foto_camera", {}, "veja a tela")["ok"]


@pytest.mark.parametrize("pedido", ["use a câmera", "tire uma foto", "uma selfie"])
def test_foto_solicitada_retorna_caminho(monkeypatch, tmp_path, pedido):
    caminho = tmp_path / "camera.jpg"
    monkeypatch.setitem(acoes.ACOES["foto_camera"], "funcao", lambda: caminho)
    assert acoes.executar("foto_camera", {}, pedido) == {
        "ok": True, "texto": str(caminho), "imagem": str(caminho),
    }


def test_tela_e_janelas_reaproveitam_sentidos(monkeypatch, tmp_path):
    chamadas = []
    caminho = tmp_path / "tela.jpg"

    def falso(nome, *args, **kwargs):
        chamadas.append((nome, args, kwargs))
        return caminho if nome == "salvar_tela" else ["Janela falsa"]

    monkeypatch.setattr(acoes, "_sentidos", falso)
    assert acoes.executar("ver_tela", {})["imagem"] == str(caminho)
    assert acoes.executar("janelas", {})["imagem"] is None
    assert [chamada[0] for chamada in chamadas] == ["salvar_tela", "janelas"]


def test_excecao_vira_resultado(monkeypatch):
    def falhar(alvo):
        raise RuntimeError("falha simulada")
    monkeypatch.setitem(acoes.ACOES["abrir"], "funcao", falhar)
    assert acoes.executar("abrir", {"alvo": "calc"}) == {
        "ok": False, "texto": "falha simulada", "imagem": None,
    }


def test_confirmacao_de_comandos():
    assert not acoes.precisa_confirmar("comando", {"powershell": "Get-Date"})
    assert acoes.precisa_confirmar("comando", {"powershell": "Remove-Item arquivo"})
    assert acoes.precisa_confirmar("comando", {})
    assert acoes.precisa_confirmar("inexistente", {})
    assert not acoes.precisa_confirmar("abrir", {"alvo": "calc"})


def test_comando_usa_timeout_e_limita_saida(monkeypatch):
    def rodar(argumentos, **opcoes):
        assert argumentos == ["powershell", "-NoProfile", "-Command", "Get-Date"]
        assert opcoes == {"capture_output": True, "text": True, "timeout": 20}
        return type("Resultado", (), {"stdout": "a" * 2000, "stderr": "", "returncode": 0})()
    monkeypatch.setattr(acoes.subprocess, "run", rodar)
    resultado = acoes.executar("comando", {"powershell": "Get-Date"})
    assert resultado["ok"]
    assert len(resultado["texto"]) == 1500


def test_pastas_e_pesquisa_nao_abrem_nada(monkeypatch):
    alvos = []
    monkeypatch.setattr(acoes, "abrir", alvos.append)
    for nome, pasta in [("documentos", "Documents"), ("downloads", "Downloads"),
                        ("área de trabalho", "Desktop"), ("imagens", "Pictures"),
                        ("músicas", "Music"), ("vídeos", "Videos")]:
        acoes.abrir_pasta(nome)
        assert alvos[-1] == str(Path.home() / pasta)
    acoes.abrir_pasta("C:\\pasta")
    assert alvos[-1] == "C:\\pasta"
    acoes.pesquisar_web("café & pão")
    assert alvos[-1] == "https://www.google.com/search?q=caf%C3%A9+%26+p%C3%A3o"


def test_descricao_cita_todas_as_acoes():
    descricao = acoes.descrever_acoes()
    for nome, acao in acoes.ACOES.items():
        assert f"{nome}(" in descricao
        assert callable(acao["funcao"])
        assert isinstance(acao["confirmar"], bool)
        for argumento in acao["args"]:
            assert argumento in descricao
