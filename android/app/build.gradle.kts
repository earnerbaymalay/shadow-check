plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "app.shadowcheck"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.shadowcheck"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // Deliberately dependency-free: only the Android framework is used at runtime.
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303") // org.json stubs are empty in JVM unit tests
}
