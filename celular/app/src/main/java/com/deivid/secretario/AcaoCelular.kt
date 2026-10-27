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

fun appFinanceiro(pacote: String, rotulo: String = ""): Boolean {
    val texto = java.text.Normalizer.normalize("$pacote $rotulo".lowercase(), java.text.Normalizer.Form.NFD)
        .replace(Regex("\\p{M}"), "")
    return pacote in setOf("com.nu.production", "br.com.bb.android", "br.com.intermedium", "com.itau") ||
        Regex("bank|banco|pay|wallet|invest|cartao|credito|cripto|nubank|itau|bradesco|santander|picpay|binance|sicredi|sicoob|caixa|intermedium|c6bank|btg|rico|neon|next|original|banrisul|xpinc|mercado.?pago|pagbank|finance", RegexOption.IGNORE_CASE)
            .containsMatchIn(texto)
}
