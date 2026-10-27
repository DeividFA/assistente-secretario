package com.deivid.secretario

import kotlinx.serialization.json.JsonObject

interface AcaoCelular {
    val nome: String
    val descricao: String
    val parametros: JsonObject
    suspend fun executar(argumentos: JsonObject): String
}

class RegistroAcoes(val acoes: List<AcaoCelular> = emptyList()) {
    init { require(acoes.map { it.nome }.distinct().size == acoes.size) }
    fun escolher(nome: String): AcaoCelular? = acoes.singleOrNull { it.nome == nome }
}
