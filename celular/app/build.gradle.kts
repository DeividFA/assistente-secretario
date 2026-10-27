import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
}
val versao = Properties().apply { rootProject.file("versao.properties").inputStream().use { load(it) } }
val chaves = Properties().apply {
    rootProject.file("keystore.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) }
}
fun segredo(nome: String): String? = System.getenv("SECRETARIO_${nome.uppercase()}")
    ?.takeIf { it.isNotBlank() } ?: chaves.getProperty(nome)?.takeIf { it.isNotBlank() }
val caminhoChave = segredo("storeFile")
val arquivoChave = caminhoChave?.let { rootProject.file(it) }
val podeAssinar = arquivoChave?.isFile == true &&
    listOf("storePassword", "keyAlias", "keyPassword").all { segredo(it) != null }
android {
    namespace = "com.deivid.secretario"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.deivid.secretario"
        minSdk = 29
        targetSdk = 35
        versionCode = versao.getProperty("versionCode").toInt().also { require(it > 0) }
        versionName = versao.getProperty("versionName").also { require(!it.isNullOrBlank()) }
    }
    signingConfigs {
        if (podeAssinar) create("localRelease") {
            storeFile = arquivoChave
            storePassword = segredo("storePassword")
            keyAlias = segredo("keyAlias")
            keyPassword = segredo("keyPassword")
        }
    }
    buildTypes { getByName("release") {
        if (podeAssinar) signingConfig = signingConfigs.getByName("localRelease")
    } }
    buildFeatures { compose = true; buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
ksp { arg("room.schemaLocation", "$projectDir/schemas") }
dependencies {
    implementation("androidx.work:work-runtime-ktx:2.10.0")
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.activity.compose)
    implementation(libs.core.ktx)
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.lifecycle.viewmodel.ktx)
    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    ksp(libs.room.compiler)
    implementation(libs.coroutines.android)
    implementation(libs.serialization.json)
    implementation(libs.okhttp)
    implementation(libs.camera.core)
    implementation(libs.camera.camera2)
    implementation(libs.camera.lifecycle)
    implementation(libs.camera.view)
    implementation(libs.mlkit.barcode)
    implementation("com.google.mlkit:text-recognition:16.0.1")
    implementation(libs.security.crypto)
    testImplementation(libs.junit)
    testImplementation(libs.coroutines.test)
}
