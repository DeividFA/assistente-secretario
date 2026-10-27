package com.deivid.secretario

import android.content.Context
import java.time.LocalDate
import java.util.Locale
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class PreferenciasGastos(contexto: Context) {
    private val preferencias = contexto.getSharedPreferences("gastos", Context.MODE_PRIVATE)
    var notificacoes: Boolean
        get() = preferencias.getBoolean("notificacoes", false)
        set(valor) { preferencias.edit().putBoolean("notificacoes", valor).apply() }
    fun apps(): Set<String> = preferencias.getStringSet("apps", emptySet())!!.toSet()
    fun marcar(pacote: String, marcado: Boolean) {
        val apps = apps().toMutableSet()
        if (marcado) apps.add(pacote) else apps.remove(pacote)
        preferencias.edit().putStringSet("apps", apps).apply()
    }
    private fun chave(local: String) = local.trim().lowercase(Locale.ROOT)
    fun categoria(local: String): String? = preferencias.getString("categoria:${chave(local)}", null)
    fun aprender(local: String, categoria: String) {
        if (local.isNotBlank()) preferencias.edit().putString("categoria:${chave(local)}", categoria).apply()
    }
    fun orcamento(categoria: String): Long = preferencias.getLong("orcamento:$categoria", 0)
    fun orcamento(categoria: String, valor: Long) { require(valor > 0); preferencias.edit().putLong("orcamento:$categoria", valor).apply() }
}

class GastosCelular(private val dados: DadosGastos, val preferencias: PreferenciasGastos) {
    companion object { private val trava = Mutex() }
    suspend fun guardar(rascunho: RascunhoGasto, confirmado: Boolean, id: String = java.util.UUID.randomUUID().toString()): Boolean = trava.withLock {
        if (rascunho.origem == "csv" && dados.duplicados(rascunho.data,
                rascunho.valor, rascunho.estabelecimento, rascunho.origem) > 0) return@withLock false
        require(rascunho.valor in 1..1_000_000_000_000L)
        LocalDate.parse(rascunho.data)
        dados.inserir(GastoLocal(id = id, data = rascunho.data, valor_centavos = rascunho.valor,
            descricao = "Gasto", estabelecimento = ParseGastos.seguro(rascunho.estabelecimento),
            categoria = ParseGastos.seguro(rascunho.categoria), forma = ParseGastos.seguro(rascunho.forma),
            origem = rascunho.origem, confirmado = confirmado))
        true
    }
    suspend fun sincronizar(pc: ClientePc) = trava.withLock {
        val pendentes = dados.pendentes()
        if (pendentes.isNotEmpty()) {
            val ids = pc.enviarGastos(pendentes)
            check(ids.toSet() == pendentes.map { it.id }.toSet())
            dados.sincronizados(ids)
        }
        // Inserção IGNORE preserva correções locais ainda não enviadas.
        pc.lerGastos().forEach { dados.inserir(it) }
    }
    suspend fun corrigir(item: GastoLocal, categoria: String) = trava.withLock {
        val limpa = ParseGastos.seguro(categoria).ifBlank { "Outros" }
        dados.atualizar(item.copy(categoria = limpa, confirmado = true, sincronizado = false))
        preferencias.aprender(item.estabelecimento, limpa)
    }
    suspend fun resumo(categoria: String = ""): String {
        val mes = LocalDate.now().toString().take(7)
        val itens = dados.todos().filter { it.confirmado && it.data.startsWith(mes) &&
            (categoria.isBlank() || it.categoria.equals(categoria, true) || it.estabelecimento.contains(categoria, true)) }
        return "Gastos $mes${if (categoria.isBlank()) "" else " · $categoria"}: ${ParseGastos.reais(itens.sumOf { it.valor_centavos })}"
    }
    suspend fun avisos(): String {
        val mes = LocalDate.now().toString().take(7)
        return dados.todos().filter { it.confirmado && it.data.startsWith(mes) }.groupBy { it.categoria }
            .mapNotNull { (categoria, itens) ->
                val limite = preferencias.orcamento(categoria); val total = itens.sumOf { it.valor_centavos }
                if (limite > 0 && total >= (limite * 80 + 99) / 100) "$categoria: ${ParseGastos.reais(total)} (80% do orçamento atingido)" else null
            }.joinToString("\n")
    }
}
