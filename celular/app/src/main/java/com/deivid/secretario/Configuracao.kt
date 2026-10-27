package com.deivid.secretario

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

enum class Provedor(val titulo: String, val base: String, val modelo: String) {
    GEMINI("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
    GPT("GPT", "https://api.openai.com/v1/", "gpt-4o-mini"),
    GROK("Grok", "https://api.x.ai/v1/", "grok-3-mini"),
    OPENROUTER("OpenRouter", "https://openrouter.ai/api/v1/", "openai/gpt-4o-mini")
}

data class ConfigNuvem(val provedor: Provedor, val base: String, val modelo: String, val chave: String)

@Suppress("DEPRECATION")
class Configuracao(contexto: Context) {
    private val preferencias = EncryptedSharedPreferences.create(
        contexto, "segredos", MasterKey.Builder(contexto).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
    )
    fun pareamento(): Pareamento? = preferencias.getString("pc", null)?.let(Pareamento::ler)
    fun parear(pc: Pareamento) { preferencias.edit().putString("pc", pc.json()).apply() }
    fun removerPc() { preferencias.edit().remove("pc").apply() }
    fun perfilEstilo(): String = preferencias.getString("perfil_estilo", "").orEmpty()
    fun guardarPerfilEstilo(resumo: String) { preferencias.edit().putString("perfil_estilo", resumo.take(1600)).apply() }
    fun postagensPendentes(): String = preferencias.getString("postagens", "[]")!!
    fun guardarPostagens(texto: String) { preferencias.edit().putString("postagens", texto).commit() }
    fun nuvem(): ConfigNuvem {
        val provedor = Provedor.entries.firstOrNull { it.name == preferencias.getString("provedor", "GPT") } ?: Provedor.GPT
        return ConfigNuvem(provedor, preferencias.getString("base", provedor.base)!!,
            preferencias.getString("modelo", provedor.modelo)!!, preferencias.getString("chave", "")!!)
    }
    fun salvar(config: ConfigNuvem) {
        val url = config.base.toHttpUrlOrNull()
        require(url != null && url.isHttps && url.username.isEmpty() && url.password.isEmpty() &&
            url.query == null && url.fragment == null) { "Informe uma URL HTTPS válida" }
        require(config.modelo.isNotBlank()) { "Informe o modelo" }
        preferencias.edit().putString("provedor", config.provedor.name).putString("base", config.base)
            .putString("modelo", config.modelo).putString("chave", config.chave).apply()
    }
}
