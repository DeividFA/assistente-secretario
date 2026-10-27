package com.deivid.secretario

import kotlinx.serialization.json.*

data class Pareamento(val hostLan: String?, val hostTailscale: String?, val porta: Int, val token: String) {
    val hosts: List<String> get() = listOfNotNull(hostLan, hostTailscale).distinct()

    companion object {
        fun ler(texto: String): Pareamento {
            val objeto = Json.parseToJsonElement(texto).jsonObject
            fun host(nome: String): String? {
                val valor = objeto[nome] ?: error("QR sem $nome")
                if (valor == JsonNull) return null
                require(valor.jsonPrimitive.isString) { "Host inválido" }
                val ip = valor.jsonPrimitive.content
                val partes = ip.split('.').map { it.toIntOrNull() ?: -1 }
                require(partes.size == 4 && partes.all { it in 0..255 }) { "Host deve ser IPv4 privado" }
                val privado = partes[0] == 10 || (partes[0] == 172 && partes[1] in 16..31) ||
                    (partes[0] == 192 && partes[1] == 168) || (partes[0] == 100 && partes[1] in 64..127)
                require(privado) { "Host fora da rede privada/Tailscale" }
                return ip
            }
            val porta = objeto.getValue("porta").jsonPrimitive
            require(!porta.isString && porta.int in 1..65535) { "Porta inválida" }
            val token = objeto.getValue("token").jsonPrimitive
            require(token.isString && token.content.matches(Regex("[a-fA-F0-9]{64}"))) { "Token inválido" }
            return Pareamento(host("host_lan"), host("host_tailscale"), porta.int, token.content)
                .also { require(it.hosts.isNotEmpty()) { "QR sem endereço disponível" } }
        }
    }

    fun json(): String = buildJsonObject {
        put("host_lan", hostLan?.let(::JsonPrimitive) ?: JsonNull)
        put("host_tailscale", hostTailscale?.let(::JsonPrimitive) ?: JsonNull)
        put("porta", porta); put("token", token)
    }.toString()
}

data class TarefaPc(val id: Long, val comando: String, val status: String)
sealed interface EventoPc {
    data class Mensagem(val autor: String, val texto: String, val tarefa: Long? = null) : EventoPc
    data class Estado(val estado: String) : EventoPc
    data class Fila(val tarefas: List<TarefaPc>) : EventoPc
    data class Outro(val nome: String) : EventoPc
}

object Protocolo {
    fun evento(texto: String): EventoPc {
        val o = Json.parseToJsonElement(texto).jsonObject
        fun campo(nome: String): String = o.getValue(nome).jsonPrimitive.let {
            require(it.isString); it.content
        }
        return when (val nome = campo("evento")) {
            "mensagem" -> EventoPc.Mensagem(campo("autor"), campo("texto"), o["tarefa"]?.jsonPrimitive?.longOrNull)
            "estado" -> EventoPc.Estado(campo("estado"))
            "fila" -> EventoPc.Fila(o.getValue("tarefas").jsonArray.map { item ->
                val t = item.jsonObject
                TarefaPc(t.getValue("id").jsonPrimitive.long,
                    t.getValue("comando").jsonPrimitive.content, t.getValue("status").jsonPrimitive.content)
            })
            else -> EventoPc.Outro(nome)
        }
    }

    fun tarefas(texto: String): List<Long> = Json.parseToJsonElement(texto).jsonObject
        .getValue("tarefas").jsonArray.map { it.jsonPrimitive.long }
}
