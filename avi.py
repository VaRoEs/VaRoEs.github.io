#!/usr/bin/env python3
import os
import subprocess
import urllib.parse
import hashlib
from flask import Flask, jsonify, send_from_directory, render_template_string, request
from flask_cors import CORS

# === Настройки ===
PORT = 8000
FOLDER = os.path.expanduser("~/Videos")  # Папка, где лежат твои фильмы
HLS_CACHE = os.path.join(FOLDER, ".hls_cache")  # Скрытая папка для кусков HLS
GITHUB_PAGES_URL = "https://varoes.github.io/"  # Ссылка на твой плеер

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
        js_safe_name = f.replace("'", "\\'").replace('"', '&quot;')
        
        is_audio = ext in {'.mp3', '.wav', '.flac'}
        icon = "fa-music" if is_audio else "fa-film"
        color = "#e91e63" if is_audio else "#2196f3"

        cards_html += f'''
        <div class="media-card" onclick="openOptionsModal('{safe_name}', '{js_safe_name}')">
            <div class="card-icon" style="color: {color};">
                <i class="fas {icon}"></i>
            </div>
            <div class="card-title" title="{f}">{f}</div>
            <div class="card-size">{size}</div>
            <div class="card-play-overlay">
                <i class="fas fa-sliders-h"></i>
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
        background: #0f0f1a; color: white;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        margin: 0; padding: 20px; min-height: 100vh;
    }}
    h1 {{
        text-align: center; color: #bbdefb;
        font-weight: 300; letter-spacing: 2px; margin-bottom: 40px;
    }}
    .media-grid {{
        display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 25px; max-width: 1200px; margin: 0 auto;
    }}
    .media-card {{
        background: rgba(30, 30, 45, 0.8); border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 15px; padding: 20px; text-align: center;
        cursor: pointer; position: relative; overflow: hidden;
        transition: all 0.3s ease; box-shadow: 0 10px 20px rgba(0,0,0,0.3);
    }}
    .media-card:hover {{
        transform: translateY(-10px); box-shadow: 0 15px 30px rgba(33, 150, 243, 0.4);
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
        background: rgba(0, 0, 0, 0.7); display: flex; align-items: center; justify-content: center;
        font-size: 50px; color: white; opacity: 0; transition: opacity 0.3s ease;
    }}
    .media-card:hover .card-play-overlay {{ opacity: 1; }}

    /* Модальное окно настроек */
    #options-modal {{
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0, 0, 0, 0.85); display: flex; align-items: center; justify-content: center;
        z-index: 500; opacity: 0; visibility: hidden; transition: all 0.3s ease; backdrop-filter: blur(5px);
    }}
    #options-modal.active {{ opacity: 1; visibility: visible; }}
    .modal-content {{
        background: #1e1e2d; border-radius: 15px; padding: 30px; width: 90%; max-width: 400px;
        border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 20px 40px rgba(0,0,0,0.5);
        position: relative;
    }}
    .close-btn {{
        position: absolute; top: 15px; right: 15px; font-size: 20px; color: #888;
        cursor: pointer; transition: color 0.2s;
    }}
    .close-btn:hover {{ color: white; }}
    .modal-title {{ font-size: 18px; margin-bottom: 20px; word-break: break-all; color: #2196f3; font-weight: bold; }}
    
    .fps-input-group {{ margin-bottom: 20px; }}
    .fps-input-group label {{ display: block; font-size: 14px; margin-bottom: 8px; color: #ccc; }}
    .fps-input-group input {{
        width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #444;
        background: #151520; color: white; font-size: 16px; box-sizing: border-box;
    }}
    .fps-input-group input:focus {{ border-color: #2196f3; outline: none; }}

    .quality-btn {{
        display: block; width: 100%; padding: 15px; margin-bottom: 10px;
        background: #2a2a3f; color: white; border: none; border-radius: 8px;
        font-size: 16px; font-weight: 600; cursor: pointer; transition: all 0.2s;
    }}
    .quality-btn.low:hover {{ background: #4caf50; }}
    .quality-btn.medium:hover {{ background: #ff9800; }}
    .quality-btn.high:hover {{ background: #f44336; }}

    /* Оверлей загрузки */
    #loading-overlay {{
        position: fixed; top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(10, 10, 15, 0.95); display: flex; flex-direction: column; align-items: center; justify-content: center;
        z-index: 1000; opacity: 0; visibility: hidden; transition: all 0.4s ease; backdrop-filter: blur(15px);
    }}
    #loading-overlay.active {{ opacity: 1; visibility: visible; }}
    .loader-icon {{ font-size: 50px; color: #2196f3; margin-bottom: 20px; animation: spin 2s linear infinite; }}
    @keyframes spin {{ 100% {{ transform: rotate(360deg); }} }}
    .status-text {{ font-size: 24px; font-weight: 300; margin-bottom: 15px; color: #bbdefb; text-align: center; }}
    .progress-container {{ width: 300px; height: 8px; background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden; }}
    .progress-bar {{ height: 100%; width: 0%; background: linear-gradient(90deg, #2196f3, #00bcd4); transition: width 0.5s ease; }}
</style>
</head>
<body>

    <h1><i class="fas fa-server"></i> AVI Media Core</h1>
    
    <div class="media-grid">
        {cards_html}
    </div>

    <div id="options-modal">
        <div class="modal-content">
            <i class="fas fa-times close-btn" onclick="closeOptionsModal()"></i>
            <div class="modal-title" id="modal-filename-display">Фильм.mp4</div>
            
            <div class="fps-input-group">
                <label for="fps-input"><i class="fas fa-tachometer-alt"></i> FPS (Кадры в секунду):</label>
                <input type="number" id="fps-input" placeholder="Исходный (напр. 24, 30, 60)" min="1" max="120">
            </div>

            <button class="quality-btn low" onclick="startTranscoding('low')">Слабый (360p + Идеальный поток)</button>
            <button class="quality-btn medium" onclick="startTranscoding('medium')">Средний (720p + Баланс HRD)</button>
            <button class="quality-btn high" onclick="startTranscoding('high')">Высокий (Исходное с защитой)</button>
        </div>
    </div>

    <div id="loading-overlay">
        <i class="fas fa-cog loader-icon"></i>
        <div class="status-text" id="status-text">Запуск движка FFmpeg...</div>
        <div class="progress-container">
            <div class="progress-bar" id="progress-bar"></div>
        </div>
    </div>

    <script>
        const GITHUB_PAGES_URL = "{GITHUB_PAGES_URL}";
        let currentFileSafeName = "";

        function openOptionsModal(safeName, displayName) {{
            currentFileSafeName = safeName;
            document.getElementById('modal-filename-display').innerHTML = displayName;
            document.getElementById('fps-input').value = ''; 
            document.getElementById('options-modal').classList.add('active');
        }}

        function closeOptionsModal() {{
            document.getElementById('options-modal').classList.remove('active');
        }}

        async function startTranscoding(quality) {{
            closeOptionsModal();
            
            const fpsValue = document.getElementById('fps-input').value;
            const overlay = document.getElementById('loading-overlay');
            const statusText = document.getElementById('status-text');
            const progressBar = document.getElementById('progress-bar');
            
            overlay.classList.add('active');
            progressBar.style.width = '10%';
            statusText.textContent = 'Подготовка параметров...';
            
            try {{
                const payload = {{ quality: quality, fps: fpsValue }};
                
                const startRes = await fetch('/prepare/' + currentFileSafeName, {{ 
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                
                if (!startRes.ok) throw new Error("Ошибка запуска");
                
                const responseData = await startRes.json();
                const streamId = responseData.stream_id;
                
                progressBar.style.width = '40%';
                statusText.textContent = 'Рендеринг потока...';
                
                const checkInterval = setInterval(async () => {{
                    const statusRes = await fetch('/status/' + streamId);
                    const data = await statusRes.json();
                    
                    if (data.ready) {{
                        clearInterval(checkInterval);
                        progressBar.style.width = '100%';
                        statusText.textContent = 'Готово! Перенаправление...';
                        
                        const currentHost = window.location.origin; 
                        const streamUrl = currentHost + "/stream/" + streamId + "/index.m3u8";
                        
                        setTimeout(() => {{
                            window.location.href = GITHUB_PAGES_URL + "?stream=" + encodeURIComponent(streamUrl);
                        }}, 1000);
                    }}
                }}, 2000);
                
            }} catch (e) {{
                statusText.textContent = 'Ошибка! Проверьте консоль сервера.';
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
    
    data = request.json or {}
    quality = data.get('quality', 'medium')
    fps = data.get('fps', '').strip()

    stream_key = f"{filename}_{quality}_{fps}"
    stream_id = hashlib.md5(stream_key.encode()).hexdigest()
    
    stream_dir = os.path.join(HLS_CACHE, stream_id)
    os.makedirs(stream_dir, exist_ok=True)
    m3u8_file = os.path.join(stream_dir, 'index.m3u8')

    if not os.path.exists(m3u8_file):
        # Умный расчет потоков (Оставляем 25% CPU свободными)
        total_cores = os.cpu_count() or 4
        threads_to_use = max(1, int(total_cores * 0.75))
        
        command = [
            'ffmpeg', '-i', video_path,
            '-c:v', 'libx264', '-preset', 'ultrafast',
            '-threads', str(threads_to_use)
        ]

        if fps and fps.isdigit():
            command.extend(['-r', fps])

        # ---------------------------------------------------------
        # МАГИЯ HRD (Capped CRF) - Идеально ровный поток для процессора
        # -maxrate: Жесткий потолок битрейта (чтобы Wi-Fi и ЦП не подавились)
        # -bufsize: Эмулятор буфера планшета (сообщает FFmpeg, как "размазать" сложные кадры)
        # ---------------------------------------------------------
        if quality == 'low':
            # Для старого Atom: Строгие 400 килобит. Процессор отдыхает.
            command.extend([
                '-vf', 'scale=-2:360', 
                '-crf', '32', '-maxrate', '400k', '-bufsize', '800k', 
                '-c:a', 'aac', '-b:a', '64k'
            ])
        elif quality == 'high':
            # Для мощных устройств: отличное качество, но режем сумасшедшие скачки выше 5 Мбит/с
            command.extend([
                '-crf', '23', '-maxrate', '5000k', '-bufsize', '10000k', 
                '-c:a', 'aac', '-b:a', '192k'
            ])
        else: # medium
            # Идеальный баланс 720p: Жесткий лимит в 1.5 Мбит/с
            command.extend([
                '-vf', 'scale=-2:720', 
                '-crf', '28', '-maxrate', '1500k', '-bufsize', '3000k', 
                '-c:a', 'aac', '-b:a', '128k'
            ])

        command.extend([
            '-start_number', '0', '-hls_time', '5', '-hls_list_size', '0',
            '-hls_playlist_type', 'event',
            '-f', 'hls', m3u8_file
        ])
        
        print(f"Запуск потока: {quality} (FPS: {fps if fps else 'Исходный'})")
        print(f"ЦП: Обнаружено {total_cores} потоков. Используем {threads_to_use} (Ограничение 75%).")
        print(f"Режим HRD включен: идеальная математика синхронизации.")
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    return jsonify({"status": "processing", "stream_id": stream_id})

# ==========================================
# 3. МАРШРУТ: ПРОВЕРКА ГОТОВНОСТИ (STATUS)
# ==========================================
@app.route('/status/<stream_id>')
def check_status(stream_id):
    stream_dir = os.path.join(HLS_CACHE, stream_id)
    m3u8_file = os.path.join(stream_dir, 'index.m3u8')
    
    is_ready = False
    if os.path.exists(m3u8_file):
        ts_files = [f for f in os.listdir(stream_dir) if f.endswith('.ts')]
        if len(ts_files) >= 1:
            is_ready = True

    return jsonify({"ready": is_ready})

# ==========================================
# 4. МАРШРУТ: ОТДАЧА ВИДЕО ПОТОКА (HLS)
# ==========================================
@app.route('/stream/<stream_id>/<path:file>')
def serve_hls(stream_id, file):
    stream_dir = os.path.join(HLS_CACHE, stream_id)
    return send_from_directory(stream_dir, file)


if __name__ == '__main__':
    total_cores = os.cpu_count() or 4
    calc_threads = max(1, int(total_cores * 0.75))
    print(f"🚀 AVI Media Core [PRO Version] запущен!")
    print(f"⚙️ Динамическая оптимизация CPU: {calc_threads}/{total_cores} потоков")
    print(f"📁 Сканирую папку: {FOLDER}")
    print(f"🌐 Сервер доступен на: http://localhost:{PORT}")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
