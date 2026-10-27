"""Persistência dos lembretes compartilhada pelo MCP e pela ponte."""
import json
from datetime import datetime
from pathlib import Path
import threading

ARQUIVO = Path(__file__).resolve().parent / 'lembretes.json'
TRAVA = threading.RLock()


def listar(arquivo=ARQUIVO):
    with TRAVA:
        try:
            return json.loads(arquivo.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return []


def adicionar(quando, texto, id=None, arquivo=ARQUIVO):
    data = datetime.strptime(quando, '%Y-%m-%dT%H:%M')
    if data.isoformat(timespec='minutes') != quando:
        raise ValueError('Data inválida')
    if not isinstance(texto, str) or not texto.strip() or len(texto) > 10000:
        raise ValueError('Texto inválido')
    if id is not None and (not isinstance(id, str) or not 1 <= len(id) <= 100):
        raise ValueError('Identificador inválido')
    with TRAVA:
        itens = listar(arquivo)
        if id is not None:
            existente = next((item for item in itens if item.get('id') == id), None)
            if existente is not None:
                if existente['quando'] != quando or existente['texto'] != texto:
                    raise ValueError('Identificador já usado')
                return existente
        item = dict(quando=quando, texto=texto, feito=False)
        if id is not None:
            item['id'] = id
        itens.append(item)
        temporario = arquivo.with_suffix('.json.tmp')
        temporario.write_text(json.dumps(itens, ensure_ascii=False, indent=2), encoding='utf-8')
        temporario.replace(arquivo)
        return item
