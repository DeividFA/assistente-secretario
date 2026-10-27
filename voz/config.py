"""Configuração do assistente de voz com valores padrão."""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
PADROES = {
    "motores_paralelos": ["claude", "codex", "gemma"],
    "vagas": {"claude": 2, "codex": 1, "gemini-cli": 1, "gemma": 1, "api": 2},
    "ponte_ativa": False,
    "pasta_apk": "celular/app/build/outputs/apk",
    "microfone": None,
    "mic_em_chamada": "liberar",
    "modo_microfone": "continuo",
    "modelo_whisper": "small",
    "velocidade_fala": 190,
    "voz": "windows",
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
