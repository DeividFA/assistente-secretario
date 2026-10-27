"""Aplicativos que estão usando o microfone no Windows."""

import ntpath
import sys

try:
    import winreg
except ImportError:
    winreg = None

CHAVE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def apps_usando_microfone():
    if winreg is None:
        return []
    proprios = {str(p).replace("\\", "#").lower()
                for p in (sys.executable, getattr(sys, "_base_executable", sys.executable))}
    encontrados = set()

    def visitar(caminho):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, caminho) as chave:
                nome = caminho.rsplit("\\", 1)[-1]
                try:
                    inicio = winreg.QueryValueEx(chave, "LastUsedTimeStart")[0]
                    fim = winreg.QueryValueEx(chave, "LastUsedTimeStop")[0]
                    if inicio > 0 and fim == 0 and nome.lower() not in proprios:
                        executavel = ntpath.basename(nome.replace("#", "\\"))
                        if executavel.lower() != "electron.exe":
                            amigaveis = {"discord.exe": "Discord", "chrome.exe": "Chrome",
                                         "msedge.exe": "Edge", "teams.exe": "Teams",
                                         "ms-teams.exe": "Teams", "zoom.exe": "Zoom"}
                            encontrados.add(amigaveis.get(executavel.lower(),
                                                         ntpath.splitext(executavel)[0]))
                except OSError:
                    pass
                indice = 0
                while True:
                    try:
                        filho = winreg.EnumKey(chave, indice)
                    except OSError:
                        break
                    visitar(caminho + "\\" + filho)
                    indice += 1
        except OSError:
            pass

    visitar(CHAVE)
    return sorted(encontrados)
