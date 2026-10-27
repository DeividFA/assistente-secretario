package com.deivid.secretario

import java.time.LocalDateTime
import java.time.temporal.TemporalAdjusters
import java.time.DayOfWeek
import kotlinx.serialization.json.*

data class ElementoReceita(val id: String, val texto: String, val editavel: Boolean)
data class SeletorReceita(val id: String = "", val texto: String = "") {
    fun localizar(tela: List<ElementoReceita>): Int? {
        val candidatos = tela.indices.filter { i ->
            val no = tela[i]
            if (id.isNotBlank()) no.id == id else texto.isNotBlank() && !no.editavel && no.texto == texto
        }
        return candidatos.singleOrNull()
    }
}
data class PassoReceita(val acao: String, val seletor: SeletorReceita)
data class Receita(val app: String, val intencao: String, val passos: List<PassoReceita>) {
    fun json(): String = buildJsonObject {
        put("app", app); put("intencao", intencao)
        put("passos", buildJsonArray { passos.forEach { passo -> add(buildJsonObject {
            put("acao", passo.acao); put("id", passo.seletor.id); put("texto", passo.seletor.texto)
        }) } })
    }.toString()
    companion object {
        fun ler(texto: String): Receita {
            val o = Json.parseToJsonElement(texto).jsonObject
            return Receita(o.getValue("app").jsonPrimitive.content, o.getValue("intencao").jsonPrimitive.content,
                o.getValue("passos").jsonArray.map { item -> val p = item.jsonObject
                    PassoReceita(p.getValue("acao").jsonPrimitive.content,
                        SeletorReceita(p.getValue("id").jsonPrimitive.content, p.getValue("texto").jsonPrimitive.content)) })
        }
    }
}

/** Só seletores estáticos saem deste rascunho; valores ficam apenas na memória da sessão. */
class GravadorReceita(private val app: String, private val intencao: String, private val politica: BloqueioFinanceiro) {
    private val passos = mutableListOf<PassoReceita>()
    private val digitados = mutableListOf<String>()
    private var valido = !politica.bloqueado(app) && intencao in INTENCOES
    fun protegerValores(valores: List<String>) {
        digitados.addAll(valores.filter { it.isNotBlank() })
    }
    fun registrar(acao: String, alvo: ElementoReceita?, textoDigitado: String = "", sucesso: Boolean) {
        if (textoDigitado.isNotEmpty()) digitados.add(textoDigitado)
        if (!sucesso || acao !in setOf("tocar", "preencher", "rolar") || alvo == null) { valido = false; return }
        val seletor = if (alvo.id.isNotBlank()) SeletorReceita(id = alvo.id)
            else if (!alvo.editavel && alvo.texto.isNotBlank()) SeletorReceita(texto = alvo.texto)
            else { valido = false; return }
        passos.add(PassoReceita(acao, seletor))
    }
    fun concluir(sucesso: Boolean, confirmado: Boolean): Receita? {
        if (!valido || !sucesso || !confirmado || politica.bloqueado(app) || passos.isEmpty()) return null
        fun normalizar(valor: String) = valor.trim().replace(Regex("\\s+"), " ").lowercase(java.util.Locale.ROOT)
        if (passos.any { p -> digitados.any {
                val valor = normalizar(it)
                valor.isNotBlank() && (normalizar(p.seletor.texto).contains(valor) || normalizar(p.seletor.id).contains(valor))
            } }) return null
        return Receita(app, intencao, passos.toList())
    }
    companion object { val INTENCOES = setOf("mensagem", "postagem", "pesquisa", "outro") }
}

data class UsoRotina(val intencao: String, val quando: LocalDateTime)
data class PadraoRotina(val intencao: String, val dia: DayOfWeek, val hora: Int) {
    val chave get() = "rotina:$intencao:${dia.value}:$hora"
}
object PadroesRotina {
    fun detectar(usos: List<UsoRotina>): List<PadraoRotina> = usos.filter { it.intencao == "agenda" }
        .groupBy { PadraoRotina(it.intencao, it.quando.dayOfWeek, it.quando.hour) }
        .filterValues { grupo -> grupo.size >= 3 && grupo.map {
            it.quando.toLocalDate().with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
        }.distinct().size >= 3 }.keys.sortedWith(compareBy({ it.dia.value }, { it.hora }))
}
