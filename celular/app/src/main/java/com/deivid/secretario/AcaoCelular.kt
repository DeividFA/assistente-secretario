package com.deivid.secretario

import kotlinx.serialization.json.JsonObject

interface AcaoCelular {
    val nome: String
    val descricao: String
    val parametros: JsonObject
    suspend fun executar(argumentos: JsonObject): String
}

// C3/C4 preencherão este registro. Nenhuma ação do aparelho existe na C2.
class RegistroAcoes(val acoes: List<AcaoCelular> = emptyList())
