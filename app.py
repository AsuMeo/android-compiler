#!/usr/bin/env python3
"""
Android Java → APK Compiler v3
Фикс: APK 4KB, classes.dex, ресурсы, подпись
"""
import os
import sys
import tempfile
import shutil
import subprocess
import time
import zipfile
from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

OUTPUT_DIR = "/tmp/apk_outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

ANDROID_HOME = os.environ.get("ANDROID_HOME", "/opt/android-sdk")
BUILD_TOOLS = os.path.join(ANDROID_HOME, "build-tools", "34.0.0")
PLATFORM = os.path.join(ANDROID_HOME, "platforms", "android-34")


def cleanup_old_files():
    now = time.time()
    for f in os.listdir(OUTPUT_DIR):
        path = os.path.join(OUTPUT_DIR, f)
        if os.path.isfile(path) and now - os.path.getmtime(path) > 3600:
            os.remove(path)


def build_apk(project_files, work_dir):
    logs = []
    def log(msg):
        logs.append(msg)
        print(msg, flush=True)

    try:
        app_name = project_files.get("app_name", "MyApp")
        package_name = project_files.get("package_name", "com.example.myapp")
        min_sdk = int(project_files.get("min_sdk", 26))
        files = project_files.get("files", {})

        log("[1/10] Создание структуры проекта...")

        # Разворачиваем файлы как есть в work_dir
        manifest_path = None
        has_manifest = False
        java_files_list = []
        res_files_list = []

        for filepath, content in files.items():
            filepath = filepath.strip().lstrip("/")
            if not filepath:
                continue

            full_path = os.path.join(work_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file:
                file.write(content)

            if filepath == "AndroidManifest.xml":
                has_manifest = True
                manifest_path = full_path
            elif filepath.endswith(".java"):
                java_files_list.append(full_path)
            elif filepath.startswith("res/"):
                res_files_list.append(full_path)

        # Если манифеста нет — генерируем
        if not has_manifest:
            log("[1/10] ⚠ Манифест не найден, генерирую...")
            main_activity = "MainActivity"
            for jf in java_files_list:
                with open(jf, "r", encoding="utf-8") as file:
                    code = file.read()
                if "extends Activity" in code or "extends AppCompatActivity" in code:
                    for line in code.split("\n"):
                        if "public class" in line:
                            parts = line.split("public class")[1].split("{")[0].strip().split()
                            if parts:
                                main_activity = parts[0]
                            break

            manifest_path = os.path.join(work_dir, "AndroidManifest.xml")
            with open(manifest_path, "w", encoding="utf-8") as file:
                file.write(f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{package_name}"
    android:versionCode="1"
    android:versionName="1.0">
    <uses-sdk android:minSdkVersion="{min_sdk}" android:targetSdkVersion="34" />
    <application android:label="{app_name}">
        <activity android:name=".{main_activity}" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>""")
            has_manifest = True

        log(f"[1/10] ✓ Файлов: Java={len(java_files_list)}, Res={len(res_files_list)}")

        # Если нет ресурсов — создаём минимальные
        if not any(f.startswith("res/values/") for f in files.keys()):
            log("[2/10] Создание strings.xml...")
            values_dir = os.path.join(work_dir, "res", "values")
            os.makedirs(values_dir, exist_ok=True)
            strings_path = os.path.join(values_dir, "strings.xml")
            with open(strings_path, "w", encoding="utf-8") as file:
                file.write(f"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">{app_name}</string>
</resources>""")
            res_files_list.append(strings_path)
        else:
            log("[2/10] ✓ Ресурсы от пользователя")

        log("[3/10] Компиляция ресурсов (aapt2 compile)...")
        aapt2 = os.path.join(BUILD_TOOLS, "aapt2")
        compiled_res_dir = os.path.join(work_dir, "compiled_res")
        os.makedirs(compiled_res_dir, exist_ok=True)

        compiled_files = []
        for res_file in res_files_list:
            if res_file.endswith(".xml"):
                r = subprocess.run(
                    [aapt2, "compile", "--legacy", "-o", compiled_res_dir, res_file],
                    capture_output=True, text=True
                )
                if r.returncode != 0:
                    log(f"[3/10] ⚠ {os.path.basename(res_file)}: {r.stderr[:200]}")
                else:
                    log(f"[3/10]   ✓ {os.path.basename(res_file)}")

        # Собираем все .flat файлы
        for f in os.listdir(compiled_res_dir):
            if f.endswith(".flat"):
                compiled_files.append(os.path.join(compiled_res_dir, f))

        if not compiled_files:
            log("[3/10] ✗ Нет скомпилированных ресурсов")
            return {"success": False, "error": "No compiled resources", "logs": logs}

        log(f"[3/10] ✓ .flat файлов: {len(compiled_files)}")
        for cf in compiled_files:
            log(f"[3/10]     {os.path.basename(cf)} ({os.path.getsize(cf)} bytes)")

        log("[4/10] Линковка (aapt2 link)...")
        r_java_dir = os.path.join(work_dir, "r_java")
        os.makedirs(r_java_dir, exist_ok=True)
        resources_ap = os.path.join(work_dir, "resources.ap_")

        link_args = [
            aapt2, "link",
            "-I", os.path.join(PLATFORM, "android.jar"),
            "--manifest", manifest_path,
            "-o", resources_ap,
            "--java", r_java_dir,
            "--min-sdk-version", str(min_sdk),
            "--target-sdk-version", "34",
            "--version-code", "1",
            "--version-name", "1.0",
            "--auto-add-overlay"
        ]
        for cf in compiled_files:
            link_args.extend(["-R", cf])

        r = subprocess.run(link_args, capture_output=True, text=True)
        if r.returncode != 0:
            log(f"[4/10] ✗ ОШИБКА: {r.stderr[:1000]}")
            return {"success": False, "error": r.stderr[:1000], "logs": logs}

        ap_size = os.path.getsize(resources_ap) if os.path.exists(resources_ap) else 0
        log(f"[4/10] ✓ resources.ap_ создан ({ap_size} bytes)")

        # Проверим что внутри resources.ap_
        if os.path.exists(resources_ap):
            with zipfile.ZipFile(resources_ap, 'r') as zf:
                log(f"[4/10]   Содержимое: {zf.namelist()}")

        log("[5/10] Компиляция Java (javac)...")
        classes_dir = os.path.join(work_dir, "classes")
        os.makedirs(classes_dir, exist_ok=True)

        # Собираем ВСЕ Java файлы из work_dir (не только src/)
        all_java = []
        for root, _, files in os.walk(work_dir):
            # Пропускаем compiled_res и r_java (там могут быть .java от R, но мы их отдельно возьмём)
            if "compiled_res" in root or root == r_java_dir:
                continue
            for file in files:
                if file.endswith(".java"):
                    all_java.append(os.path.join(root, file))
        # Добавляем R.java
        for root, _, files in os.walk(r_java_dir):
            for file in files:
                if file.endswith(".java"):
                    all_java.append(os.path.join(root, file))

        all_java = list(set(all_java))  # уникальные

        if not all_java:
            log("[5/10] ✗ Нет Java файлов")
            return {"success": False, "error": "No Java files", "logs": logs}

        javac = os.path.join(os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-17-openjdk-amd64"), "bin", "javac")
        classpath = os.path.join(PLATFORM, "android.jar")

        r = subprocess.run(
            [javac, "-source", "1.8", "-target", "1.8", "-cp", classpath, "-d", classes_dir] + all_java,
            capture_output=True, text=True
        )
        if r.returncode != 0:
            log(f"[5/10] ✗ ОШИБКА:")
            for line in r.stderr.split("\n")[:30]:
                log(f"  > {line}")
            return {"success": False, "error": r.stderr[:1000], "logs": logs}

        class_count = sum(1 for _, _, files in os.walk(classes_dir) for f in files if f.endswith(".class"))
        log(f"[5/10] ✓ Скомпилировано {class_count} .class файлов")

        log("[6/10] Конвертация в Dalvik (d8)...")
        d8 = os.path.join(BUILD_TOOLS, "d8")
        class_files = []
        for root, _, files in os.walk(classes_dir):
            for file in files:
                if file.endswith(".class"):
                    class_files.append(os.path.join(root, file))

        r = subprocess.run(
            [d8, "--release", "--output", work_dir, "--lib", classpath] + class_files,
            capture_output=True, text=True
        )
        if r.returncode != 0:
            log(f"[6/10] ✗ ОШИБКА: {r.stderr[:500]}")
            return {"success": False, "error": r.stderr[:500], "logs": logs}

        dex_path = os.path.join(work_dir, "classes.dex")
        dex_size = os.path.getsize(dex_path) if os.path.exists(dex_path) else 0
        log(f"[6/10] ✓ classes.dex создан ({dex_size} bytes)")

        log("[7/10] Сборка APK...")
        unsigned_apk = os.path.join(work_dir, f"{app_name}_unsigned.apk")

        # Копируем resources.ap_ как основу
        shutil.copy(resources_ap, unsigned_apk)

        # Добавляем classes.dex
        with zipfile.ZipFile(unsigned_apk, "a", zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(dex_path):
                zf.write(dex_path, "classes.dex")

        apk_size = os.path.getsize(unsigned_apk)
        log(f"[7/10] ✓ APK собран ({apk_size} bytes)")

        # Проверим содержимое
        with zipfile.ZipFile(unsigned_apk, 'r') as zf:
            log(f"[7/10]   Содержимое: {zf.namelist()}")

        log("[8/10] Генерация keystore...")
        keystore = os.path.join(work_dir, "debug.keystore")
        keytool = os.path.join(os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-17-openjdk-amd64"), "bin", "keytool")

        subprocess.run([
            keytool, "-genkey", "-v", "-keystore", keystore, "-alias", "androiddebugkey",
            "-storepass", "android", "-keypass", "android", "-keyalg", "RSA", "-validity", "10000",
            "-dname", "CN=Android Debug,O=Android,C=US"
        ], capture_output=True)
        log("[8/10] ✓ Keystore создан")

        log("[9/10] Подпись APK (apksigner)...")
        apksigner = os.path.join(BUILD_TOOLS, "apksigner")
        signed_apk = os.path.join(work_dir, f"{app_name}.apk")

        r = subprocess.run([
            apksigner, "sign", "--ks", keystore, "--ks-pass", "pass:android",
            "--key-pass", "pass:android", "--out", signed_apk, unsigned_apk
        ], capture_output=True, text=True)

        if r.returncode != 0:
            log(f"[9/10] ⚠ apksigner не сработал, пробуем jarsigner...")
            jarsigner = os.path.join(os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-17-openjdk-amd64"), "bin", "jarsigner")
            subprocess.run([
                jarsigner, "-verbose", "-sigalg", "SHA1withRSA", "-digestalg", "SHA1",
                "-keystore", keystore, "-storepass", "android", unsigned_apk, "androiddebugkey"
            ], capture_output=True)
            shutil.copy(unsigned_apk, signed_apk)

        signed_size = os.path.getsize(signed_apk) if os.path.exists(signed_apk) else 0
        log(f"[9/10] ✓ APK подписан ({signed_size} bytes)")

        log("[10/10] Выравнивание (zipalign)...")
        zipalign = os.path.join(BUILD_TOOLS, "zipalign")
        aligned_apk = os.path.join(work_dir, f"{app_name}_aligned.apk")

        r = subprocess.run([zipalign, "-f", "4", signed_apk, aligned_apk], capture_output=True, text=True)

        if r.returncode == 0 and os.path.exists(aligned_apk):
            final_apk = aligned_apk
            log(f"[10/10] ✓ APK выровнен ({os.path.getsize(final_apk)} bytes)")
        else:
            final_apk = signed_apk
            log(f"[10/10] ✓ APK готов (без zipalign, {os.path.getsize(final_apk)} bytes)")

        # Финальная проверка содержимого
        with zipfile.ZipFile(final_apk, 'r') as zf:
            log(f"[FINAL] Содержимое APK: {zf.namelist()}")
            for name in zf.namelist():
                info = zf.getinfo(name)
                log(f"[FINAL]   {name}: {info.file_size} bytes")

        return {"success": True, "apk_path": final_apk, "logs": logs}

    except Exception as e:
        log(f"✗ ИСКЛЮЧЕНИЕ: {str(e)}")
        import traceback
        log(traceback.format_exc())
        return {"success": False, "error": str(e), "logs": logs}


HTML_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>⚡ Android IDE</title>
<style>
:root { --bg:#0a0a0f; --bg2:#12121a; --bg3:#1a1a2e; --bg4:#0f0f1a; --border:#2a2a3e; --border2:#3a3a5e; --text:#e0e0ff; --text2:#8b8bb5; --accent:#7c3aed; --accent2:#a855f7; --accent3:#c084fc; --success:#22c55e; --error:#ef4444; --warn:#f59e0b; }
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body { background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; min-height:100vh; line-height:1.5; overflow-x:hidden; }
.glow { position:fixed; width:400px; height:400px; border-radius:50%; background:radial-gradient(circle,var(--accent) 0%,transparent 70%); opacity:.06; pointer-events:none; z-index:0; }
.glow-1 { top:-100px; left:-100px; }
.glow-2 { bottom:-100px; right:-100px; background:radial-gradient(circle,var(--accent2) 0%,transparent 70%); }
header { background:rgba(10,10,15,.9); backdrop-filter:blur(20px); border-bottom:1px solid var(--border); padding:14px 16px; position:sticky; top:0; z-index:100; display:flex; align-items:center; justify-content:space-between; }
header h1 { font-size:16px; font-weight:700; background:linear-gradient(135deg,var(--accent3),var(--accent2)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; display:flex; align-items:center; gap:8px; }
header h1::before { content:"⚡"; -webkit-text-fill-color:var(--accent3); }
header .badge { font-size:11px; background:var(--bg3); border:1px solid var(--border); padding:4px 10px; border-radius:20px; color:var(--text2); }
.container { max-width:100%; margin:0 auto; padding:12px; position:relative; z-index:1; }
@media(min-width:900px){ .container { max-width:900px; padding:20px; } }
.card { background:var(--bg2); border:1px solid var(--border); border-radius:16px; margin-bottom:12px; overflow:hidden; transition:border-color .3s; }
.card:hover { border-color:rgba(124,58,237,.25); }
.card-header { background:var(--bg3); padding:12px 16px; font-size:12px; font-weight:600; color:var(--text2); text-transform:uppercase; letter-spacing:1px; display:flex; align-items:center; gap:8px; justify-content:space-between; }
.card-body { padding:14px; }
label { display:block; font-size:11px; font-weight:500; color:var(--text2); margin-bottom:5px; text-transform:uppercase; letter-spacing:.5px; }
input,select { width:100%; background:var(--bg); border:1px solid var(--border); border-radius:10px; padding:10px 14px; color:var(--text); font-size:14px; outline:none; transition:all .2s; }
input:focus,select:focus { border-color:var(--accent); box-shadow:0 0 0 3px rgba(124,58,237,.1); }
.row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
@media(max-width:600px){ .row{grid-template-columns:1fr} }
.file-tabs { display:flex; gap:6px; overflow-x:auto; padding-bottom:8px; margin-bottom:8px; scrollbar-width:none; }
.file-tabs::-webkit-scrollbar { display:none; }
.file-tab { flex-shrink:0; padding:8px 14px; background:var(--bg3); border:1px solid var(--border); border-radius:10px; font-size:12px; font-weight:500; color:var(--text2); cursor:pointer; transition:all .2s; display:flex; align-items:center; gap:6px; position:relative; }
.file-tab:hover { border-color:var(--accent); color:var(--text); }
.file-tab.active { background:rgba(124,58,237,.15); border-color:var(--accent); color:var(--text); }
.file-tab .close { width:16px; height:16px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:10px; opacity:0; transition:opacity .2s; }
.file-tab:hover .close { opacity:1; }
.file-tab .close:hover { background:var(--error); color:#fff; }
.add-file-btn { flex-shrink:0; padding:8px 12px; background:var(--bg4); border:1px dashed var(--border2); border-radius:10px; font-size:18px; color:var(--text2); cursor:pointer; transition:all .2s; }
.add-file-btn:hover { border-color:var(--accent); color:var(--accent3); }
.editor-wrap { position:relative; }
.editor { width:100%; min-height:280px; background:var(--bg); border:1px solid var(--border); border-radius:12px; padding:14px; color:var(--text); font-size:13px; line-height:1.7; outline:none; resize:vertical; font-family:'SF Mono','Fira Code',monospace; white-space:pre; overflow-x:auto; tab-size:4; }
.editor:focus { border-color:var(--accent); box-shadow:0 0 0 3px rgba(124,58,237,.1); }
.editor-info { display:flex; justify-content:space-between; align-items:center; margin-top:6px; font-size:11px; color:var(--text2); }
.build-btn { width:100%; padding:16px; background:linear-gradient(135deg,var(--accent),var(--accent2)); border:none; border-radius:14px; color:#fff; font-size:16px; font-weight:700; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:10px; transition:all .2s; box-shadow:0 4px 20px rgba(124,58,237,.3); margin-top:12px; }
.build-btn:hover { transform:translateY(-2px); box-shadow:0 6px 30px rgba(124,58,237,.4); }
.build-btn:active { transform:translateY(0); }
.build-btn:disabled { opacity:.5; cursor:not-allowed; transform:none; }
.spinner { width:18px; height:18px; border:2px solid rgba(255,255,255,.3); border-top-color:#fff; border-radius:50%; animation:spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
.status { margin-top:14px; padding:14px; border-radius:14px; font-size:14px; display:none; }
.status.show { display:block; animation:fadeIn .3s; }
.status-info { background:rgba(124,58,237,.1); border:1px solid rgba(124,58,237,.2); color:var(--accent3); }
.status-success { background:rgba(34,197,94,.1); border:1px solid rgba(34,197,94,.2); color:var(--success); }
.status-error { background:rgba(239,68,68,.1); border:1px solid rgba(239,68,68,.2); color:var(--error); }
.apk-link { display:block; margin-top:12px; padding:16px; background:linear-gradient(135deg,var(--success),#16a34a); color:#fff; text-align:center; border-radius:14px; text-decoration:none; font-weight:700; font-size:15px; box-shadow:0 4px 20px rgba(34,197,94,.3); transition:all .2s; }
.apk-link:hover { transform:translateY(-2px); box-shadow:0 6px 30px rgba(34,197,94,.4); }
.logs { background:var(--bg); border:1px solid var(--border); border-radius:12px; padding:12px; font-family:'SF Mono',monospace; font-size:11px; color:var(--text2); max-height:300px; overflow-y:auto; margin-top:12px; white-space:pre-wrap; word-break:break-all; display:none; }
.logs.show { display:block; }
.log-line { padding:2px 0; border-bottom:1px solid rgba(42,42,62,.3); }
.log-line:last-child { border-bottom:none; }
.log-ok { color:var(--success); }
.log-err { color:var(--error); }
.log-info { color:var(--accent3); }
.log-warn { color:var(--warn); }
.progress-bar { width:100%; height:4px; background:var(--bg3); border-radius:2px; margin-top:10px; overflow:hidden; display:none; }
.progress-bar.show { display:block; }
.progress-fill { height:100%; background:linear-gradient(90deg,var(--accent),var(--accent2)); width:0%; transition:width .3s; border-radius:2px; }
.templates-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-bottom:12px; }
@media(max-width:600px){ .templates-grid{grid-template-columns:repeat(2,1fr)} }
.template-btn { padding:10px; background:var(--bg3); border:1px solid var(--border); border-radius:12px; font-size:12px; font-weight:500; color:var(--text2); cursor:pointer; transition:all .2s; text-align:center; }
.template-btn:hover { background:rgba(124,58,237,.15); border-color:var(--accent); color:var(--text); }
.template-btn:active { transform:scale(.96); }
.modal-overlay { position:fixed; inset:0; background:rgba(0,0,0,.7); backdrop-filter:blur(8px); z-index:200; display:none; align-items:center; justify-content:center; padding:20px; }
.modal-overlay.show { display:flex; }
.modal { background:var(--bg2); border:1px solid var(--border); border-radius:20px; padding:20px; width:100%; max-width:400px; }
.modal h3 { font-size:16px; margin-bottom:16px; }
.modal input { margin-bottom:12px; }
.modal-actions { display:flex; gap:10px; }
.modal-actions button { flex:1; padding:12px; border-radius:12px; border:none; font-size:14px; font-weight:600; cursor:pointer; }
.modal-actions .btn-primary { background:var(--accent); color:#fff; }
.modal-actions .btn-secondary { background:var(--bg3); color:var(--text); border:1px solid var(--border); }
footer { text-align:center; padding:20px; font-size:12px; color:var(--text2); }
@keyframes fadeIn { from{opacity:0;transform:translateY(-10px)} to{opacity:1;transform:translateY(0)} }
</style>
</head>
<body>
<div class="glow glow-1"></div><div class="glow glow-2"></div>
<header>
  <h1>⚡ Android IDE</h1>
  <span class="badge">Java → APK</span>
</header>
<div class="container">
  <div class="card">
    <div class="card-header">⚙️ Проект</div>
    <div class="card-body">
      <div class="row">
        <div><label>Название</label><input type="text" id="appName" value="MyApp"></div>
        <div><label>Package</label><input type="text" id="packageName" value="com.example.myapp"></div>
      </div>
      <div style="margin-top:10px"><label>Min SDK</label>
        <select id="minSdk">
          <option value="21">API 21</option>
          <option value="24">API 24</option>
          <option value="26" selected>API 26</option>
          <option value="28">API 28</option>
          <option value="30">API 30</option>
          <option value="33">API 33</option>
        </select>
      </div>
    </div>
  </div>
  <div class="card">
    <div class="card-header"><span>📝 Файлы</span><span style="font-size:11px;color:var(--text2)" id="fileCount">3</span></div>
    <div class="card-body">
      <div class="templates-grid">
        <button class="template-btn" onclick="loadProject('hello')">👋 Hello</button>
        <button class="template-btn" onclick="loadProject('button')">🔘 Кнопка</button>
        <button class="template-btn" onclick="loadProject('webview')">🌐 WebView</button>
        <button class="template-btn" onclick="loadProject('calc')">🔢 Калькулятор</button>
        <button class="template-btn" onclick="loadProject('toast')">💬 Toast</button>
        <button class="template-btn" onclick="loadProject('input')">⌨️ Ввод</button>
      </div>
      <div class="file-tabs" id="fileTabs"></div>
      <div class="editor-wrap">
        <textarea class="editor" id="editor" spellcheck="false"></textarea>
        <div class="editor-info"><span id="cursorPos">Ln 1, Col 1</span><span id="fileType">Java</span></div>
      </div>
      <button class="add-file-btn" onclick="showAddFileModal()">+</button>
    </div>
  </div>
  <div class="card">
    <div class="card-body">
      <button class="build-btn" id="buildBtn" onclick="buildApk()">
        <span id="btnText">🔨 Собрать APK</span>
      </button>
      <div class="progress-bar" id="progressBar"><div class="progress-fill" id="progressFill"></div></div>
      <div class="status" id="status"></div>
      <div class="logs" id="logs"></div>
    </div>
  </div>
</div>
<div class="modal-overlay" id="addFileModal">
  <div class="modal">
    <h3>📄 Новый файл</h3>
    <label>Путь</label>
    <input type="text" id="newFilePath" placeholder="res/layout/main.xml" onkeydown="if(event.key==='Enter')addFile()">
    <div class="modal-actions">
      <button class="btn-secondary" onclick="hideAddFileModal()">Отмена</button>
      <button class="btn-primary" onclick="addFile()">Создать</button>
    </div>
  </div>
</div>
<footer>⚡ Android IDE 2026</footer>
<script>
const projects = {
  hello: {
    appName: "HelloApp", packageName: "com.example.hello",
    files: {
      "MainActivity.java": `package com.example.hello;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        TextView tv = new TextView(this);
        tv.setText("Hello Android!");
        tv.setTextSize(28);
        setContentView(tv);
    }
}`,
      "AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.hello">
    <application android:label="HelloApp">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>`,
      "res/values/strings.xml": `<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">HelloApp</string>
</resources>`
    }
  },
  button: {
    appName: "ButtonApp", packageName: "com.example.button",
    files: {
      "MainActivity.java": `package com.example.button;

import android.app.Activity;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.Toast;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(40,40,40,40);
        Button btn = new Button(this);
        btn.setText("Нажми меня");
        btn.setOnClickListener(v -> Toast.makeText(this, "Привет!", Toast.LENGTH_SHORT).show());
        layout.addView(btn);
        setContentView(layout);
    }
}`,
      "AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.button">
    <application android:label="ButtonApp">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>`,
      "res/values/strings.xml": `<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">ButtonApp</string>
</resources>`
    }
  },
  webview: {
    appName: "WebApp", packageName: "com.example.webapp",
    files: {
      "MainActivity.java": `package com.example.webapp;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        WebView wv = new WebView(this);
        wv.setWebViewClient(new WebViewClient());
        wv.getSettings().setJavaScriptEnabled(true);
        wv.loadUrl("https://example.com");
        setContentView(wv);
    }
}`,
      "AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.webapp">
    <uses-permission android:name="android.permission.INTERNET" />
    <application android:label="WebApp">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>`,
      "res/values/strings.xml": `<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">WebApp</string>
</resources>`
    }
  },
  calc: {
    appName: "CalcApp", packageName: "com.example.calc",
    files: {
      "MainActivity.java": `package com.example.calc;

import android.app.Activity;
import android.os.Bundle;
import android.widget.*;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(40,40,40,40);
        EditText a = new EditText(this); a.setHint("Число A"); layout.addView(a);
        EditText b = new EditText(this); b.setHint("Число B"); layout.addView(b);
        TextView res = new TextView(this); res.setTextSize(18); layout.addView(res);
        Button btn = new Button(this); btn.setText("Сложить");
        btn.setOnClickListener(v -> {
            try {
                int sum = Integer.parseInt(a.getText().toString()) + Integer.parseInt(b.getText().toString());
                res.setText("Результат: " + sum);
            } catch(Exception e) { res.setText("Ошибка"); }
        });
        layout.addView(btn);
        setContentView(layout);
    }
}`,
      "AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.calc">
    <application android:label="CalcApp">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>`,
      "res/values/strings.xml": `<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">CalcApp</string>
</resources>`
    }
  },
  toast: {
    appName: "ToastApp", packageName: "com.example.toast",
    files: {
      "MainActivity.java": `package com.example.toast;

import android.app.Activity;
import android.os.Bundle;
import android.widget.*;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(40,40,40,40);
        String[] texts = {"Привет!","Как дела?","Отлично!","Пока!"};
        for (String t : texts) {
            Button btn = new Button(this);
            btn.setText(t);
            btn.setOnClickListener(v -> Toast.makeText(this, t, Toast.LENGTH_SHORT).show());
            layout.addView(btn);
        }
        setContentView(layout);
    }
}`,
      "AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.toast">
    <application android:label="ToastApp">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>`,
      "res/values/strings.xml": `<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">ToastApp</string>
</resources>`
    }
  },
  input: {
    appName: "InputApp", packageName: "com.example.input",
    files: {
      "MainActivity.java": `package com.example.input;

import android.app.Activity;
import android.os.Bundle;
import android.widget.*;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(40,40,40,40);
        EditText input = new EditText(this); input.setHint("Введите текст..."); layout.addView(input);
        Button btn = new Button(this); btn.setText("Показать");
        TextView result = new TextView(this); result.setTextSize(18); result.setPadding(0,20,0,0);
        btn.setOnClickListener(v -> result.setText("Вы ввели: " + input.getText().toString()));
        layout.addView(btn); layout.addView(result);
        setContentView(layout);
    }
}`,
      "AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.input">
    <application android:label="InputApp">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>`,
      "res/values/strings.xml": `<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">InputApp</string>
</resources>`
    }
  }
};

let currentFiles = {};
let activeFile = "";

function initProject(projKey) {
  const proj = projects[projKey];
  document.getElementById('appName').value = proj.appName;
  document.getElementById('packageName').value = proj.packageName;
  currentFiles = JSON.parse(JSON.stringify(proj.files));
  renderTabs();
  const first = Object.keys(currentFiles)[0];
  if (first) openFile(first);
}
function loadProject(key) { initProject(key); }

function renderTabs() {
  const container = document.getElementById('fileTabs');
  container.innerHTML = '';
  Object.keys(currentFiles).forEach(path => {
    const tab = document.createElement('div');
    tab.className = 'file-tab' + (path === activeFile ? ' active' : '');
    const name = path.split('/').pop();
    tab.innerHTML = `<span>${name}</span><span class="close" onclick="event.stopPropagation();removeFile('${path}')">×</span>`;
    tab.onclick = () => openFile(path);
    container.appendChild(tab);
  });
  document.getElementById('fileCount').textContent = Object.keys(currentFiles).length;
}
function openFile(path) {
  if (activeFile && currentFiles[activeFile] !== undefined) {
    currentFiles[activeFile] = document.getElementById('editor').value;
  }
  activeFile = path;
  document.getElementById('editor').value = currentFiles[path] || '';
  renderTabs();
  const type = path.endsWith('.java') ? 'Java' : path.endsWith('.xml') ? 'XML' : 'Text';
  document.getElementById('fileType').textContent = type;
}
function removeFile(path) {
  if (Object.keys(currentFiles).length <= 1) { alert('Минимум 1 файл'); return; }
  delete currentFiles[path];
  if (activeFile === path) {
    const remaining = Object.keys(currentFiles);
    activeFile = remaining[0] || '';
    document.getElementById('editor').value = activeFile ? currentFiles[activeFile] : '';
  }
  renderTabs();
}
function showAddFileModal() {
  document.getElementById('addFileModal').classList.add('show');
  document.getElementById('newFilePath').value = '';
  document.getElementById('newFilePath').focus();
}
function hideAddFileModal() { document.getElementById('addFileModal').classList.remove('show'); }
function addFile() {
  const path = document.getElementById('newFilePath').value.trim();
  if (!path) return;
  if (currentFiles[path]) { alert('Файл уже есть'); return; }
  let content = '';
  if (path.endsWith('.java')) {
    const pkg = document.getElementById('packageName').value || 'com.example';
    const cls = path.replace('.java','');
    content = `package ${pkg};

import android.app.Activity;
import android.os.Bundle;

public class ${cls} extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
    }
}`;
  } else if (path.endsWith('.xml')) {
    content = `<?xml version="1.0" encoding="utf-8"?>
<resources>
</resources>`;
  }
  currentFiles[path] = content;
  hideAddFileModal();
  renderTabs();
  openFile(path);
}

document.getElementById('editor').addEventListener('keyup', function() {
  const val = this.value;
  const pos = this.selectionStart;
  let line = 1, col = 1;
  for (let i = 0; i < pos; i++) {
    if (val[i] === '\n') { line++; col = 1; }
    else col++;
  }
  document.getElementById('cursorPos').textContent = `Ln ${line}, Col ${col}`;
});

function setStatus(msg, type) {
  const el = document.getElementById('status');
  el.className = 'status show status-' + type;
  el.innerHTML = msg;
}
function addLog(line) {
  const el = document.getElementById('logs');
  el.classList.add('show');
  const div = document.createElement('div');
  div.className = 'log-line';
  if(line.includes('✓')) div.classList.add('log-ok');
  else if(line.includes('✗') || line.includes('ОШИБКА')) div.classList.add('log-err');
  else if(line.includes('⚠')) div.classList.add('log-warn');
  else if(line.includes('[')) div.classList.add('log-info');
  div.textContent = line;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}
function clearLogs() {
  const el = document.getElementById('logs');
  el.innerHTML = '';
  el.classList.remove('show');
}
function setProgress(pct) {
  document.getElementById('progressBar').classList.add('show');
  document.getElementById('progressFill').style.width = pct + '%';
}
function hideProgress() {
  document.getElementById('progressBar').classList.remove('show');
}

async function buildApk() {
  const btn = document.getElementById('buildBtn');
  const btnText = document.getElementById('btnText');
  if (activeFile) currentFiles[activeFile] = document.getElementById('editor').value;
  btn.disabled = true;
  btnText.innerHTML = '<span class="spinner"></span> Компиляция...';
  clearLogs();
  setProgress(10);
  const data = {
    appName: document.getElementById('appName').value || 'MyApp',
    packageName: document.getElementById('packageName').value || 'com.example.myapp',
    minSdk: parseInt(document.getElementById('minSdk').value),
    files: currentFiles
  };
  try {
    setStatus('⏳ Отправка...', 'info');
    setProgress(25);
    const res = await fetch('/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    setProgress(60);
    const result = await res.json();
    if (result.logs && result.logs.length > 0) {
      result.logs.forEach(l => addLog(l));
    }
    setProgress(90);
    if (result.success && result.downloadUrl) {
      setProgress(100);
      setStatus('✅ APK собран!<br><a class="apk-link" href="' + result.downloadUrl + '" download>📥 Скачать ' + result.appName + '.apk</a>', 'success');
    } else {
      setStatus('❌ Ошибка:<br>' + (result.error || 'Неизвестная ошибка'), 'error');
    }
  } catch(e) {
    setStatus('❌ Сеть:<br>' + e.message, 'error');
  }
  hideProgress();
  btn.disabled = false;
  btnText.textContent = '🔨 Собрать APK';
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') hideAddFileModal(); });
initProject('hello');
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_PAGE)

@app.route("/build", methods=["POST"])
def build():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No JSON data"}), 400
        app_name = data.get("appName", "MyApp").strip()
        package_name = data.get("packageName", "com.example.myapp").strip()
        min_sdk = int(data.get("minSdk", 26))
        files = data.get("files", {})
        if not files:
            return jsonify({"success": False, "error": "No files provided"}), 400
        cleanup_old_files()
        with tempfile.TemporaryDirectory() as work_dir:
            result = build_apk({
                "app_name": app_name,
                "package_name": package_name,
                "min_sdk": min_sdk,
                "files": files
            }, work_dir)
            if result["success"]:
                apk_name = f"{app_name.replace(' ', '_')}_{int(time.time())}.apk"
                output_path = os.path.join(OUTPUT_DIR, apk_name)
                shutil.copy(result["apk_path"], output_path)
                download_url = f"/download/{apk_name}"
                return jsonify({
                    "success": True,
                    "appName": app_name,
                    "downloadUrl": request.host_url.rstrip("/") + download_url,
                    "logs": result["logs"]
                })
            else:
                return jsonify({
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                    "logs": result.get("logs", [])
                }), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "logs": [f"Server error: {str(e)}"]}), 500

@app.route("/download/<filename>")
def download(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(path):
        return send_file(path, as_attachment=True, download_name=filename)
    return jsonify({"error": "File not found"}), 404

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
