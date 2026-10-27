package com.deivid.secretario

import android.content.Context
import kotlinx.serialization.json.*

class OperarTela : AcaoCelular {
    override val nome = "operar_tela"
    override val descricao = "Opera app não financeiro. iniciar com intencao (mensagem/postagem/pesquisa/outro) começa aprendizado; reutilizar tenta receita com textos novos deste pedido (um por preenchimento); se seletor mudou, refaça da tela atual. concluir SOMENTE após sequência terminar com sucesso pede confirmação humana e guarda seletores sem valores. parar cancela sem guardar. Cada mutação, inclusive final de receita, exige confirmação no overlay. Nunca autenticação. Máximo 15 passos; leia após cada ação."
    override val parametros = buildJsonObject {
        put("type", "object")
        put("properties", buildJsonObject {
            put("acao", buildJsonObject { put("type", "string"); put("enum", JsonArray(listOf("iniciar", "ler", "tocar", "preencher", "rolar", "voltar", "gesto", "parar", "concluir", "reutilizar").map(::JsonPrimitive))) })
            put("intencao", buildJsonObject { put("type", "string"); put("enum", JsonArray(GravadorReceita.INTENCOES.map(::JsonPrimitive))) })
            put("textos", buildJsonObject { put("type", "array"); put("items", buildJsonObject { put("type", "string") }) })
            put("indice", buildJsonObject { put("type", "integer") })
            put("texto", buildJsonObject { put("type", "string") })
            listOf("x", "y").forEach { put(it, buildJsonObject { put("type", "number") }) }
        })
        put("required", JsonArray(listOf(JsonPrimitive("acao"))))
        put("additionalProperties", false)
    }
    override suspend fun executar(argumentos: JsonObject): String {
        val servico = ServicoAcessibilidade.atual ?: error("Ative Secretário em Configurações > Acessibilidade")
        val intencao = argumentos["intencao"]?.jsonPrimitive?.content.orEmpty()
        if (argumentos.getValue("acao").jsonPrimitive.content == "reutilizar")
            return servico.reutilizar(intencao, argumentos["textos"]?.jsonArray?.map { it.jsonPrimitive.content }.orEmpty())
        return servico.executar(argumentos.getValue("acao").jsonPrimitive.content,
            argumentos["indice"]?.jsonPrimitive?.intOrNull, argumentos["texto"]?.jsonPrimitive?.content.orEmpty(),
            argumentos["x"]?.jsonPrimitive?.floatOrNull, argumentos["y"]?.jsonPrimitive?.floatOrNull, intencao = intencao)
    }
}

/** Apenas inclusão local explícita: não é uma ferramenta disponível à IA. */
class ListaBloqueioUsuario(private val contexto: Context) {
    fun acrescentar(pacote: String) {
        val preferencias = contexto.getSharedPreferences("bloqueio_acessibilidade", Context.MODE_PRIVATE)
        val politica = BloqueioFinanceiro(preferencias.getStringSet("adicionais", emptySet()).orEmpty())
        politica.acrescentar(pacote)
        preferencias.edit().putStringSet("adicionais", politica.listaUsuario()).apply()
        ServicoAcessibilidade.atual?.acrescentarBloqueio(pacote)
    }
}
