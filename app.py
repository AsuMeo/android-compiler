#!/usr/bin/env python3
"""
Android Java → APK Compiler v2
Полноценный мобильный IDE: множество файлов, ресурсы, манифест, Java, XML
"""
import os
import sys
import tempfile
import shutil
import subprocess
import time
import zipfile
import json
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
    """
    project_files = {
        "app_name": "MyApp",
        "package_name": "com.example.myapp",
        "min_sdk": 26,
        "files": {
            "MainActivity.java": "...",
            "AndroidManifest.xml": "...",
            "res/values/strings.xml": "...",
            ...
        }
    }
    """
    logs = []
    def log(msg):
        logs.append(msg)
        print(msg)

    try:
        app_name = project_files.get("app_name", "MyApp")
        package_name = project_files.get("package_name", "com.example.myapp")
        min_sdk = int(project_files.get("min_sdk", 26))
        files = project_files.get("files", {})

        log("[1/9] Создание структуры проекта...")
        src_dir = os.path.join(work_dir, "src", *package_name.split("."))
        os.makedirs(src_dir, exist_ok=True)
        res_dir = os.path.join(work_dir, "res")
        os.makedirs(res_dir, exist_ok=True)

        manifest_content = None
        has_manifest = False
        java_files_list = []
        res_files_list = []

        for filepath, content in files.items():
            filepath = filepath.strip().lstrip("/")
            if not filepath:
                continue

            full_path = os.path.join(work_dir, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            if filepath == "AndroidManifest.xml":
                has_manifest = True
                manifest_content = content
            elif filepath.endswith(".java"):
                java_files_list.append(full_path)
            elif filepath.startswith("res/"):
                res_files_list.append(full_path)

        if not has_manifest:
            log("[1/9] ⚠ Манифест не найден, генерирую автоматически...")
            main_activity = "MainActivity"
            for jf in java_files_list:
                with open(jf, "r", encoding="utf-8") as f:
                    code = f.read()
                if "extends Activity" in code or "extends AppCompatActivity" in code:
                    for line in code.split("\n"):
                        if "public class" in line:
                            main_activity = line.split("public class")[1].split("{")[0].strip().split()[0]
                            break

            manifest_content = f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{package_name}"
    android:versionCode="1"
    android:versionName="1.0">
    <uses-sdk android:minSdkVersion="{min_sdk}" android:targetSdkVersion="34" />
    <application
        android:label="{app_name}"
        android:theme="@android:style/Theme.NoTitleBar">
        <activity android:name=".{main_activity}"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>"""
            manifest_path = os.path.join(work_dir, "AndroidManifest.xml")
            with open(manifest_path, "w", encoding="utf-8") as f:
                f.write(manifest_content)
            has_manifest = True
        else:
            manifest_path = os.path.join(work_dir, "AndroidManifest.xml")

        log("[1/9] ✓ Структура создана")

        if not any(f.startswith("res/values/") for f in files.keys()):
            log("[2/9] Создание минимальных ресурсов...")
            values_dir = os.path.join(res_dir, "values")
            os.makedirs(values_dir, exist_ok=True)
            strings_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">{app_name}</string>
</resources>"""
            with open(os.path.join(values_dir, "strings.xml"), "w", encoding="utf-8") as f:
                f.write(strings_xml)
            res_files_list.append(os.path.join(values_dir, "strings.xml"))
            log("[2/9] ✓ Минимальные ресурсы созданы")
        else:
            log("[2/9] ✓ Ресурсы от пользователя")

        log("[3/9] Компиляция ресурсов (aapt2)...")
        aapt2 = os.path.join(BUILD_TOOLS, "aapt2")
        compiled_res_dir = os.path.join(work_dir, "compiled_res")
        os.makedirs(compiled_res_dir, exist_ok=True)

        compiled_files = []
        for res_file in res_files_list:
            if res_file.endswith(".xml"):
                r = subprocess.run([aapt2, "compile", "--legacy", "-o", compiled_res_dir, res_file],
                    capture_output=True, text=True)
                if r.returncode != 0:
                    log(f"[3/9] ⚠ {os.path.basename(res_file)}: {r.stderr[:200]}")
                else:
                    log(f"[3/9] ✓ {os.path.basename(res_file)}")

        # Собираем ВСЕ .flat файлы из директории — aapt2 даёт им хешированные имена
        for f in os.listdir(compiled_res_dir):
            if f.endswith(".flat"):
                compiled_files.append(os.path.join(compiled_res_dir, f))

        if not compiled_files:
            log("[3/9] ✗ Нет скомпилированных ресурсов")
            return {"success": False, "error": "No compiled resources", "logs": logs}

        log(f"[3/9] ✓ Скомпилировано ресурсов: {len(compiled_files)}")
        for cf in compiled_files:
            log(f"      → {os.path.basename(cf)}")

        log("[4/9] Линковка ресурсов (aapt2 link)...")
        r_java_dir = os.path.join(work_dir, "r_java")
        os.makedirs(r_java_dir, exist_ok=True)
        resources_ap_ = os.path.join(work_dir, "resources.ap_")

        link_args = [aapt2, "link",
            "-I", os.path.join(PLATFORM, "android.jar"),
            "--manifest", manifest_path,
            "-o", resources_ap_,
            "--java", r_java_dir,
            "--min-sdk-version", str(min_sdk),
            "--target-sdk-version", "34",
            "--version-code", "1",
            "--version-name", "1.0",
            "--auto-add-overlay"]

        for cf in compiled_files:
            link_args.extend(["-R", cf])

        r = subprocess.run(link_args, capture_output=True, text=True)
        if r.returncode != 0:
            log(f"[4/9] ✗ ОШИБКА: {r.stderr[:800]}")
            return {"success": False, "error": r.stderr[:800], "logs": logs}

        # Проверяем что resources.ap_ создан и не пустой
        if not os.path.exists(resources_ap_) or os.path.getsize(resources_ap_) < 100:
            log(f"[4/9] ✗ resources.ap_ пустой или не создан ({os.path.getsize(resources_ap_) if os.path.exists(resources_ap_) else 'не существует'} bytes)")
            return {"success": False, "error": "resources.ap_ is empty or missing", "logs": logs}

        log(f"[4/9] ✓ Ресурсы слинкованы, R.java создан (resources.ap_ = {os.path.getsize(resources_ap_)} bytes)")

        log("[5/9] Компиляция Java (javac)...")
        classes_dir = os.path.join(work_dir, "classes")
        os.makedirs(classes_dir, exist_ok=True)

        all_java = []
        for root, _, files in os.walk(os.path.join(work_dir, "src")):
            for file in files:
                if file.endswith(".java"):
                    all_java.append(os.path.join(root, file))
        for root, _, files in os.walk(r_java_dir):
            for file in files:
                if file.endswith(".java"):
                    all_java.append(os.path.join(root, file))

        if not all_java:
            log("[5/9] ✗ Нет Java файлов для компиляции")
            return {"success": False, "error": "No Java files found", "logs": logs}

        javac = os.path.join(os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-17-openjdk-amd64"), "bin", "javac")
        classpath = os.path.join(PLATFORM, "android.jar")

        r = subprocess.run([javac, "-source", "1.8", "-target", "1.8", "-cp", classpath, "-d", classes_dir] + all_java,
            capture_output=True, text=True)
        if r.returncode != 0:
            log(f"[5/9] ✗ ОШИБКА КОМПИЛЯЦИИ:")
            for line in r.stderr.split("\n")[:25]:
                log(f"  > {line}")
            return {"success": False, "error": r.stderr[:800], "logs": logs}
        log(f"[5/9] ✓ Java скомпилирован ({len(all_java)} файлов)")

        log("[6/9] Конвертация в Dalvik (d8)...")
        d8 = os.path.join(BUILD_TOOLS, "d8")
        class_files = []
        for root, _, files in os.walk(classes_dir):
            for file in files:
                if file.endswith(".class"):
                    class_files.append(os.path.join(root, file))

        r = subprocess.run([d8, "--release", "--output", work_dir, "--lib", classpath] + class_files,
            capture_output=True, text=True)
        if r.returncode != 0:
            log(f"[6/9] ✗ ОШИБКА: {r.stderr[:500]}")
            return {"success": False, "error": r.stderr[:500], "logs": logs}
        log("[6/9] ✓ Dalvik байткод создан")

        log("[7/9] Сборка APK...")
        unsigned_apk = os.path.join(work_dir, f"{app_name}_unsigned.apk")

        # Копируем resources.ap_ → unsigned_apk и добавляем classes.dex
        # resources.ap_ уже является ZIP/APK с манифестом и ресурсами
        shutil.copy(resources_ap_, unsigned_apk)

        dex_path = os.path.join(work_dir, "classes.dex")
        if os.path.exists(dex_path):
            with zipfile.ZipFile(unsigned_apk, "a", zipfile.ZIP_DEFLATED) as zf:
                zf.write(dex_path, "classes.dex")
            log(f"[7/9] ✓ APK собран, classes.dex добавлен ({os.path.getsize(dex_path)} bytes)")
        else:
            log("[7/9] ⚠ classes.dex не найден, APK без кода")

        # Проверяем размер APK
        apk_size = os.path.getsize(unsigned_apk)
        log(f"[7/9] 📦 Размер unsigned APK: {apk_size} bytes")

        log("[8/9] Подпись APK...")
        keystore = os.path.join(work_dir, "debug.keystore")
        keytool = os.path.join(os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-17-openjdk-amd64"), "bin", "keytool")

        subprocess.run([keytool, "-genkey", "-v", "-keystore", keystore, "-alias", "androiddebugkey",
            "-storepass", "android", "-keypass", "android", "-keyalg", "RSA", "-validity", "10000",
            "-dname", "CN=Android Debug,O=Android,C=US"], capture_output=True)

        apksigner = os.path.join(BUILD_TOOLS, "apksigner")
        signed_apk = os.path.join(work_dir, f"{app_name}.apk")

        r = subprocess.run([apksigner, "sign", "--ks", keystore, "--ks-pass", "pass:android",
            "--key-pass", "pass:android", "--out", signed_apk, unsigned_apk], capture_output=True, text=True)

        if r.returncode != 0:
            log(f"[8/9] ⚠ apksigner не сработал, пробую jarsigner...")
            jarsigner = os.path.join(os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-17-openjdk-amd64"), "bin", "jarsigner")
            subprocess.run([jarsigner, "-verbose", "-sigalg", "SHA1withRSA", "-digestalg", "SHA1",
                "-keystore", keystore, "-storepass", "android", unsigned_apk, "androiddebugkey"], capture_output=True)
            shutil.copy(unsigned_apk, signed_apk)

        signed_size = os.path.getsize(signed_apk)
        log(f"[8/9] ✓ APK подписан ({signed_size} bytes)")

        log("[9/9] Выравнивание (zipalign)...")
        zipalign = os.path.join(BUILD_TOOLS, "zipalign")
        aligned_apk = os.path.join(work_dir, f"{app_name}_aligned.apk")
        r = subprocess.run([zipalign, "-f", "4", signed_apk, aligned_apk], capture_output=True, text=True)

        if r.returncode == 0 and os.path.exists(aligned_apk) and os.path.getsize(aligned_apk) > 100:
            final_apk = aligned_apk
            log(f"[9/9] ✓ APK выровнен ({os.path.getsize(aligned_apk)} bytes)")
        else:
            final_apk = signed_apk
            log(f"[9/9] ⚠ zipalign пропущен, использую signed APK")

        final_size = os.path.getsize(final_apk)
        log(f"🎉 ИТОГО: APK = {final_size} bytes")

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
<title>⚡ Android IDE — Компилятор APK</title>
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

/* Файловый менеджер */
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
.logs { background:var(--bg); border:1px solid var(--border); border-radius:12px; padding:12px; font-family:'SF Mono',monospace; font-size:11px; color:var(--text2); max-height:250px; overflow-y:auto; margin-top:12px; white-space:pre-wrap; word-break:break-all; display:none; }
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
        <div><label>Название приложения</label><input type="text" id="appName" value="MyApp"></div>
        <div><label>Package name</label><input type="text" id="packageName" value="com.example.myapp"></div>
      </div>
      <div style="margin-top:10px"><label>Min SDK</label>
        <select id="minSdk">
          <option value="21">API 21 (Android 5.0)</option>
          <option value="24">API 24 (Android 7.0)</option>
          <option value="26" selected>API 26 (Android 8.0)</option>
          <option value="28">API 28 (Android 9.0)</option>
          <option value="30">API 30 (Android 11)</option>
          <option value="33">API 33 (Android 13)</option>
        </select>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-header">
      <span>📝 Файлы проекта</span>
      <span style="font-size:11px;color:var(--text2)" id="fileCount">3 файла</span>
    </div>
    <div class="card-body">
      <div class="templates-grid">
        <button class="template-btn" onclick="loadProject('hello')">👋 Hello World</button>
        <button class="template-btn" onclick="loadProject('button')">🔘 Кнопка</button>
        <button class="template-btn" onclick="loadProject('webview')">🌐 WebView</button>
        <button class="template-btn" onclick="loadProject('calc')">🔢 Калькулятор</button>
        <button class="template-btn" onclick="loadProject('toast')">💬 Toast</button>
        <button class="template-btn" onclick="loadProject('input')">⌨️ Ввод</button>
      </div>

      <div class="file-tabs" id="fileTabs"></div>
      <div class="editor-wrap">
        <textarea class="editor" id="editor" spellcheck="false"></textarea>
        <div class="editor-info">
          <span id="cursorPos">Ln 1, Col 1</span>
          <span id="fileType">Java</span>
        </div>
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
    <label>Путь к файлу</label>
    <input type="text" id="newFilePath" placeholder="res/layout/activity_main.xml" onkeydown="if(event.key==='Enter')addFile()">
    <div class="modal-actions">
      <button class="btn-secondary" onclick="hideAddFileModal()">Отмена</button>
      <button class="btn-primary" onclick="addFile()">Создать</button>
    </div>
  </div>
</div>

<footer>⚡ Android IDE 2026 • Render</footer>

<script>
const projects = {
  hello: {
    appName: "HelloApp",
    packageName: "com.example.hello",
    files: {
      "MainActivity.java": `package com.example.hello;\n\nimport android.app.Activity;\nimport android.os.Bundle;\nimport android.widget.TextView;\n\npublic class MainActivity extends Activity {\n    @Override\n    protected void onCreate(Bundle savedInstanceState) {\n        super.onCreate(savedInstanceState);\n        TextView tv = new TextView(this);\n        tv.setText("Hello Android!");\n        tv.setTextSize(28);\n        setContentView(tv);\n    }\n}`,
      "AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>\n<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n    package="com.example.hello">\n    <application android:label="HelloApp">\n        <activity android:name=".MainActivity" android:exported="true">\n            <intent-filter>\n                <action android:name="android.intent.action.MAIN" />\n                <category android:name="android.intent.category.LAUNCHER" />\n            </intent-filter>\n        </activity>\n    </application>\n</manifest>`,
      "res/values/strings.xml": `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <string name="app_name">HelloApp</string>\n</resources>`
    }
  },
  button: {
    appName: "ButtonApp",
    packageName: "com.example.button",
    files: {
      "MainActivity.java": `package com.example.button;\n\nimport android.app.Activity;\nimport android.os.Bundle;\nimport android.widget.Button;\nimport android.widget.LinearLayout;\nimport android.widget.Toast;\n\npublic class MainActivity extends Activity {\n    @Override\n    protected void onCreate(Bundle savedInstanceState) {\n        super.onCreate(savedInstanceState);\n        LinearLayout layout = new LinearLayout(this);\n        layout.setOrientation(LinearLayout.VERTICAL);\n        layout.setPadding(40, 40, 40, 40);\n        Button btn = new Button(this);\n        btn.setText("Нажми меня");\n        btn.setOnClickListener(v -> Toast.makeText(this, "Привет!", Toast.LENGTH_SHORT).show());\n        layout.addView(btn);\n        setContentView(layout);\n    }\n}`,
      "AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>\n<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n    package="com.example.button">\n    <application android:label="ButtonApp">\n        <activity android:name=".MainActivity" android:exported="true">\n            <intent-filter>\n                <action android:name="android.intent.action.MAIN" />\n                <category android:name="android.intent.category.LAUNCHER" />\n            </intent-filter>\n        </activity>\n    </application>\n</manifest>`,
      "res/values/strings.xml": `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <string name="app_name">ButtonApp</string>\n</resources>`
    }
  },
  webview: {
    appName: "WebApp",
    packageName: "com.example.webapp",
    files: {
      "MainActivity.java": `package com.example.webapp;\n\nimport android.app.Activity;\nimport android.os.Bundle;\nimport android.webkit.WebView;\nimport android.webkit.WebViewClient;\n\npublic class MainActivity extends Activity {\n    @Override\n    protected void onCreate(Bundle savedInstanceState) {\n        super.onCreate(savedInstanceState);\n        WebView wv = new WebView(this);\n        wv.setWebViewClient(new WebViewClient());\n        wv.getSettings().setJavaScriptEnabled(true);\n        wv.loadUrl("https://example.com");\n        setContentView(wv);\n    }\n}`,
      "AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>\n<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n    package="com.example.webapp">\n    <uses-permission android:name="android.permission.INTERNET" />\n    <application android:label="WebApp">\n        <activity android:name=".MainActivity" android:exported="true">\n            <intent-filter>\n                <action android:name="android.intent.action.MAIN" />\n                <category android:name="android.intent.category.LAUNCHER" />\n            </intent-filter>\n        </activity>\n    </application>\n</manifest>`,
      "res/values/strings.xml": `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <string name="app_name">WebApp</string>\n</resources>`
    }
  },
  calc: {
    appName: "CalcApp",
    packageName: "com.example.calc",
    files: {
      "MainActivity.java": `package com.example.calc;\n\nimport android.app.Activity;\nimport android.os.Bundle;\nimport android.widget.*;\n\npublic class MainActivity extends Activity {\n    @Override\n    protected void onCreate(Bundle savedInstanceState) {\n        super.onCreate(savedInstanceState);\n        LinearLayout layout = new LinearLayout(this);\n        layout.setOrientation(LinearLayout.VERTICAL);\n        layout.setPadding(40, 40, 40, 40);\n        EditText a = new EditText(this); a.setHint("Число A"); layout.addView(a);\n        EditText b = new EditText(this); b.setHint("Число B"); layout.addView(b);\n        TextView res = new TextView(this); res.setTextSize(18); layout.addView(res);\n        Button btn = new Button(this); btn.setText("Сложить");\n        btn.setOnClickListener(v -> {\n            try {\n                int sum = Integer.parseInt(a.getText().toString()) + Integer.parseInt(b.getText().toString());\n                res.setText("Результат: " + sum);\n            } catch(Exception e) { res.setText("Ошибка"); }\n        });\n        layout.addView(btn);\n        setContentView(layout);\n    }\n}`,
      "AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>\n<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n    package="com.example.calc">\n    <application android:label="CalcApp">\n        <activity android:name=".MainActivity" android:exported="true">\n            <intent-filter>\n                <action android:name="android.intent.action.MAIN" />\n                <category android:name="android.intent.category.LAUNCHER" />\n            </intent-filter>\n        </activity>\n    </application>\n</manifest>`,
      "res/values/strings.xml": `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <string name="app_name">CalcApp</string>\n</resources>`
    }
  },
  toast: {
    appName: "ToastApp",
    packageName: "com.example.toast",
    files: {
      "MainActivity.java": `package com.example.toast;\n\nimport android.app.Activity;\nimport android.os.Bundle;\nimport android.widget.*;\n\npublic class MainActivity extends Activity {\n    @Override\n    protected void onCreate(Bundle savedInstanceState) {\n        super.onCreate(savedInstanceState);\n        LinearLayout layout = new LinearLayout(this);\n        layout.setOrientation(LinearLayout.VERTICAL);\n        layout.setPadding(40, 40, 40, 40);\n        String[] texts = {"Привет!","Как дела?","Отлично!","Пока!"};\n        for (String t : texts) {\n            Button btn = new Button(this);\n            btn.setText(t);\n            btn.setOnClickListener(v -> Toast.makeText(this, t, Toast.LENGTH_SHORT).show());\n            layout.addView(btn);\n        }\n        setContentView(layout);\n    }\n}`,
      "AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>\n<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n    package="com.example.toast">\n    <application android:label="ToastApp">\n        <activity android:name=".MainActivity" android:exported="true">\n            <intent-filter>\n                <action android:name="android.intent.action.MAIN" />\n                <category android:name="android.intent.category.LAUNCHER" />\n            </intent-filter>\n        </activity>\n    </application>\n</manifest>`,
      "res/values/strings.xml": `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <string name="app_name">ToastApp</string>\n</resources>`
    }
  },
  input: {
    appName: "InputApp",
    packageName: "com.example.input",
    files: {
      "MainActivity.java": `package com.example.input;\n\nimport android.app.Activity;\nimport android.os.Bundle;\nimport android.widget.*;\n\npublic class MainActivity extends Activity {\n    @Override\n    protected void onCreate(Bundle savedInstanceState) {\n        super.onCreate(savedInstanceState);\n        LinearLayout layout = new LinearLayout(this);\n        layout.setOrientation(LinearLayout.VERTICAL);\n        layout.setPadding(40, 40, 40, 40);\n        EditText input = new EditText(this); input.setHint("Введите текст..."); layout.addView(input);\n        Button btn = new Button(this); btn.setText("Показать");\n        TextView result = new TextView(this); result.setTextSize(18); result.setPadding(0, 20, 0, 0);\n        btn.setOnClickListener(v -> result.setText("Вы ввели: " + input.getText().toString()));\n        layout.addView(btn); layout.addView(result);\n        setContentView(layout);\n    }\n}`,
      "AndroidManifest.xml": `<?xml version="1.0" encoding="utf-8"?>\n<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n    package="com.example.input">\n    <application android:label="InputApp">\n        <activity android:name=".MainActivity" android:exported="true">\n            <intent-filter>\n                <action android:name="android.intent.action.MAIN" />\n                <category android:name="android.intent.category.LAUNCHER" />\n            </intent-filter>\n        </activity>\n    </application>\n</manifest>`,
      "res/values/strings.xml": `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <string name="app_name">InputApp</string>\n</resources>`
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

function loadProject(key) {
  initProject(key);
}

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
  document.getElementById('fileCount').textContent = Object.keys(currentFiles).length + ' файла';
}

function openFile(path) {
  if (activeFile && currentFiles[activeFile] !== undefined) {
    currentFiles[activeFile] = document.getElementById('editor').value;
  }
  activeFile = path;
  document.getElementById('editor').value = currentFiles[path] || '';
  renderTabs();
  updateFileType(path);
}

function updateFileType(path) {
  const type = path.endsWith('.java') ? 'Java' : path.endsWith('.xml') ? 'XML' : 'Text';
  document.getElementById('fileType').textContent = type;
}

function removeFile(path) {
  if (Object.keys(currentFiles).length <= 1) {
    alert('Нужен минимум 1 файл');
    return;
  }
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
function hideAddFileModal() {
  document.getElementById('addFileModal').classList.remove('show');
}
function addFile() {
  const path = document.getElementById('newFilePath').value.trim();
  if (!path) return;
  if (currentFiles[path]) { alert('Файл уже существует'); return; }
  let content = '';
  if (path.endsWith('.java')) {
    const pkg = document.getElementById('packageName').value || 'com.example';
    const cls = path.replace('.java','');
    content = `package ${pkg};\n\nimport android.app.Activity;\nimport android.os.Bundle;\n\npublic class ${cls} extends Activity {\n    @Override\n    protected void onCreate(Bundle savedInstanceState) {\n        super.onCreate(savedInstanceState);\n    }\n}`;
  } else if (path.endsWith('.xml')) {
    content = `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n</resources>`;
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
    if (val[i] === '\\n') { line++; col = 1; }
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
    setStatus('⏳ Отправка проекта на сервер...', 'info');
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
      setStatus(
        '✅ APK собран!<br><a class="apk-link" href="' + result.downloadUrl + '" download>📥 Скачать ' + result.appName + '.apk</a>',
        'success'
      );
    } else {
      setStatus('❌ Ошибка сборки:<br>' + (result.error || 'Неизвестная ошибка'), 'error');
    }
  } catch(e) {
    setStatus('❌ Ошибка сети:<br>• Сервер спит (подожди 30 сек)<br>• Нет интернета<br><small>' + e.message + '</small>', 'error');
  }

  hideProgress();
  btn.disabled = false;
  btnText.textContent = '🔨 Собрать APK';
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') hideAddFileModal();
});

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
        return jsonify({
            "success": False,
            "error": str(e),
            "logs": [f"Server error: {str(e)}"]
        }), 500


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
