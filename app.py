import os
import sys
import tempfile
import subprocess
import traceback
from pathlib import Path

from flask import Flask, render_template_string, request, jsonify
from flask_cors import CORS
from telebot import TeleBot
from telebot.types import InputFile

app = Flask(__name__)
CORS(app)

FFMPEG_LOGS = []

def ff(*args):
    """Find ffmpeg and return full path."""
    # Try common locations
    for p in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/opt/ffmpeg/bin/ffmpeg", "ffmpeg"]:
        r = subprocess.run(["which", p], capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip():
            return [r.stdout.strip()] + list(args)
    # Last try
    return ["ffmpeg"] + list(args)


def run_cmd(cmd_list, label="cmd"):
    """Run command and capture ALL output for logs."""
    global FFMPEG_LOGS
    result = subprocess.run(cmd_list, capture_output=True, text=True, timeout=120)
    log_entry = {
        "label": label,
        "cmd": " ".join(cmd_list),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    FFMPEG_LOGS.append(log_entry)
    return result.returncode == 0, log_entry


# ── HTML / CSS / JS ────────────────────────────────────────────────────────
HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VideoNote Sender</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
  *{margin:0;padding:0;box-sizing:border-box}
  body{
    font-family:'Inter',sans-serif;
    background:#0a0a0f;
    color:#e0e0e5;
    min-height:100vh;
    display:flex;
    align-items:center;
    justify-content:center;
    padding:20px;
  }
  .container{
    width:100%;max-width:460px;
    background:#111118;
    border:1px solid #1e1e2e;
    border-radius:20px;
    padding:28px;
    box-shadow:0 8px 40px rgba(0,0,0,.5);
  }
  h1{font-size:20px;font-weight:700;color:#fff;margin-bottom:4px;display:flex;align-items:center;gap:10px}
  h1 svg{width:26px;height:26px;fill:#2aabee}
  .subtitle{font-size:12px;color:#6b6b7b;margin-bottom:20px}
  .field{margin-bottom:14px}
  label{display:block;font-size:11px;font-weight:500;color:#8a8a9a;margin-bottom:5px;text-transform:uppercase;letter-spacing:.5px}
  input[type="text"],input[type="file"]{
    width:100%;background:#0d0d14;border:1px solid #222233;border-radius:10px;
    padding:10px 12px;color:#e0e0e5;font-size:13px;font-family:inherit;outline:none;
  }
  input:focus{border-color:#2aabee;box-shadow:0 0 0 2px rgba(42,171,238,.1)}
  input[type="file"]{padding:8px 12px;cursor:pointer}
  input[type="file"]::-webkit-file-upload-button{
    background:#1a1a2a;border:1px solid #2a2a3a;border-radius:6px;
    color:#8a8a9a;padding:5px 10px;margin-right:8px;cursor:pointer;font-size:11px;
  }
  .preview-wrap{
    width:100%;aspect-ratio:1/1;background:#0d0d14;border:1px dashed #2a2a3a;
    border-radius:50%;display:flex;align-items:center;justify-content:center;
    margin-bottom:14px;overflow:hidden;
  }
  .preview-wrap video{width:100%;height:100%;object-fit:cover;border-radius:50%}
  .preview-wrap .placeholder{text-align:center;color:#4a4a5a;font-size:12px}
  .preview-wrap .placeholder svg{width:36px;height:36px;fill:#2a2a3a;margin-bottom:6px;display:block;margin:0 auto}
  .btn{
    width:100%;background:#2aabee;border:none;border-radius:10px;padding:12px;
    color:#fff;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;
  }
  .btn:hover{background:#1d9ad8}
  .btn:disabled{background:#1a3a4a;cursor:not-allowed}
  .progress-wrap{margin-top:12px;display:none}
  .progress-bar{height:5px;background:#1a1a2a;border-radius:3px;overflow:hidden}
  .progress-fill{height:100%;width:0%;background:#2aabee;border-radius:3px;transition:width .3s}
  .progress-text{text-align:center;font-size:11px;color:#8a8a9a;margin-top:5px}
  .status{
    margin-top:12px;padding:10px 12px;border-radius:8px;font-size:12px;display:none;
  }
  .status.ok{background:#0f2e1f;border:1px solid #1a4a2f;color:#4ade80}
  .status.err{background:#2e0f0f;border:1px solid #4a1a1a;color:#f87171}
  .logs-box{
    margin-top:12px;background:#0a0a12;border:1px solid #1e1e2e;border-radius:8px;
    padding:10px;font-size:10px;color:#888;font-family:monospace;max-height:200px;
    overflow-y:auto;display:none;white-space:pre-wrap;word-break:break-all;
  }
  .logs-box.show{display:block}
  .logs-title{font-size:10px;color:#555;margin-bottom:4px;text-transform:uppercase}
  .footer{margin-top:14px;text-align:center;font-size:10px;color:#3a3a4a}
</style>
</head>
<body>
<div class="container">
  <h1>
    <svg viewBox="0 0 24 24"><path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71L12.6 16.3l-1.99 1.93c-.23.23-.42.42-.83.42z"/></svg>
    VideoNote Sender
  </h1>
  <p class="subtitle">Отправка кружочков с нативной обводкой Telegram</p>

  <form id="uploadForm" enctype="multipart/form-data">
    <div class="field">
      <label>Bot Token</label>
      <input type="text" name="token" id="token" placeholder="123456:ABC-DEF..." required>
    </div>
    <div class="field">
      <label>Chat ID</label>
      <input type="text" name="chat_id" id="chat_id" placeholder="-1001234567890" required>
    </div>
    <div class="field">
      <label>Видео</label>
      <input type="file" name="video" id="video" accept="video/*" required>
    </div>

    <div class="preview-wrap" id="previewWrap">
      <div class="placeholder">
        <svg viewBox="0 0 24 24"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4zM14 13h-3v3H9v-3H6v-2h3V8h2v3h3v2z"/></svg>
        Выберите видео
      </div>
    </div>

    <button type="submit" class="btn" id="submitBtn">Отправить кружок</button>
  </form>

  <div class="progress-wrap" id="progressWrap">
    <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
    <div class="progress-text" id="progressText">0%</div>
  </div>

  <div class="status" id="status"></div>

  <div class="logs-box" id="logsBox">
    <div class="logs-title">Логи FFmpeg</div>
    <div id="logsContent"></div>
  </div>

  <div class="footer">Render-ready &middot; Docker</div>
</div>

<script>
  const videoInput = document.getElementById('video');
  const previewWrap = document.getElementById('previewWrap');
  const form = document.getElementById('uploadForm');
  const statusDiv = document.getElementById('status');
  const submitBtn = document.getElementById('submitBtn');
  const progressWrap = document.getElementById('progressWrap');
  const progressFill = document.getElementById('progressFill');
  const progressText = document.getElementById('progressText');
  const logsBox = document.getElementById('logsBox');
  const logsContent = document.getElementById('logsContent');

  function setProgress(pct, text){
    progressFill.style.width = pct + '%';
    progressText.textContent = text || (pct + '%');
    progressWrap.style.display = 'block';
  }
  function showLogs(html){
    logsContent.innerHTML = html;
    logsBox.classList.add('show');
  }

  videoInput.addEventListener('change', function(){
    const file = this.files[0];
    if(!file) return;
    previewWrap.innerHTML = `<video src="${URL.createObjectURL(file)}" autoplay loop muted playsinline></video>`;
  });

  form.addEventListener('submit', async function(e){
    e.preventDefault();
    statusDiv.style.display = 'none';
    logsBox.classList.remove('show');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Обработка...';
    setProgress(10, 'Загрузка видео...');

    try{
      const res = await fetch('/send', {method:'POST', body:new FormData(form)});
      setProgress(80, 'Обработка ответа...');
      const data = await res.json();
      setProgress(100, 'Готово!');

      statusDiv.style.display = 'block';
      if(data.ok){
        statusDiv.className = 'status ok';
        statusDiv.textContent = '✅ ' + data.message;
      } else {
        statusDiv.className = 'status err';
        statusDiv.textContent = '❌ ' + data.message;
      }

      if(data.logs){
        let html = '';
        data.logs.forEach((log, i) => {
          html += `<div style="margin-bottom:8px;border-bottom:1px solid #1a1a2a;padding-bottom:4px;">`;
          html += `<span style="color:#2aabee">[${log.label}]</span> rc=${log.returncode}<br>`;
          html += `<span style="color:#555">CMD:</span> ${log.cmd}<br>`;
          if(log.stderr) html += `<span style="color:#f87171">ERR:</span> ${log.stderr}<br>`;
          if(log.stdout) html += `<span style="color:#4ade80">OUT:</span> ${log.stdout}<br>`;
          html += `</div>`;
        });
        showLogs(html);
      }
    } catch(err){
      statusDiv.style.display = 'block';
      statusDiv.className = 'status err';
      statusDiv.textContent = '❌ Сеть: ' + err.message;
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Отправить кружок';
      setTimeout(() => { progressWrap.style.display = 'none'; }, 3000);
    }
  });
</script>
</body>
</html>
"""


# ── Video processing ───────────────────────────────────────────────────────

def make_overlay(out_path="/tmp/tg_overlay.mp4", w=800, h=800, dur=0.8, fps=30):
    frames = int(dur * fps)
    frame_dir = "/tmp/tg_frames"
    os.makedirs(frame_dir, exist_ok=True)

    try:
        from PIL import Image, ImageDraw, ImageFont
        plane_pts = [(0.18,0.35),(0.50,0.48),(0.82,0.50),(0.50,0.58),(0.35,0.82),(0.42,0.62),(0.18,0.35)]
        for i in range(frames):
            t = i / max(frames-1, 1)
            bg = Image.new('RGB', (w,h), '#120812')
            draw = ImageDraw.Draw(bg)
            cx, cy = w//2, h//2
            max_r = int((w*w+h*h)**0.5/2)
            for r in range(max_r, 0, -8):
                v = int(18 * r / max_r)
                draw.ellipse([cx-r,cy-r,cx+r,cy+r], outline=f'#{v:02x}{v//4:02x}{v//4:02x}')
            fade = min(1.0, t*2.5)
            ls = 52
            blx, bly = 32, h-32-ls
            pulse = 1.0 + 0.06*(1.0-abs(t-0.5)*2)*fade
            s = ls * pulse
            lx, ly = blx-(s-ls)/2, bly-(s-ls)/2
            pts = [(lx+p[0]*s, ly+p[1]*s) for p in plane_pts]
            draw.polygon(pts, fill=(255,255,255))
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 19)
            except:
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 19)
                except:
                    font = ImageFont.load_default()
            text = "TELEGRAM"
            bbox = draw.textbbox((0,0), text, font=font)
            tw = bbox[2]-bbox[0]
            tx, ty = w-tw-35, h-35
            for j,ch in enumerate(text):
                draw.text((tx+j*11, ty), ch, fill=(255,255,255), font=font)
            bg.save(f"{frame_dir}/frame_{i:04d}.png")

        ok, log = run_cmd(ff("-y","-framerate",str(fps),"-i",f"{frame_dir}/frame_%04d.png",
            "-c:v","libx264","-preset","fast","-crf","18","-an","-pix_fmt","yuv420p","-t",str(dur),out_path), "overlay")
        for f in os.listdir(frame_dir):
            os.unlink(os.path.join(frame_dir,f))
        os.rmdir(frame_dir)
        return ok, out_path
    except Exception as e:
        FFMPEG_LOGS.append({"label":"overlay_exc","cmd":"PIL","returncode":-1,"stderr":str(e),"stdout":""})
        return False, out_path


def process_video(input_path, output_path):
    global FFMPEG_LOGS
    FFMPEG_LOGS = []

    ok, overlay = make_overlay()
    if not ok:
        return False

    main_sq = "/tmp/main_sq.mp4"
    ok, _ = run_cmd(ff("-y","-i",input_path,"-vf",
        "crop=min(iw,ih):min(iw,ih),scale=800:800:force_original_aspect_ratio=increase,crop=800:800,setsar=1,format=yuv420p",
        "-c:v","libx264","-preset","fast","-crf","23","-an","-movflags","+faststart",main_sq), "square")
    if not ok:
        return False

    clist = "/tmp/concat.txt"
    with open(clist,"w") as f:
        f.write(f"file '{overlay}'\nfile '{main_sq}'\n")

    concat = "/tmp/concat.mp4"
    ok, _ = run_cmd(ff("-y","-f","concat","-safe","0","-i",clist,"-c","copy",concat), "concat")
    if not ok:
        return False

    mask = "/tmp/mask.png"
    ok, _ = run_cmd(ff("-y","-f","lavfi","-i","color=black:s=800x800","-vf",
        "format=rgba,geq=lum=0:a='if(lt(hypot(X-400,Y-400),390),255,if(lt(hypot(X-400,Y-400),400),lerp(0,255,(400-hypot(X-400,Y-400))/10),0))',format=rgba",
        "-frames:v","1",mask), "mask")
    if not ok:
        return False

    ok, _ = run_cmd(ff("-y","-i",concat,"-i",mask,"-filter_complex",
        "[0:v][1:v]overlay=0:0:format=auto[masked];[masked]format=yuv420p",
        "-c:v","libx264","-preset","fast","-crf","23","-an","-movflags","+faststart",output_path), "final")

    for f in [overlay, main_sq, clist, concat, mask]:
        try:
            os.unlink(f)
        except:
            pass
    return ok


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/send", methods=["POST"])
def send():
    global FFMPEG_LOGS
    token = request.form.get("token","").strip()
    chat_id = request.form.get("chat_id","").strip()
    video_file = request.files.get("video")

    if not token or not chat_id or not video_file:
        return jsonify({"ok":False,"message":"Заполните все поля","logs":[]})

    suffix = Path(video_file.filename).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_in:
        video_file.save(tmp_in)
        tmp_in_path = tmp_in.name

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_out:
        tmp_out_path = tmp_out.name

    try:
        ok = process_video(tmp_in_path, tmp_out_path)
        if not ok:
            logs = [{k:v for k,v in log.items()} for log in FFMPEG_LOGS]
            return jsonify({"ok":False,"message":"Ошибка FFmpeg — смотри логи ниже","logs":logs})

        bot = TeleBot(token)
        with open(tmp_out_path, "rb") as f:
            bot.send_video_note(chat_id=chat_id, video_note=InputFile(f), duration=None, length=800)
        return jsonify({"ok":True,"message":"Кружок отправлен!","logs":[]})

    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({"ok":False,"message":str(e),"logs":[{"label":"python_exc","cmd":"","returncode":-1,"stderr":tb,"stdout":""}]})

    finally:
        for p in (tmp_in_path, tmp_out_path):
            try:
                os.unlink(p)
            except:
                pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
