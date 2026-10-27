package com.deivid.secretario

import android.content.Context
import kotlinx.serialization.json.*

class OperarTela : AcaoCelular {
    override val nome = "operar_tela"
    override val descricao = "Opera app não financeiro por Acessibilidade: iniciar (sessão confirmada), ler, tocar, preencher, rolar, voltar, gesto ou parar. Máximo 15 passos. Cada mutação exige confirmação humana no overlay; nunca autenticação, senha, CAPTCHA ou códigos. Use índices da última leitura; após cada ação leia novamente."
    override val parametros = buildJsonObject {
        put("type", "object")
        put("properties", buildJsonObject {
            put("acao", buildJsonObject { put("type", "string"); put("enum", JsonArray(listOf("iniciar", "ler", "tocar", "preencher", "rolar", "voltar", "gesto", "parar").map(::JsonPrimitive))) })
            put("indice", buildJsonObject { put("type", "integer") })
            put("texto", buildJsonObject { put("type", "string") })
            listOf("x", "y").forEach { put(it, buildJsonObject { put("type", "number") }) }
        })
        put("required", JsonArray(listOf(JsonPrimitive("acao"))))
        put("additionalProperties", false)
    }
    override suspend fun executar(argumentos: JsonObject): String {
        val servico = ServicoAcessibilidade.atual ?: error("Ative Secretário em Configurações > Acessibilidade")
        return servico.executar(argumentos.getValue("acao").jsonPrimitive.content,
            argumentos["indice"]?.jsonPrimitive?.intOrNull, argumentos["texto"]?.jsonPrimitive?.content.orEmpty(),
            argumentos["x"]?.jsonPrimitive?.floatOrNull, argumentos["y"]?.jsonPrimitive?.floatOrNull)
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
