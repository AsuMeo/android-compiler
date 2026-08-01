#!/usr/bin/env python3
"""
Android Java → APK Compiler
Один сайт на Render: интерфейс + компиляция
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


def build_apk(app_name, package_name, min_sdk, java_code, work_dir):
    logs = []
    def log(msg):
        logs.append(msg)
        print(msg)

    try:
        log("[1/8] Создание структуры проекта...")
        src_dir = os.path.join(work_dir, "src", *package_name.split("."))
        os.makedirs(src_dir, exist_ok=True)
        res_dir = os.path.join(work_dir, "res")
        os.makedirs(os.path.join(res_dir, "values"), exist_ok=True)

        main_java = os.path.join(src_dir, "MainActivity.java")
        with open(main_java, "w", encoding="utf-8") as f:
            f.write(java_code)
        log("[1/8] ✓ MainActivity.java создан")

        log("[2/8] Создание AndroidManifest.xml...")
        manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{package_name}"
    android:versionCode="1"
    android:versionName="1.0">
    <uses-sdk android:minSdkVersion="{min_sdk}" android:targetSdkVersion="34" />
    <application
        android:label="{app_name}"
        android:theme="@android:style/Theme.Light.NoActionBar">
        <activity android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>"""
        with open(os.path.join(work_dir, "AndroidManifest.xml"), "w", encoding="utf-8") as f:
            f.write(manifest)
        log("[2/8] ✓ AndroidManifest.xml создан")

        log("[3/8] Создание ресурсов...")
        strings_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">{app_name}</string>
