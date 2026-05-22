#!/usr/bin/env python3
import os
import subprocess
import time
import urllib.parse
from flask import Flask, jsonify, send_from_directory, render_template_string, request
from flask_cors import CORS

# === Настройки ===
PORT = 8000
FOLDER = os.path.expanduser("~/Videos")  # Папка, где лежат твои фильмы
HLS_CACHE = os.path.join(FOLDER, ".hls_cache")  # Скрытая папка для кусков HLS
GITHUB_PAGES_URL = "https://varoes.github.io/"  # Ссылка на твой будущий плеер

# Разрешенные форматы
MEDIA_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.mp3', '.wav', '.flac'}

os.makedirs(FOLDER, exist_ok=True)
os.makedirs(HLS_CACHE, exist_ok=True)

app = Flask(__name__)
# Разрешаем твоему GitHub Pages забирать видео с этого сервера
CORS(app, resources={r"/stream/*": {"origins": "*"}})

def get_media_files():
    try:
        files = []
        for f in os.listdir(FOLDER):
            if os.path.isfile(os.path.join(FOLDER, f)):
                ext = os.path.splitext(f)[1].lower()
                if ext in MEDIA_EXTS:
                    files.append(f)
        return sorted(files)
    except OSError:
        return []

def sizeof_fmt(num):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"

