import os
import tempfile
import subprocess
from pathlib import Path

from flask import Flask, render_template_string, request, jsonify
from flask_cors import CORS
from telebot import TeleBot
from telebot.types import InputFile

app = Flask(__name__)
CORS(app)

# ── HTML / CSS / JS (single file) ──────────────────────────────────────────
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
    width:100%;max-width:420px;
    background:#111118;
    border:1px solid #1e1e2e;
    border-radius:20px;
    padding:32px;
    box-shadow:0 8px 40px rgba(0,0,0,.5),0 0 0 1px rgba(255,255,255,.02);
  }
  h1{
    font-size:22px;font-weight:700;
    color:#fff;margin-bottom:4px;
    display:flex;align-items:center;gap:10px;
  }
  h1 svg{width:28px;height:28px;fill:#2aabee}
  .subtitle{font-size:13px;color:#6b6b7b;margin-bottom:24px}
  .field{margin-bottom:18px}
  label{display:block;font-size:12px;font-weight:500;color:#8a8a9a;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}
  input[type="text"],input[type="file"]{
    width:100%;
    background:#0d0d14;
    border:1px solid #222233;
    border-radius:12px;
    padding:12px 14px;
    color:#e0e0e5;
    font-size:14px;
    font-family:inherit;
    outline:none;
    transition:border-color .2s,box-shadow .2s;
  }
  input[type="text"]:focus,input[type="file"]:focus{
    border-color:#2aabee;
    box-shadow:0 0 0 3px rgba(42,171,238,.12);
  }
  input[type="file"]{padding:10px 14px;cursor:pointer}
  input[type="file"]::-webkit-file-upload-button{
    background:#1a1a2a;border:1px solid #2a2a3a;border-radius:8px;
    color:#8a8a9a;padding:6px 12px;margin-right:10px;cursor:pointer;font-family:inherit;font-size:12px;
  }
  .preview-wrap{
    width:100%;aspect-ratio:1/1;
    background:#0d0d14;
    border:1px dashed #2a2a3a;
    border-radius:50%;
    display:flex;align-items:center;justify-content:center;
    margin-bottom:18px;overflow:hidden;position:relative;
  }
  .preview-wrap video{
    width:100%;height:100%;object-fit:cover;border-radius:50%;
  }
  .preview-wrap .placeholder{
    text-align:center;color:#4a4a5a;font-size:13px;
  }
  .preview-wrap .placeholder svg{width:40px;height:40px;fill:#2a2a3a;margin-bottom:8px;display:block;margin-left:auto;margin-right:auto}
  .btn{
    width:100%;
    background:#2aabee;
    border:none;
    border-radius:12px;
    padding:14px;
    color:#fff;
    font-size:15px;
    font-weight:600;
    font-family:inherit;
    cursor:pointer;
    transition:background .2s,transform .1s;
  }
  .btn:hover{background:#1d9ad8}
  .btn:active{transform:scale(.98)}
  .btn:disabled{background:#1a3a4a;cursor:not-allowed}
  .status{
    margin-top:14px;
    padding:12px 14px;
    border-radius:10px;
    font-size:13px;
    display:none;
  }
  .status.ok{background:#0f2e1f;border:1px solid #1a4a2f;color:#4ade80}
  .status.err{background:#2e0f0f;border:1px solid #4a1a1a;color:#f87171}
  .spinner{
    display:none;width:18px;height:18px;border:2px solid rgba(255,255,255,.2);
    border-top-color:#fff;border-radius:50%;animation:spin .8s linear infinite;
    margin-right:8px;vertical-align:middle;
  }
  @keyframes spin{to{transform:rotate(360deg)}}
  .footer{
    margin-top:18px;text-align:center;font-size:11px;color:#3a3a4a;
  }
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
      <input type="text" name="chat_id" id="chat_id" placeholder="-1001234567890 или 123456789" required>
    </div>
    <div class="field">
      <label>Видео</label>
      <input type="file" name="video" id="video" accept="video/*" required>
    </div>

    <div class="preview-wrap" id="previewWrap">
      <div class="placeholder">
        <svg viewBox="0 0 24 24"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4zM14 13h-3v3H9v-3H6v-2h3V8h2v3h3v2z"/></svg>
        Выберите видео для предпросмотра
      </div>
    </div>

    <button type="submit" class="btn" id="submitBtn">
      <span class="spinner" id="spinner"></span>
      <span id="btnText">Отправить кружок</span>
    </button>
  </form>

  <div class="status" id="status"></div>
  <div class="footer">Telegram VideoNote Bot &middot; Render-ready</div>
</div>

<script>
  const videoInput = document.getElementById('video');
  const previewWrap = document.getElementById('previewWrap');
  const form = document.getElementById('uploadForm');
  const statusDiv = document.getElementById('status');
  const submitBtn = document.getElementById('submitBtn');
  const spinner = document.getElementById('spinner');
  const btnText = document.getElementById('btnText');

  videoInput.addEventListener('change', function(){
    const file = this.files[0];
    if(!file) return;
    const url = URL.createObjectURL(file);
    previewWrap.innerHTML = `<video src="${url}" autoplay loop muted playsinline></video>`;
  });

  form.addEventListener('submit', async function(e){
    e.preventDefault();
    const formData = new FormData(form);
    statusDiv.style.display = 'none';
    submitBtn.disabled = true;
    spinner.style.display = 'inline-block';
    btnText.textContent = 'Обработка...';

    try{
      const res = await fetch('/send', {method:'POST', body:formData});
      const data = await res.json();
      statusDiv.style.display = 'block';
      if(data.ok){
        statusDiv.className = 'status ok';
        statusDiv.textContent = '✅ ' + data.message;
      } else {
        statusDiv.className = 'status err';
        statusDiv.textContent = '❌ ' + data.message;
      }
    } catch(err){
      statusDiv.style.display = 'block';
      statusDiv.className = 'status err';
      statusDiv.textContent = '❌ Ошибка сети: ' + err.message;
    } finally {
      submitBtn.disabled = false;
      spinner.style.display = 'none';
      btnText.textContent = 'Отправить кружок';
    }
  });
</script>
</body>
</html>
"""


def create_tg_overlay(width=800, height=800, duration=0.8, fps=30, out_path="/tmp/tg_overlay.mp4"):
    """
    Generate animated Telegram video_note intro using Pillow + FFmpeg.
    Matches the screenshot: dark background, white paper-plane logo bottom-left,
    'TELEGRAM' text bottom-right rotated, gentle fade-in animation.
    """
    frames = int(duration * fps)
    frame_dir = "/tmp/tg_frames"
    os.makedirs(frame_dir, exist_ok=True)

    try:
        from PIL import Image, ImageDraw, ImageFont
        has_pil = True
    except ImportError:
        has_pil = False

    if has_pil:
        # Paper plane polygon points (normalized 0-1)
        plane_pts = [
            (0.18, 0.35), (0.50, 0.48), (0.82, 0.50),
            (0.50, 0.58), (0.35, 0.82), (0.42, 0.62), (0.18, 0.35)
        ]

        for i in range(frames):
            t = i / max(frames - 1, 1)

            # Dark purple-black background
            bg = Image.new('RGB', (width, height), '#120812')
            draw = ImageDraw.Draw(bg)

            # Subtle radial vignette
            cx, cy = width // 2, height // 2
            max_r = int((width**2 + height**2) ** 0.5 / 2)
            for r in range(max_r, 0, -8):
                ratio = r / max_r
                v = int(18 * ratio)
                draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                             outline=f'#{v:02x}{v//4:02x}{v//4:02x}')

            # Fade-in factor
            fade = min(1.0, t * 2.5)

            # Paper plane logo (bottom-left)
            logo_size = 52
            base_lx, base_ly = 32, height - 32 - logo_size

            # Gentle scale pulse during fade
            pulse = 1.0 + 0.06 * (1.0 - abs(t - 0.5) * 2) * fade
            s = logo_size * pulse
            lx = base_lx - (s - logo_size) / 2
            ly = base_ly - (s - logo_size) / 2

            pts = [(lx + p[0]*s, ly + p[1]*s) for p in plane_pts]
            white = (255, 255, 255)
            draw.polygon(pts, fill=white)

            # TELEGRAM text (bottom-right, rotated ~-15deg)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 19)
            except:
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 19)
                except:
                    font = ImageFont.load_default()

            text = "TELEGRAM"
            # Position bottom-right
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            tx = width - tw - 35
            ty = height - 35

            # Draw with slight transparency
            for j, ch in enumerate(text):
                char_x = tx + j * 11
                draw.text((char_x, ty), ch, fill=(255, 255, 255), font=font)

            bg.save(f"{frame_dir}/frame_{i:04d}.png")

        # Encode frames to MP4
        cmd = (
            f'ffmpeg -y -framerate {fps} -i "{frame_dir}/frame_%04d.png" '
            f'-c:v libx264 -preset fast -crf 18 -an -pix_fmt yuv420p '
            f'-t {duration} "{out_path}"'
        )
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        # Cleanup frames
        for f in os.listdir(frame_dir):
            os.unlink(os.path.join(frame_dir, f))
        os.rmdir(frame_dir)

        return r.returncode == 0, out_path

    else:
        # Fallback: pure ffmpeg
        cmd = (
            f'ffmpeg -y -f lavfi -i color=c=#120812:s={width}x{height}:r={fps} '
            f'-vf "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:'
            f'text=\'TELEGRAM\':x=w-tw-35:y=h-th-30:fontcolor=white@0.35:fontsize=18:'
            f'enable=\'between(t\\,0\\,{duration})\','
            f'drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:'
            f'text=\'\\u27A4\':x=35:y=h-70:fontcolor=white@0.85:fontsize=45:'
            f'enable=\'between(t\\,0\\,{duration})\'" '
            f'-c:v libx264 -preset fast -crf 18 -an -pix_fmt yuv420p '
            f'-t {duration} "{out_path}"'
        )
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return r.returncode == 0, out_path


def process_video_with_overlay(input_path: str, output_path: str) -> bool:
    """
    Pipeline:
    1. Generate Telegram overlay intro (0.8s)
    2. Crop input to square 800x800
    3. Concatenate: overlay + main video
    4. Apply circular mask with black border
    5. Output as MP4 ready for video_note
    """

    # Step 1: Create overlay animation
    overlay_ok, overlay_path = create_tg_overlay()
    if not overlay_ok:
        return False

    # Step 2: Prepare main video (square crop, 800x800, no audio)
    main_sq = "/tmp/main_square.mp4"
    cmd_sq = (
        f'ffmpeg -y -i "{input_path}" -vf '
        f'"crop=min(iw\\,ih):min(iw\\,ih),'
        f'scale=800:800:force_original_aspect_ratio=increase,'
        f'crop=800:800,setsar=1,format=yuv420p" '
        f'-c:v libx264 -preset fast -crf 23 -an -movflags +faststart "{main_sq}"'
    )
    r1 = subprocess.run(cmd_sq, shell=True, capture_output=True, text=True)
    if r1.returncode != 0:
        return False

    # Step 3: Concatenate overlay + main video
    concat_list = "/tmp/concat_list.txt"
    with open(concat_list, "w") as f:
        f.write(f"file '{overlay_path}'\n")
        f.write(f"file '{main_sq}'\n")

    concat_out = "/tmp/concatenated.mp4"
    cmd_concat = f'ffmpeg -y -f concat -safe 0 -i "{concat_list}" -c copy "{concat_out}"'
    r2 = subprocess.run(cmd_concat, shell=True, capture_output=True, text=True)
    if r2.returncode != 0:
        return False

    # Step 4: Apply circular mask with smooth black border
    mask_path = "/tmp/circle_mask_800.png"
    cmd_mask = (
        f'ffmpeg -y -f lavfi -i color=black:s=800x800 -vf '
        f'"format=rgba,'
        f'geq=lum=0:a=\'if(lt(hypot(X-400,Y-400),390),255,'
        f'if(lt(hypot(X-400,Y-400),400),lerp(0,255,(400-hypot(X-400,Y-400))/10),0))\','
        f'format=rgba" -frames:v 1 "{mask_path}"'
    )
    r3 = subprocess.run(cmd_mask, shell=True, capture_output=True, text=True)
    if r3.returncode != 0:
        return False

    # Apply mask to concatenated video
    cmd_final = (
        f'ffmpeg -y -i "{concat_out}" -i "{mask_path}" -filter_complex '
        f'"[0:v][1:v]overlay=0:0:format=auto[masked];'
        f'[masked]format=yuv420p" '
        f'-c:v libx264 -preset fast -crf 23 -an -movflags +faststart "{output_path}"'
    )
    r4 = subprocess.run(cmd_final, shell=True, capture_output=True, text=True)

    # Cleanup temp files
    for f in [overlay_path, main_sq, concat_list, concat_out, mask_path]:
        try:
            os.unlink(f)
        except:
            pass

    return r4.returncode == 0


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/send", methods=["POST"])
def send():
    token = request.form.get("token", "").strip()
    chat_id = request.form.get("chat_id", "").strip()
    video_file = request.files.get("video")

    if not token or not chat_id or not video_file:
        return jsonify({"ok": False, "message": "Заполните все поля"}), 400

    suffix = Path(video_file.filename).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_in:
        video_file.save(tmp_in)
        tmp_in_path = tmp_in.name

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_out:
        tmp_out_path = tmp_out.name

    try:
        ok = process_video_with_overlay(tmp_in_path, tmp_out_path)
        if not ok:
            return jsonify({"ok": False, "message": "Ошибка обработки видео (FFmpeg)"}), 500

        bot = TeleBot(token)
        with open(tmp_out_path, "rb") as f:
            bot.send_video_note(chat_id=chat_id, video_note=InputFile(f),
                                duration=None, length=800)
        return jsonify({"ok": True, "message": "Кружок отправлен!"})

    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

    finally:
        for p in (tmp_in_path, tmp_out_path):
            try:
                os.unlink(p)
            except Exception:
                pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
