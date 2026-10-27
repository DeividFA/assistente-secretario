package com.deivid.secretario

import android.content.Context
import java.time.LocalDateTime
import java.util.UUID
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.*

class LembretesCelular(contexto: Context) {
    private val preferencias = contexto.getSharedPreferences("lembretes", Context.MODE_PRIVATE)
    private val trava = Mutex()
    private fun ler(chave: String) = Json.parseToJsonElement(preferencias.getString(chave, "[]")!!).jsonArray
    private fun salvar(chave: String, itens: JsonArray) {
        check(preferencias.edit().putString(chave, itens.toString()).commit()) { "Não foi possível guardar lembretes" }
    }
    suspend fun adicionar(quando: LocalDateTime, texto: String) = trava.withLock {
        val item = buildJsonObject {
            put("id", UUID.randomUUID().toString()); put("quando", quando.withSecond(0).withNano(0).toString())
            put("texto", texto); put("feito", false)
        }
        salvar("pendentes", JsonArray(ler("pendentes") + item))
    }
    suspend fun listar(): String = trava.withLock { JsonArray(ler("pc") + ler("pendentes")).toString() }
    suspend fun sincronizar(pc: ClientePc) = trava.withLock {
        val pendentes = ler("pendentes").toMutableList()
        while (pendentes.isNotEmpty()) {
            pc.enviarLembrete(pendentes.first().jsonObject)
            // O id torna segura a repetição se houver perda de recibo ou encerramento.
            pendentes.removeAt(0)
            salvar("pendentes", JsonArray(pendentes))
        }
        salvar("pc", pc.lerLembretes())
    }
}
