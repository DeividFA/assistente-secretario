"""Configuração do assistente de voz com valores padrão."""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
PADROES = {
    "microfone": None,
    "modelo_whisper": "small",
    "velocidade_fala": 190,
    "janela_conversa": 15,
    "palavra_ativacao": "secretário",
    "pausa_fala": 1.4,
    "pasta_backup": str(Path.home() / "Backups" / "Secretario"),
    "pasta_backup_extra": None,
}


def carregar():
    """Lê config.json, completando as opções ausentes com os padrões."""
    configuracao = PADROES.copy()
    arquivo = BASE / "config.json"
    if arquivo.exists():
        with arquivo.open(encoding="utf-8") as entrada:
            configuracao.update(json.load(entrada))
    return configuracao