</resources>"""
        with open(os.path.join(res_dir, "values", "strings.xml"), "w", encoding="utf-8") as f:
            f.write(strings_xml)
        log("[3/8] ✓ Ресурсы созданы")

        log("[4/8] Компиляция ресурсов (aapt2)...")
        aapt2 = os.path.join(BUILD_TOOLS, "aapt2")
        compiled_res_dir = os.path.join(work_dir, "compiled_res")
        os.makedirs(compiled_res_dir, exist_ok=True)

        # Компилируем каждый XML-файл отдельно, а не всю директорию
        strings_xml_path = os.path.join(res_dir, "values", "strings.xml")
        flat_file = os.path.join(compiled_res_dir, "strings.arsc.flat")
        r = subprocess.run([aapt2, "compile", "--legacy", "-o", compiled_res_dir, strings_xml_path],
            capture_output=True, text=True)
        if r.returncode != 0:
            log(f"[4/8] ⚠ Предупреждение aapt2 compile: {r.stderr[:300]}")
        else:
            log("[4/8] ✓ strings.xml скомпилирован")

        r_java_dir = os.path.join(work_dir, "r_java")
        os.makedirs(r_java_dir, exist_ok=True)

        compiled_files = []
        for f in os.listdir(compiled_res_dir):
            if f.endswith(".flat"):
                compiled_files.append(os.path.join(compiled_res_dir, f))

        link_args = [aapt2, "link", "-I", os.path.join(PLATFORM, "android.jar"),
            "--manifest", os.path.join(work_dir, "AndroidManifest.xml"),
            "-o", os.path.join(work_dir, "resources.ap_"),
            "--java", r_java_dir, "--min-sdk-version", str(min_sdk),
            "--target-sdk-version", "34", "--version-code", "1", "--version-name", "1.0",
            "--auto-add-overlay"]

        for cf in compiled_files:
            link_args.extend(["-R", cf])

        r = subprocess.run(link_args, capture_output=True, text=True)
        if r.returncode != 0:
            log(f"[4/8] ✗ ОШИБКА: {r.stderr[:500]}")
            return {"success": False, "error": r.stderr[:500], "logs": logs}
        log("[4/8] ✓ Ресурсы скомпилированы")

        log("[5/8] Компиляция Java (javac)...")
        classes_dir = os.path.join(work_dir, "classes")
        os.makedirs(classes_dir, exist_ok=True)

        java_files = []
        for root, _, files in os.walk(src_dir):
            for file in files:
                if file.endswith(".java"):
                    java_files.append(os.path.join(root, file))
        for root, _, files in os.walk(r_java_dir):
            for file in files:
                if file.endswith(".java"):
                    java_files.append(os.path.join(root, file))

        javac = os.path.join(os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-17-openjdk-amd64"), "bin", "javac")
        classpath = os.path.join(PLATFORM, "android.jar")

        r = subprocess.run([javac, "-source", "1.8", "-target", "1.8", "-cp", classpath, "-d", classes_dir] + java_files, capture_output=True, text=True)
        if r.returncode != 0:
            log(f"[5/8] ✗ ОШИБКА КОМПИЛЯЦИИ:")
            for line in r.stderr.split("\n")[:20]:
                log(f"  > {line}")
            return {"success": False, "error": r.stderr[:500], "logs": logs}
        log("[5/8] ✓ Java скомпилирован")

        log("[6/8] Конвертация в Dalvik (d8)...")
        d8 = os.path.join(BUILD_TOOLS, "d8")
        class_files = []
        for root, _, files in os.walk(classes_dir):
            for file in files:
                if file.endswith(".class"):
                    class_files.append(os.path.join(root, file))

        r = subprocess.run([d8, "--release", "--output", work_dir, "--lib", classpath] + class_files, capture_output=True, text=True)
        if r.returncode != 0:
            log(f"[6/8] ✗ ОШИБКА: {r.stderr[:500]}")
            return {"success": False, "error": r.stderr[:500], "logs": logs}
        log("[6/8] ✓ Dalvik байткод создан")

        log("[7/8] Сборка APK...")
        unsigned_apk = os.path.join(work_dir, f"{app_name}_unsigned.apk")
        shutil.copy(os.path.join(work_dir, "resources.ap_"), unsigned_apk)

        with zipfile.ZipFile(unsigned_apk, "a", zipfile.ZIP_DEFLATED) as zf:
            dex_path = os.path.join(work_dir, "classes.dex")
            if os.path.exists(dex_path):
                zf.write(dex_path, "classes.dex")
        log("[7/8] ✓ APK собран")

        log("[8/8] Подпись APK...")
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
            jarsigner = os.path.join(os.environ.get("JAVA_HOME", "/usr/lib/jvm/java-17-openjdk-amd64"), "bin", "jarsigner")
            subprocess.run([jarsigner, "-verbose", "-sigalg", "SHA1withRSA", "-digestalg", "SHA1",
                "-keystore", keystore, "-storepass", "android", unsigned_apk, "androiddebugkey"], capture_output=True)
            shutil.copy(unsigned_apk, signed_apk)

        zipalign = os.path.join(BUILD_TOOLS, "zipalign")
        aligned_apk = os.path.join(work_dir, f"{app_name}_aligned.apk")
        r = subprocess.run([zipalign, "-f", "4", signed_apk, aligned_apk], capture_output=True, text=True)

        final_apk = aligned_apk if r.returncode == 0 and os.path.exists(aligned_apk) else signed_apk
        log("[8/8] ✓ APK подписан и готов!")

        return {"success": True, "apk_path": final_apk, "logs": logs}

    except Exception as e:
        log(f"✗ ИСКЛЮЧЕНИЕ: {str(e)}")
        return {"success": False, "error": str(e), "logs": logs}


HTML_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>⚡ Java → APK Compiler</title>
<style>
:root { --bg:#0a0a0f; --bg2:#12121a; --bg3:#1a1a2e; --border:#2a2a3e; --text:#e0e0ff; --text2:#8b8bb5; --accent:#7c3aed; --accent2:#a855f7; --accent3:#c084fc; --success:#22c55e; --error:#ef4444; }
* { margin:0; padding:0; box-sizing:border-box; }
body { background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; min-height:100vh; line-height:1.5; }
.glow { position:fixed; width:400px; height:400px; border-radius:50%; background:radial-gradient(circle,var(--accent) 0%,transparent 70%); opacity:.08; pointer-events:none; z-index:0; }
.glow-1 { top:-100px; left:-100px; }
.glow-2 { bottom:-100px; right:-100px; background:radial-gradient(circle,var(--accent2) 0%,transparent 70%); }
header { background:rgba(10,10,15,.8); backdrop-filter:blur(20px); border-bottom:1px solid var(--border); padding:16px 20px; position:sticky; top:0; z-index:100; }
header h1 { font-size:18px; font-weight:700; background:linear-gradient(135deg,var(--accent3),var(--accent2)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; display:flex; align-items:center; gap:10px; }
header h1::before { content:"⚡"; -webkit-text-fill-color:var(--accent3); }
.container { max-width:900px; margin:0 auto; padding:20px; position:relative; z-index:1; }
.card { background:var(--bg2); border:1px solid var(--border); border-radius:20px; margin-bottom:16px; overflow:hidden; transition:border-color .3s; }
.card:hover { border-color:rgba(124,58,237,.3); }
.card-header { background:var(--bg3); padding:14px 20px; font-size:13px; font-weight:600; color:var(--text2); text-transform:uppercase; letter-spacing:1px; display:flex; align-items:center; gap:8px; }
.card-body { padding:20px; }
label { display:block; font-size:12px; font-weight:500; color:var(--text2); margin-bottom:6px; text-transform:uppercase; letter-spacing:.5px; }
input,select,textarea { width:100%; background:var(--bg); border:1px solid var(--border); border-radius:12px; padding:12px 16px; color:var(--text); font-size:14px; outline:none; transition:all .2s; font-family:'SF Mono','Fira Code',monospace; }
input:focus,select:focus,textarea:focus { border-color:var(--accent); box-shadow:0 0 0 3px rgba(124,58,237,.1); }
textarea { min-height:320px; resize:vertical; line-height:1.7; font-size:13px; }
.templates { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:12px; }
.template-btn { padding:8px 16px; background:var(--bg3); border:1px solid var(--border); border-radius:10px; font-size:12px; font-weight:500; color:var(--text2); cursor:pointer; transition:all .2s; }
.template-btn:hover { background:rgba(124,58,237,.15); border-color:var(--accent); color:var(--text); }
.template-btn:active { transform:scale(.96); }
.build-btn { width:100%; padding:16px; background:linear-gradient(135deg,var(--accent),var(--accent2)); border:none; border-radius:14px; color:#fff; font-size:16px; font-weight:700; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:10px; transition:all .2s; box-shadow:0 4px 20px rgba(124,58,237,.3); }
.build-btn:hover { transform:translateY(-2px); box-shadow:0 6px 30px rgba(124,58,237,.4); }
.build-btn:active { transform:translateY(0); }
.build-btn:disabled { opacity:.5; cursor:not-allowed; transform:none; }
.spinner { width:18px; height:18px; border:2px solid rgba(255,255,255,.3); border-top-color:#fff; border-radius:50%; animation:spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
.status { margin-top:16px; padding:16px; border-radius:14px; font-size:14px; display:none; animation:fadeIn .3s; }
@keyframes fadeIn { from{opacity:0;transform:translateY(-10px)} to{opacity:1;transform:translateY(0)} }
.status.show { display:block; }
.status-info { background:rgba(124,58,237,.1); border:1px solid rgba(124,58,237,.2); color:var(--accent3); }
.status-success { background:rgba(34,197,94,.1); border:1px solid rgba(34,197,94,.2); color:var(--success); }
.status-error { background:rgba(239,68,68,.1); border:1px solid rgba(239,68,68,.2); color:var(--error); }
.apk-link { display:block; margin-top:14px; padding:16px; background:linear-gradient(135deg,var(--success),#16a34a); color:#fff; text-align:center; border-radius:14px; text-decoration:none; font-weight:700; font-size:15px; box-shadow:0 4px 20px rgba(34,197,94,.3); transition:all .2s; }
.apk-link:hover { transform:translateY(-2px); box-shadow:0 6px 30px rgba(34,197,94,.4); }
.logs { background:var(--bg); border:1px solid var(--border); border-radius:12px; padding:14px; font-family:'SF Mono',monospace; font-size:11px; color:var(--text2); max-height:300px; overflow-y:auto; margin-top:14px; white-space:pre-wrap; word-break:break-all; display:none; }
.logs.show { display:block; }
.log-line { padding:2px 0; border-bottom:1px solid rgba(42,42,62,.3); }
.log-line:last-child { border-bottom:none; }
.log-ok { color:var(--success); }
.log-err { color:var(--error); }
.log-info { color:var(--accent3); }
.progress-bar { width:100%; height:4px; background:var(--bg3); border-radius:2px; margin-top:12px; overflow:hidden; display:none; }
.progress-bar.show { display:block; }
.progress-fill { height:100%; background:linear-gradient(90deg,var(--accent),var(--accent2)); width:0%; transition:width .3s; border-radius:2px; }
.hint { font-size:12px; color:var(--text2); margin-top:8px; line-height:1.6; }
footer { text-align:center; padding:24px; font-size:12px; color:var(--text2); }
.row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
@media(max-width:600px){ .row{grid-template-columns:1fr} }
</style>
</head>
<body>
<div class="glow glow-1"></div><div class="glow glow-2"></div>
<header><h1>Java → APK Compiler</h1></header>
<div class="container">
  <div class="card">
    <div class="card-header">⚙️ Настройки приложения</div>
    <div class="card-body">
      <div class="row">
        <div><label>Название приложения</label><input type="text" id="appName" value="MyApp"></div>
        <div><label>Package name</label><input type="text" id="packageName" value="com.example.myapp"></div>
      </div>
      <div style="margin-top:12px"><label>Min SDK</label>
        <select id="minSdk">
          <option value="21">API 21 (Android 5.0)</option>
          <option value="24">API 24 (Android 7.0)</option>
          <option value="26" selected>API 26 (Android 8.0)</option>
          <option value="28">API 28 (Android 9.0)</option>
          <option value="30">API 30 (Android 11)</option>
        </select>
      </div>
    </div>
  </div>
  <div class="card">
    <div class="card-header">📝 Java код</div>
    <div class="card-body">
      <div class="templates">
        <button class="template-btn" onclick="loadTemplate('hello')">👋 Hello</button>
        <button class="template-btn" onclick="loadTemplate('button')">🔘 Кнопка</button>
        <button class="template-btn" onclick="loadTemplate('webview')">🌐 WebView</button>
        <button class="template-btn" onclick="loadTemplate('calc')">🔢 Калькулятор</button>
        <button class="template-btn" onclick="loadTemplate('toast')">💬 Toast</button>
        <button class="template-btn" onclick="loadTemplate('input')">⌨️ Ввод</button>
      </div>
      <textarea id="javaCode" spellcheck="false">package com.example.myapp;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        TextView tv = new TextView(this);
        tv.setText("Hello World!");
        tv.setTextSize(24);
        setContentView(tv);
    }
}</textarea>
      <div class="hint">Пиши код класса MainActivity. AndroidManifest, ресурсы и R.java соберутся автоматически.</div>
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
<footer>⚡ Java → APK Compiler 2026 • Render</footer>

<script>
const templates = {
  hello: `package com.example.myapp;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        TextView tv = new TextView(this);
        tv.setText("Hello World!");
        tv.setTextSize(24);
        setContentView(tv);
    }
}`,
  button: `package com.example.myapp;

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
        layout.setPadding(40, 40, 40, 40);
        Button btn = new Button(this);
        btn.setText("Нажми меня");
        btn.setOnClickListener(v -> Toast.makeText(this, "Привет!", Toast.LENGTH_SHORT).show());
        layout.addView(btn);
        setContentView(layout);
    }
}`,
  webview: `package com.example.myapp;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        WebView webView = new WebView(this);
        webView.setWebViewClient(new WebViewClient());
        webView.getSettings().setJavaScriptEnabled(true);
        webView.loadUrl("https://example.com");
        setContentView(webView);
    }
}`,
  calc: `package com.example.myapp;

import android.app.Activity;
import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(40, 40, 40, 40);
        EditText a = new EditText(this); a.setHint("Число A"); layout.addView(a);
        EditText b = new EditText(this); b.setHint("Число B"); layout.addView(b);
        TextView result = new TextView(this); result.setTextSize(18); layout.addView(result);
        Button btn = new Button(this); btn.setText("Сложить");
        btn.setOnClickListener(v -> {
            try {
                int sum = Integer.parseInt(a.getText().toString()) + Integer.parseInt(b.getText().toString());
                result.setText("Результат: " + sum);
            } catch(Exception e) { result.setText("Ошибка ввода"); }
        });
        layout.addView(btn);
        setContentView(layout);
    }
}`,
  toast: `package com.example.myapp;

import android.app.Activity;
import android.os.Bundle;
import android.widget.LinearLayout;
import android.widget.Button;
import android.widget.Toast;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(40, 40, 40, 40);
        String[] texts = {"Привет!", "Как дела?", "Отлично!", "Пока!"};
        for (String text : texts) {
            Button btn = new Button(this);
            btn.setText(text);
            btn.setOnClickListener(v -> Toast.makeText(this, text, Toast.LENGTH_SHORT).show());
            layout.addView(btn);
        }
        setContentView(layout);
    }
}`,
  input: `package com.example.myapp;

import android.app.Activity;
import android.os.Bundle;
import android.widget.EditText;
import android.widget.Button;
import android.widget.TextView;
import android.widget.LinearLayout;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(40, 40, 40, 40);
        EditText input = new EditText(this); input.setHint("Введите текст..."); layout.addView(input);
        Button btn = new Button(this); btn.setText("Показать");
        TextView result = new TextView(this); result.setTextSize(18); result.setPadding(0, 20, 0, 0);
        btn.setOnClickListener(v -> {
            String text = input.getText().toString();
            result.setText("Вы ввели: " + text);
        });
        layout.addView(btn); layout.addView(result);
        setContentView(layout);
    }
}`
};

function loadTemplate(name) {
  document.getElementById('javaCode').value = templates[name];
}

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
  if(line.includes('✓') || line.includes('✓')) div.classList.add('log-ok');
  else if(line.includes('✗') || line.includes('ОШИБКА')) div.classList.add('log-err');
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
  const bar = document.getElementById('progressBar');
  const fill = document.getElementById('progressFill');
  bar.classList.add('show');
  fill.style.width = pct + '%';
}

function hideProgress() {
  document.getElementById('progressBar').classList.remove('show');
}

async function buildApk() {
  const btn = document.getElementById('buildBtn');
  const btnText = document.getElementById('btnText');

  btn.disabled = true;
  btnText.innerHTML = '<span class="spinner"></span> Компиляция...';
  clearLogs();
  setProgress(10);

  const data = {
    appName: document.getElementById('appName').value || 'MyApp',
    packageName: document.getElementById('packageName').value || 'com.example.myapp',
    minSdk: parseInt(document.getElementById('minSdk').value),
    javaCode: document.getElementById('javaCode').value
  };

  try {
    setStatus('⏳ Отправка кода на сервер...', 'info');
    setProgress(20);

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
        '✅ APK собран успешно!<br><a class="apk-link" href="' + result.downloadUrl + '" download>📥 Скачать ' + result.appName + '.apk</a>',
        'success'
      );
    } else {
      setStatus('❌ Ошибка сборки:<br>' + (result.error || 'Неизвестная ошибка'), 'error');
    }
  } catch(e) {
    setStatus('❌ Ошибка сети. Возможные причины:<br>• Сервер спит (подожди 30 сек)<br>• Нет интернета<br>• CORS блокировка<br><small>' + e.message + '</small>', 'error');
  }

  hideProgress();
  btn.disabled = false;
  btnText.textContent = '🔨 Собрать APK';
}
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
        java_code = data.get("javaCode", "").strip()

        if not java_code:
            return jsonify({"success": False, "error": "Java code is empty"}), 400

        cleanup_old_files()

        with tempfile.TemporaryDirectory() as work_dir:
            result = build_apk(app_name, package_name, min_sdk, java_code, work_dir)

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