# ==========================================
# 1. МАРШРУТ: ГЛАВНАЯ СТРАНИЦА (ГАЛЕРЕЯ)
# ==========================================
@app.route('/')
def index():
    files = get_media_files()
    cards_html = ""
    
    for f in files:
        full_path = os.path.join(FOLDER, f)
        ext = os.path.splitext(f)[1].lower()
        size = sizeof_fmt(os.path.getsize(full_path))
        safe_name = urllib.parse.quote(f)
        
        # Определяем иконку
        is_audio = ext in {'.mp3', '.wav', '.flac'}
        icon = "fa-music" if is_audio else "fa-film"
        color = "#e91e63" if is_audio else "#2196f3"

        cards_html += f'''
        <div class="media-card" onclick="prepareVideo('{safe_name}')">
            <div class="card-icon" style="color: {color};">
                <i class="fas {icon}"></i>
            </div>
            <div class="card-title" title="{f}">{f}</div>
            <div class="card-size">{size}</div>
            <div class="card-play-overlay">
                <i class="fas fa-play-circle"></i>
            </div>
        </div>
        '''

    html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AVI Media Server</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
    body {{
        background: #0f0f1a;
        color: white;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        margin: 0; padding: 20px;
        min-height: 100vh;
    }}
    h1 {{
        text-align: center; color: #bbdefb;
        font-weight: 300; letter-spacing: 2px;
        margin-bottom: 40px;
    }}
    
    /* Сетка медиафайлов */
    .media-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 25px;
        max-width: 1200px;
        margin: 0 auto;
    }}
    
    .media-card {{
        background: rgba(30, 30, 45, 0.8);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 15px;
        padding: 20px;
        text-align: center;
        cursor: pointer;
        position: relative;
        overflow: hidden;
        transition: all 0.3s ease;
        box-shadow: 0 10px 20px rgba(0,0,0,0.3);
        backdrop-filter: blur(10px);
    }}
    .media-card:hover {{
        transform: translateY(-10px);
        box-shadow: 0 15px 30px rgba(33, 150, 243, 0.4);
        border-color: rgba(33, 150, 243, 0.5);
    }}
    
    .card-icon {{ font-size: 60px; margin-bottom: 15px; transition: transform 0.3s ease; }}
    .media-card:hover .card-icon {{ transform: scale(1.1); }}
    
    .card-title {{
        font-weight: 600; font-size: 15px;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        margin-bottom: 10px; color: #e0e0e0;
    }}
    .card-size {{ font-size: 13px; color: #888; }}
    
    .card-play-overlay {{
        position: absolute; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0, 0, 0, 0.6);
        display: flex; align-items: center; justify-content: center;
        font-size: 50px; color: white; opacity: 0; transition: opacity 0.3s ease;
    }}
    .media-card:hover .card-play-overlay {{ opacity: 1; }}

    /* Оверлей загрузки */
    #loading-overlay {{
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(10, 10, 15, 0.95);
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        z-index: 1000; opacity: 0; visibility: hidden; transition: all 0.4s ease;
        backdrop-filter: blur(15px);
    }}
    #loading-overlay.active {{ opacity: 1; visibility: visible; }}
    
    .loader-icon {{ font-size: 50px; color: #2196f3; margin-bottom: 20px; animation: spin 2s linear infinite; }}
    @keyframes spin {{ 100% {{ transform: rotate(360deg); }} }}
    
    .status-text {{ font-size: 24px; font-weight: 300; margin-bottom: 15px; color: #bbdefb; }}
    
    .progress-container {{
        width: 300px; height: 8px; background: rgba(255,255,255,0.1);
        border-radius: 4px; overflow: hidden; position: relative;
    }}
    .progress-bar {{
        height: 100%; width: 0%; background: linear-gradient(90deg, #2196f3, #00bcd4);
        transition: width 0.5s ease;
    }}
</style>
</head>
<body>

    <h1><i class="fas fa-server"></i> AVI Media Core</h1>
    
    <div class="media-grid">
        {cards_html}
    </div>

    <div id="loading-overlay">
        <i class="fas fa-cog loader-icon"></i>
        <div class="status-text" id="status-text">Запуск движка FFmpeg...</div>
        <div class="progress-container">
            <div class="progress-bar" id="progress-bar"></div>
        </div>
        <div style="margin-top: 15px; color: #888; font-size: 14px;">Пожалуйста, подождите. Идет транскодирование.</div>
    </div>

    <script>
        const GITHUB_PAGES_URL = "{GITHUB_PAGES_URL}";
        
        async function prepareVideo(filename) {{
            const overlay = document.getElementById('loading-overlay');
            const statusText = document.getElementById('status-text');
            const progressBar = document.getElementById('progress-bar');
            
            overlay.classList.add('active');
            progressBar.style.width = '10%';
            
            // 1. Даем команду серверу начать нарезку
            try {{
                const startRes = await fetch('/prepare/' + filename, {{ method: 'POST' }});
                if (!startRes.ok) throw new Error("Ошибка запуска");
                
                progressBar.style.width = '40%';
                statusText.textContent = 'Создание HLS потока...';
                
                // 2. Начинаем опрашивать статус каждые 2 секунды
                const checkInterval = setInterval(async () => {{
                    const statusRes = await fetch('/status/' + filename);
                    const data = await statusRes.json();
                    
                    if (data.ready) {{
                        clearInterval(checkInterval);
                        progressBar.style.width = '100%';
                        statusText.textContent = 'Готово! Перенаправление...';
                        
                        // Собираем ссылку на поток (наш локальный IP/Ngrok)
                        const currentHost = window.location.origin; 
                        const streamUrl = currentHost + "/stream/" + filename + "/index.m3u8";
                        
                        // 3. ПЕРЕНОСИМ НА GITHUB PAGES!
                        setTimeout(() => {{
                            window.location.href = GITHUB_PAGES_URL + "?stream=" + encodeURIComponent(streamUrl);
                        }}, 1000);
                    }}
                }}, 2000);
                
            }} catch (e) {{
                statusText.textContent = 'Ошибка подготовки видео!';
                statusText.style.color = '#f44336';
                setTimeout(() => overlay.classList.remove('active'), 3000);
            }}
        }}
    </script>
</body>
</html>'''
    return render_template_string(html)

# ==========================================
# 2. МАРШРУТ: ЗАПУСК ПОДГОТОВКИ (FFMPEG)
# ==========================================
@app.route('/prepare/<path:filename>', methods=['POST'])
def prepare_video(filename):
    video_path = os.path.join(FOLDER, urllib.parse.unquote(filename))
    stream_dir = os.path.join(HLS_CACHE, urllib.parse.unquote(filename))
    os.makedirs(stream_dir, exist_ok=True)
    m3u8_file = os.path.join(stream_dir, 'index.m3u8')

    # Если уже есть готовый плейлист, ничего не делаем
    if not os.path.exists(m3u8_file):
        # Быстрое перекодирование: H.264 (720p), ultrafast preset, куски по 5 секунд
        command = [
            'ffmpeg', '-i', video_path,
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', '-vf', 'scale=-2:720',
            '-c:a', 'aac', '-b:a', '128k',
            '-start_number', '0', '-hls_time', '5', '-hls_list_size', '0',
            '-f', 'hls', m3u8_file
        ]
        # Запускаем как независимый процесс, чтобы не вешать Flask
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    return jsonify({"status": "processing"})

# ==========================================
# 3. МАРШРУТ: ПРОВЕРКА ГОТОВНОСТИ (STATUS)
# ==========================================
@app.route('/status/<path:filename>')
def check_status(filename):
    stream_dir = os.path.join(HLS_CACHE, urllib.parse.unquote(filename))
    m3u8_file = os.path.join(stream_dir, 'index.m3u8')
    
    # Видео готово к старту, если создан playlist и хотя бы ОДИН кусок .ts
    is_ready = False
    if os.path.exists(m3u8_file):
        ts_files = [f for f in os.listdir(stream_dir) if f.endswith('.ts')]
        if len(ts_files) >= 1:
            is_ready = True

    return jsonify({"ready": is_ready})

# ==========================================
# 4. МАРШРУТ: ОТДАЧА ВИДЕО ПОТОКА (HLS)
# ==========================================
@app.route('/stream/<path:filename>/<path:file>')
def serve_hls(filename, file):
    stream_dir = os.path.join(HLS_CACHE, urllib.parse.unquote(filename))
    return send_from_directory(stream_dir, file)


if __name__ == '__main__':
    print(f"🚀 AVI Media Core запущен!")
    print(f"📁 Сканирую папку: {FOLDER}")
    print(f"🌐 Сервер доступен на: http://localhost:{PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)