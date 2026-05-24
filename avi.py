#!/usr/bin/env python3
import os
import subprocess
import urllib.parse
import hashlib
import json
import threading
from flask import Flask, jsonify, send_from_directory, render_template_string, request

# === Настройки ===
PORT = 8000
FOLDER = os.path.expanduser("~/Videos")  
HLS_CACHE = os.path.join(FOLDER, ".hls_cache")  
THUMB_DIR = os.path.join(HLS_CACHE, ".thumbnails")  
META_FILE = os.path.join(HLS_CACHE, "meta.json")    
PLAYLIST_FILE = os.path.join(HLS_CACHE, "playlist.json")

MEDIA_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.mp3', '.wav', '.flac'}

os.makedirs(FOLDER, exist_ok=True)
os.makedirs(HLS_CACHE, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)

app = Flask(__name__)
meta_lock = threading.Lock()
playlist_lock = threading.Lock()

# Глобальная переменная для контроля процесса FFmpeg
current_ffmpeg_process = None

def get_secure_path(filename):
    """Защита от Path Traversal (выхода за пределы FOLDER)"""
    base_dir = os.path.abspath(FOLDER)
    target_path = os.path.abspath(os.path.join(FOLDER, urllib.parse.unquote(filename)))
    if not target_path.startswith(base_dir):
        return None
    return target_path

def sizeof_fmt(num):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"

def format_duration(seconds):
    if seconds <= 0: return ""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0: return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def get_media_duration(file_path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=2
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0

def load_playlist():
    with playlist_lock:
        if os.path.exists(PLAYLIST_FILE):
            try:
                with open(PLAYLIST_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception: pass
        return {"files": [], "names": []}

def save_playlist(data):
    with playlist_lock:
        try:
            with open(PLAYLIST_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception: pass

# ==========================================
# API МАРШРУТЫ ДЛЯ СЕРВЕРНОГО ПЛЕЙЛИСТА
# ==========================================
@app.route('/api/playlist', methods=['GET'])
def get_playlist():
    return jsonify(load_playlist())

@app.route('/api/playlist/set', methods=['POST'])
def set_playlist():
    data = request.json or {}
    save_playlist({"files": data.get('files', []), "names": data.get('names', [])})
    return jsonify({"status": "success"})

@app.route('/api/playlist/add', methods=['POST'])
def add_to_playlist():
    data = request.json or {}
    safe_name = data.get('safe_name')
    display_name = data.get('display_name')
    if safe_name and display_name:
        pl = load_playlist()
        if safe_name not in pl['files']:
            pl['files'].append(safe_name)
            pl['names'].append(display_name)
            save_playlist(pl)
    return jsonify({"status": "success"})

@app.route('/api/playlist/add_multiple', methods=['POST'])
def add_multiple_to_playlist():
    data = request.json or {}
    items = data.get('items', [])
    pl = load_playlist()
    for item in items:
        if item['safe_name'] not in pl['files']:
            pl['files'].append(item['safe_name'])
            pl['names'].append(item['display_name'])
    save_playlist(pl)
    return jsonify({"status": "success"})

@app.route('/api/playlist/remove', methods=['POST'])
def remove_from_playlist():
    data = request.json or {}
    idx = data.get('index')
    if idx is not None:
        pl = load_playlist()
        if 0 <= idx < len(pl['files']):
            pl['files'].pop(idx)
            pl['names'].pop(idx)
            save_playlist(pl)
    return jsonify({"status": "success"})

@app.route('/api/playlist/clear', methods=['POST'])
def clear_playlist():
    save_playlist({"files": [], "names": []})
    return jsonify({"status": "success"})

@app.route('/api/playlist/save_file', methods=['POST'])
def save_playlist_to_file():
    data = request.json or {}
    name = data.get('name', 'MyPlaylist')
    rel_path = data.get('path', '')
    pl = load_playlist()
    if not pl['files']: return jsonify({"status": "error", "msg": "Плейлист пуст"})
    
    target_dir = os.path.join(FOLDER, rel_path) if rel_path else FOLDER
    base_dir = os.path.abspath(FOLDER)
    if not os.path.abspath(target_dir).startswith(base_dir): target_dir = base_dir
    
    safe_name = "".join(x for x in name if x.isalnum() or x in " -_")
    if not safe_name: safe_name = "Playlist"
    if not safe_name.endswith('.ofpl'): safe_name += '.ofpl'
    
    file_path = os.path.join(target_dir, safe_name)
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(pl, f, ensure_ascii=False, indent=2)
        return jsonify({"status": "success"})
    except:
        return jsonify({"status": "error"})

@app.route('/api/playlist/read_file', methods=['POST'])
def read_playlist_file():
    data = request.json or {}
    filepath = data.get('filepath', '')
    target_path = get_secure_path(filepath)
    if target_path and os.path.exists(target_path):
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        except: pass
    return jsonify({"files": [], "names": []})

@app.route('/api/playlist/pop', methods=['POST'])
def pop_playlist():
    pl = load_playlist()
    if pl['files']:
        pl['files'].pop(0)
        pl['names'].pop(0)
        save_playlist(pl)
    return jsonify(pl)

# ==========================================
# 1. МАРШРУТ: ГЛАВНАЯ СТРАНИЦА (ГАЛЕРЕЯ)
# ==========================================
@app.route('/')
def index():
    rel_path = request.args.get('p', '')
    current_dir = os.path.join(FOLDER, rel_path) if rel_path else FOLDER
    current_dir = os.path.abspath(current_dir)
    base_dir = os.path.abspath(FOLDER)
    
    if not current_dir.startswith(base_dir):
        current_dir = base_dir
        rel_path = ''
        
    try: items = os.listdir(current_dir)
    except OSError: items = []

    meta_cache = {}
    with meta_lock:
        if os.path.exists(META_FILE):
            try:
                with open(META_FILE, 'r') as f: meta_cache = json.load(f)
            except Exception: pass
    meta_changed = False
        
    folders = []
    files = []
    
    for item in items:
        if item.startswith('.'): continue
        full_path = os.path.join(current_dir, item)
        if os.path.isdir(full_path): folders.append(item)
        elif os.path.isfile(full_path):
            ext = os.path.splitext(item)[1].lower()
            if ext in MEDIA_EXTS or ext == '.ofpl': files.append(item)
                
    folders.sort()
    files.sort()
    cards_html = ""
    
    if rel_path:
        parent_path = os.path.dirname(rel_path)
        cards_html += f'''
        <div class="media-card folder-card" onclick="location.href='/?p={urllib.parse.quote(parent_path)}'">
            <div class="card-icon" style="color: #b0bec5;"><i class="fas fa-arrow-left"></i></div>
            <div class="card-title">.. (Назад)</div>
            <div class="card-size">Вернуться</div>
        </div>
        '''

    for folder in folders:
        sub_rel_path = os.path.join(rel_path, folder) if rel_path else folder
        safe_p = urllib.parse.quote(sub_rel_path)
        cards_html += f'''
        <div class="media-card folder-card" onclick="location.href='/?p={safe_p}'">
            <div class="card-icon" style="color: #ffca28;"><i class="fas fa-folder"></i></div>
            <div class="card-title" title="{folder}">{folder}</div>
            <div class="card-size">Папка</div>
        </div>
        '''

    for f in files:
        file_rel_path = os.path.join(rel_path, f) if rel_path else f
        full_path = os.path.join(FOLDER, file_rel_path)
        ext = os.path.splitext(f)[1].lower()
        
        safe_name = urllib.parse.quote(file_rel_path)
        js_safe_name = f.replace("'", "\\'").replace('"', '&quot;')
        display_name = os.path.splitext(f)[0].replace('.', ' ').replace('_', ' ')
        
        # Если это сохраненный плейлист
        if ext == '.ofpl':
            cards_html += f'''
            <div class="media-card file-card" data-type="playlist" data-name="{display_name.lower()}" data-duration="0" onclick="openSavedPlaylistModal('{safe_name}', '{js_safe_name}')">
                <div class="card-icon" style="color: #4caf50;"><i class="fas fa-list-ol"></i></div>
                <div class="card-title" title="{f}">{display_name}</div>
                <div class="card-size">Плейлист</div>
                <div class="card-play-overlay"><i class="fas fa-sliders-h"></i></div>
            </div>'''
            continue
            
        # Медиа файл
        file_size = os.stat(full_path).st_size
        size_str = sizeof_fmt(file_size)
        cache_key = f"{f}_{file_size}"
        
        if cache_key in meta_cache: duration = meta_cache[cache_key]
        else:
            duration = get_media_duration(full_path)
            meta_cache[cache_key] = duration
            meta_changed = True
            
        dur_str = format_duration(duration)
        info_text = f"{size_str} • {dur_str}" if dur_str else size_str
        
        is_audio = ext in {'.mp3', '.wav', '.flac'}
        icon = "fa-music" if is_audio else "fa-film"
        color = "#e91e63" if is_audio else "#2196f3"
        card_id = hashlib.md5(file_rel_path.encode()).hexdigest()
        
        add_btn = f'''<div class="card-add-btn" title="Добавить в плейлист" onclick="event.stopPropagation(); addToPlaylist('{safe_name}', '{js_safe_name}')"><i class="fas fa-plus"></i></div>'''

        if is_audio:
            cards_html += f'''
            <div class="media-card file-card" data-type="media" data-safe="{safe_name}" data-display="{js_safe_name}" data-name="{display_name.lower()}" data-duration="{duration}" onclick="openOptionsModal('{safe_name}', '{js_safe_name}')">
                {add_btn}
                <div class="card-icon" style="color: {color};"><i class="fas {icon}"></i></div>
                <div class="card-title" title="{f}">{display_name}</div>
                <div class="card-size">{info_text}</div>
                <div class="card-play-overlay"><i class="fas fa-sliders-h"></i></div>
            </div>'''
        else:
            thumb_url = f"/thumbnail/{safe_name}"
            cards_html += f'''
            <div class="media-card file-card" data-type="media" data-safe="{safe_name}" data-display="{js_safe_name}" data-name="{display_name.lower()}" data-duration="{duration}" onclick="openOptionsModal('{safe_name}', '{js_safe_name}')">
                {add_btn}
                <div class="thumb-wrapper">
                    <img class="card-thumb" id="thumb-{card_id}" src="{thumb_url}" onerror="this.style.display='none'; document.getElementById('icon-{card_id}').style.display='flex';">
                    <div class="card-icon fallback-icon" id="icon-{card_id}" style="color: {color}; display: none;"><i class="fas {icon}"></i></div>
                </div>
                <div class="card-title" title="{f}">{display_name}</div>
                <div class="card-size">{info_text}</div>
                <div class="card-play-overlay"><i class="fas fa-sliders-h"></i></div>
            </div>'''

    if meta_changed:
        with meta_lock:
            try:
                with open(META_FILE, 'w') as f: json.dump(meta_cache, f)
            except Exception: pass

    path_indicator = f'<div class="path-indicator"><i class="fas fa-folder-open"></i> / {rel_path}</div>' if rel_path else '<div class="path-indicator"><i class="fas fa-home"></i> Главная директория</div>'

    html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AVI Media Server</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
    body {{ background: #0f0f1a; color: white; font-family: -apple-system, sans-serif; margin: 0; padding: 20px; min-height: 100vh; }}
    h1 {{ text-align: center; color: #bbdefb; font-weight: 300; letter-spacing: 2px; margin-bottom: 20px; }}
    .top-bar {{ display: flex; justify-content: space-between; align-items: center; max-width: 1200px; margin: 0 auto 15px auto; flex-wrap: wrap; gap: 15px; }}
    .path-indicator {{ color: #888; font-size: 14px; background: rgba(255,255,255,0.05); padding: 8px 16px; border-radius: 20px; flex-grow: 1; }}
    .sort-select, .action-btn {{ background: #1e1e2d; color: #e0e0e0; border: 1px solid rgba(255,255,255,0.2); padding: 8px 15px; border-radius: 20px; outline: none; font-size: 14px; cursor: pointer; transition: 0.2s; }}
    .action-btn:hover {{ background: #2196f3; color: white; border-color: #2196f3; box-shadow: 0 4px 10px rgba(33, 150, 243, 0.2); }}
    
    #playlist-bar {{
        display: none; justify-content: space-between; align-items: center; background: linear-gradient(90deg, rgba(30,30,45,0.8), rgba(42,42,63,0.8));
        max-width: 1200px; margin: 0 auto 30px auto; padding: 15px 20px; border-radius: 12px; border: 1px solid rgba(33, 150, 243, 0.3); box-shadow: 0 5px 20px rgba(0, 0, 0, 0.5); box-sizing: border-box; flex-wrap: wrap; gap: 10px; backdrop-filter: blur(10px);
    }}
    
    .playlist-controls button {{ background: rgba(255, 255, 255, 0.03); color: #e0e0e0; border: 1px solid rgba(255,255,255,0.1); padding: 8px 15px; border-radius: 8px; cursor: pointer; margin-left: 10px; font-weight: 500; transition: all 0.3s ease; display: inline-flex; align-items: center; gap: 6px; font-size: 14px; }}
    
    .playlist-controls button.edit {{ color: #ffb74d; border-color: rgba(255, 183, 77, 0.4); }}
    .playlist-controls button.edit:hover {{ background: rgba(255, 183, 77, 0.15); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(255, 183, 77, 0.2); border-color: #ffb74d; color: #fff; }}
    
    .playlist-controls button.save {{ color: #81c784; border-color: rgba(129, 199, 132, 0.4); }}
    .playlist-controls button.save:hover {{ background: rgba(129, 199, 132, 0.15); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(129, 199, 132, 0.2); border-color: #81c784; color: #fff; }}
    
    .playlist-controls button.play-btn {{ color: #64b5f6; border-color: rgba(100, 181, 246, 0.4); }}
    .playlist-controls button.play-btn:hover {{ background: rgba(100, 181, 246, 0.15); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(100, 181, 246, 0.2); border-color: #64b5f6; color: #fff; }}
    
    .playlist-controls button.clear {{ color: #e57373; border-color: rgba(229, 115, 115, 0.4); }}
    .playlist-controls button.clear:hover {{ background: rgba(229, 115, 115, 0.15); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(229, 115, 115, 0.2); border-color: #e57373; color: #fff; }}

    .media-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 25px; max-width: 1200px; margin: 0 auto; }}
    .media-card {{ background: rgba(30, 30, 45, 0.8); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 15px; padding: 20px; text-align: center; cursor: pointer; position: relative; overflow: hidden; transition: all 0.3s ease; box-shadow: 0 10px 20px rgba(0,0,0,0.3); display: flex; flex-direction: column; justify-content: space-between; height: 260px; box-sizing: border-box; }}
    .media-card:hover {{ transform: translateY(-10px); border-color: rgba(33, 150, 243, 0.5); }}
    
    .card-add-btn {{ position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,0.6); color: white; border-radius: 50%; width: 30px; height: 30px; display: flex; align-items: center; justify-content: center; z-index: 10; transition: 0.2s; border: 1px solid rgba(255,255,255,0.2); opacity: 0; }}
    .media-card:hover .card-add-btn {{ opacity: 1; }}
    .card-add-btn:hover {{ background: #2196f3; transform: scale(1.1); border-color: #2196f3; box-shadow: 0 0 10px #2196f3; }}

    .card-icon, .thumb-wrapper {{ height: 110px; display: flex; align-items: center; justify-content: center; font-size: 60px; margin-bottom: 10px; transition: transform 0.3s ease; overflow: hidden; border-radius: 8px; position: relative; flex-shrink: 0; }}
    .card-thumb {{ width: 100%; height: 100%; object-fit: cover; }}
    .card-title {{ font-weight: 600; font-size: 14px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; margin-bottom: 5px; color: #e0e0e0; line-height: 1.3; }}
    .card-size {{ font-size: 12px; color: #888; margin-top: auto; }}
    .card-play-overlay {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.7); display: flex; align-items: center; justify-content: center; font-size: 50px; color: white; opacity: 0; transition: opacity 0.3s ease; }}
    .media-card:hover .card-play-overlay {{ opacity: 1; }}

    .modal-overlay {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.85); display: flex; align-items: center; justify-content: center; z-index: 500; opacity: 0; visibility: hidden; transition: all 0.3s ease; backdrop-filter: blur(5px); }}
    .modal-overlay.active {{ opacity: 1; visibility: visible; }}
    .modal-content {{ background: #1e1e2d; border-radius: 15px; padding: 30px; width: 90%; max-width: 400px; border: 1px solid rgba(255,255,255,0.1); position: relative; max-height: 80vh; display: flex; flex-direction: column; box-shadow: 0 20px 50px rgba(0,0,0,0.8); }}
    .close-btn {{ position: absolute; top: 15px; right: 15px; font-size: 20px; color: #888; cursor: pointer; z-index: 10; transition: 0.2s; }}
    .close-btn:hover {{ color: white; transform: rotate(90deg); }}
    .modal-title {{ font-size: 18px; margin-bottom: 20px; word-break: break-all; color: #2196f3; font-weight: bold; padding-right: 20px; }}
    
    .fps-input-group {{ margin-bottom: 20px; }}
    .fps-input-group input {{ width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #444; background: #151520; color: white; font-size: 16px; box-sizing: border-box; }}
    .quality-btn {{ display: block; width: 100%; padding: 15px; margin-bottom: 10px; background: #2a2a3f; color: white; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s; }}
    .quality-btn.low:hover {{ background: #4caf50; }} .quality-btn.medium:hover {{ background: #ff9800; }} .quality-btn.high:hover {{ background: #f44336; }} .quality-btn.cinema {{ border: 1px solid #9c27b0; }} .quality-btn.cinema:hover {{ background: #9c27b0; }}

    /* Queue Modal specific with Drag & Drop styling */
    #queue-list {{ list-style: none; padding: 0; margin: 0; overflow-y: auto; flex-grow: 1; }}
    #queue-list::-webkit-scrollbar {{ width: 6px; }}
    #queue-list::-webkit-scrollbar-track {{ background: rgba(0,0,0,0.2); }}
    #queue-list::-webkit-scrollbar-thumb {{ background: #2196f3; border-radius: 3px; }}
    .queue-item {{ display: flex; justify-content: space-between; align-items: center; padding: 12px 15px; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 14px; background: rgba(0,0,0,0.2); margin-bottom: 8px; border-radius: 8px; transition: background 0.2s, border 0.2s; border: 1px solid transparent; cursor: grab; }}
    .queue-item:active {{ cursor: grabbing; }}
    .queue-item:hover {{ background: rgba(0,0,0,0.4); border-color: rgba(33, 150, 243, 0.3); }}
    .queue-item.over {{ border-top: 2px dashed #2196f3; background: rgba(33, 150, 243, 0.15); }}
    .drag-handle {{ color: #666; margin-right: 15px; font-size: 16px; transition: 0.2s; display: flex; align-items: center; }}
    .queue-item:hover .drag-handle {{ color: #bbdefb; }}
    
    .queue-item-name {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-right: 10px; color: #ddd; flex-grow: 1; pointer-events: none; }}
    .queue-remove-btn {{ color: #e57373; cursor: pointer; background: none; border: none; font-size: 16px; padding: 5px; transition: 0.2s; opacity: 0.7; }}
    .queue-remove-btn:hover {{ color: #f44336; opacity: 1; transform: scale(1.1); }}

    #loading-overlay {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(10, 10, 15, 0.95); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 1000; opacity: 0; visibility: hidden; transition: all 0.4s ease; backdrop-filter: blur(15px); }}
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
    
    <div id="playlist-bar">
        <div><i class="fas fa-list"></i> <span id="current-pl-name" style="cursor:pointer; border-bottom: 1px dashed #888; color: #2196f3; padding-bottom: 2px;" onclick="renamePlaylist()" title="Изменить название">Новый плейлист</span>: <strong id="pl-count">0</strong> медиа <i class="fas fa-pen" style="font-size:11px; color:#888; cursor:pointer; margin-left: 5px;" onclick="renamePlaylist()"></i></div>
        <div class="playlist-controls">
            <button class="edit" onclick="openQueueModal()"><i class="fas fa-list-ul"></i> Список</button>
            <button class="save" onclick="savePlaylistFile()"><i class="fas fa-save"></i> Сохранить</button>
            <button class="play-btn" onclick="startPlaylist()"><i class="fas fa-play"></i> Запустить</button>
            <button class="clear" onclick="clearPlaylist()"><i class="fas fa-trash"></i> Очистить</button>
        </div>
    </div>

    <div class="top-bar">
        {path_indicator}
        <button class="action-btn" onclick="addAllToPlaylist()"><i class="fas fa-plus-circle"></i> Добавить все медиа</button>
        <select class="sort-select" id="sort-select" onchange="sortCards()">
            <option value="name_asc">Имя (А-Я)</option>
            <option value="name_desc">Имя (Я-А)</option>
            <option value="dur_desc">Самые длинные</option>
            <option value="dur_asc">Самые короткие</option>
        </select>
    </div>
    
    <div class="media-grid" id="media-grid">
        {cards_html}
    </div>

    <div id="options-modal" class="modal-overlay">
        <div class="modal-content">
            <i class="fas fa-times close-btn" onclick="closeModal('options-modal')"></i>
            <div class="modal-title" id="modal-filename-display">Фильм.mp4</div>
            <div class="fps-input-group">
                <label for="fps-input"><i class="fas fa-tachometer-alt"></i> FPS:</label>
                <input type="number" id="fps-input" placeholder="Исходный (напр. 24, 60)">
            </div>
            <button class="quality-btn low" onclick="startTranscoding('low')">Слабый (360p)</button>
            <button class="quality-btn medium" onclick="startTranscoding('medium')">Средний (720p)</button>
            <button class="quality-btn cinema" onclick="startTranscoding('cinema')">Кино (720p HQ)</button>
            <button class="quality-btn high" onclick="startTranscoding('high')">Высокий (Исходное)</button>
        </div>
    </div>
    
    <div id="saved-playlist-modal" class="modal-overlay">
        <div class="modal-content">
            <i class="fas fa-times close-btn" onclick="closeModal('saved-playlist-modal')"></i>
            <div class="modal-title" id="saved-pl-title">Плейлист.ofpl</div>
            <button class="quality-btn high" onclick="playSavedPlaylist()">Запустить плейлист</button>
            <button class="quality-btn edit" onclick="editSavedPlaylist()" style="background: rgba(255, 183, 77, 0.15); border: 1px solid #ffb74d; color: #ffb74d;">Редактировать список</button>
        </div>
    </div>
    
    <div id="queue-modal" class="modal-overlay">
        <div class="modal-content" style="height: 65vh; max-width: 500px;">
            <i class="fas fa-times close-btn" onclick="closeModal('queue-modal')"></i>
            <div class="modal-title" style="display: flex; justify-content: space-between; align-items: center; padding-right: 25px; margin-bottom: 15px; width: 100%; box-sizing: border-box;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span id="queue-modal-title" style="color: #2196f3; border-bottom: 1px dashed transparent; cursor: pointer;" onclick="renamePlaylist()" title="Изменить название">Очередь</span>
                    <button onclick="renamePlaylist()" title="Переименовать" style="background:none; border:none; color:#888; cursor:pointer; font-size: 14px; transition: 0.2s;" onmouseover="this.style.color='#fff'" onmouseout="this.style.color='#888'"><i class="fas fa-pen"></i></button>
                </div>
                <button class="action-btn" onclick="closeModal('queue-modal')" style="font-size: 13px; padding: 6px 12px; background: rgba(33, 150, 243, 0.1); color: #64b5f6; border-color: rgba(33, 150, 243, 0.4);">
                    <i class="fas fa-plus"></i> Добавить медиа
                </button>
            </div>
            <ul id="queue-list"></ul>
        </div>
    </div>

    <div id="loading-overlay">
        <i class="fas fa-cog loader-icon"></i>
        <div class="status-text" id="status-text">Запуск движка FFmpeg...</div>
        <div class="progress-container"><div class="progress-bar" id="progress-bar"></div></div>
    </div>

    <script>
        function sortCards() {{
            const grid = document.getElementById('media-grid');
            const folders = Array.from(grid.querySelectorAll('.folder-card'));
            const files = Array.from(grid.querySelectorAll('.file-card'));
            const sortType = document.getElementById('sort-select').value;
            files.sort((a, b) => {{
                const nameA = a.dataset.name, nameB = b.dataset.name;
                const durA = parseFloat(a.dataset.duration), durB = parseFloat(b.dataset.duration);
                if (sortType === 'name_asc') return nameA.localeCompare(nameB);
                if (sortType === 'name_desc') return nameB.localeCompare(nameA);
                if (sortType === 'dur_asc') return durA - durB;
                if (sortType === 'dur_desc') return durB - durA;
            }});
            grid.innerHTML = '';
            folders.forEach(f => grid.appendChild(f));
            files.forEach(f => grid.appendChild(f));
        }}

        let playlistFiles = [];
        let playlistNames = [];
        let currentEditingPlaylistName = ""; 
        let currentSavedPlaylistPath = ""; 
        
        async function loadPlaylistFromServer() {{
            try {{
                const res = await fetch('/api/playlist');
                const data = await res.json();
                playlistFiles = data.files || [];
                playlistNames = data.names || [];
                updatePlaylistUI();
            }} catch(e) {{}}
        }}

        async function addToPlaylist(safeName, displayName) {{
            if(!playlistFiles.includes(safeName)) {{
                playlistFiles.push(safeName);
                playlistNames.push(displayName);
                updatePlaylistUI();
                await fetch('/api/playlist/add', {{
                    method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ safe_name: safeName, display_name: displayName }})
                }});
            }}
        }}
        
        async function addAllToPlaylist() {{
            const cards = document.querySelectorAll('.file-card[data-type="media"]');
            let itemsToAdd = [];
            cards.forEach(card => {{
                const safeName = card.getAttribute('data-safe');
                const displayName = card.getAttribute('data-display');
                if(safeName && !playlistFiles.includes(safeName)) {{
                    playlistFiles.push(safeName);
                    playlistNames.push(displayName);
                    itemsToAdd.push({{ safe_name: safeName, display_name: displayName }});
                }}
            }});
            
            if(itemsToAdd.length > 0) {{
                updatePlaylistUI();
                await fetch('/api/playlist/add_multiple', {{
                    method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ items: itemsToAdd }})
                }});
            }}
        }}

        async function removeFromPlaylist(index) {{
            playlistFiles.splice(index, 1);
            playlistNames.splice(index, 1);
            updatePlaylistUI();
            renderQueueItems();
            await fetch('/api/playlist/remove', {{
                method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ index: index }})
            }});
        }}

        async function clearPlaylist() {{
            playlistFiles = []; playlistNames = [];
            currentEditingPlaylistName = "";
            updatePlaylistUI();
            await fetch('/api/playlist/clear', {{ method: 'POST' }});
        }}

        function renamePlaylist() {{
            let current = currentEditingPlaylistName ? currentEditingPlaylistName.replace('.ofpl', '') : "Новый плейлист";
            let newName = prompt("Введите название плейлиста:", current);
            if (newName && newName.trim() !== "") {{
                currentEditingPlaylistName = newName.trim() + ".ofpl";
                updatePlaylistUI();
            }}
        }}

        async function savePlaylistFile() {{
            let name = currentEditingPlaylistName;
            
            // Если имя еще не задано, просим его ввести
            if (!name) {{
                let input = prompt("Введите имя для нового плейлиста:", "MyPlaylist");
                if (!input || input.trim() === "") return;
                name = input.trim() + ".ofpl";
                currentEditingPlaylistName = name;
            }}
            
            // Сохраняем мгновенно под текущим именем
            const urlParams = new URLSearchParams(window.location.search);
            const res = await fetch('/api/playlist/save_file', {{
                method: 'POST', headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{name: name.replace('.ofpl', ''), path: urlParams.get('p') || ''}})
            }});
            
            const data = await res.json();
            if(data.status === 'success') {{
                updatePlaylistUI();
                location.reload(); 
            }} else {{
                alert('Ошибка сохранения: ' + (data.msg || ''));
            }}
        }}

        function openSavedPlaylistModal(filepath, displayName) {{
            currentSavedPlaylistPath = filepath;
            document.getElementById('saved-pl-title').innerHTML = displayName;
            document.getElementById('saved-playlist-modal').classList.add('active');
        }}

        async function playSavedPlaylist() {{
            closeModal('saved-playlist-modal');
            const res = await fetch('/api/playlist/read_file', {{
                method: 'POST', headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{filepath: decodeURIComponent(currentSavedPlaylistPath)}})
            }});
            const data = await res.json();
            if (data.files && data.files.length > 0) {{
                playlistFiles = data.files;
                playlistNames = data.names;
                
                await fetch('/api/playlist/set', {{
                    method: 'POST', headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{files: playlistFiles, names: playlistNames}})
                }});
                
                updatePlaylistUI();
                openOptionsModal(playlistFiles[0], document.getElementById('saved-pl-title').innerHTML, true);
            }} else {{
                alert("Плейлист пуст или поврежден");
            }}
        }}
        
        async function editSavedPlaylist() {{
            closeModal('saved-playlist-modal');
            const res = await fetch('/api/playlist/read_file', {{
                method: 'POST', headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{filepath: decodeURIComponent(currentSavedPlaylistPath)}})
            }});
            const data = await res.json();
            if (data.files) {{
                playlistFiles = data.files;
                playlistNames = data.names;
                currentEditingPlaylistName = document.getElementById('saved-pl-title').innerText;
                
                await fetch('/api/playlist/set', {{
                    method: 'POST', headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{files: playlistFiles, names: playlistNames}})
                }});
                
                updatePlaylistUI();
                openQueueModal();
            }}
        }}

        function updatePlaylistUI() {{
            const bar = document.getElementById('playlist-bar');
            if(playlistFiles.length > 0) {{
                bar.style.display = 'flex';
                document.getElementById('pl-count').innerText = playlistFiles.length;
                
                let displayName = currentEditingPlaylistName ? currentEditingPlaylistName.replace('.ofpl', '') : 'Новый плейлист';
                document.getElementById('current-pl-name').innerText = displayName;
                
                let queueTitle = document.getElementById('queue-modal-title');
                if(queueTitle) queueTitle.innerText = displayName;
            }} else {{ bar.style.display = 'none'; }}
        }}
        
        // --- DRAG AND DROP ЛОГИКА ---
        let dragSrcEl = null;

        function handleDragStart(e) {{
            dragSrcEl = this;
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', this.dataset.index);
            setTimeout(() => this.style.opacity = '0.4', 0);
        }}

        function handleDragOver(e) {{
            if (e.preventDefault) e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            return false;
        }}

        function handleDragEnter(e) {{
            this.classList.add('over');
        }}

        function handleDragLeave(e) {{
            this.classList.remove('over');
        }}

        function handleDrop(e) {{
            if (e.stopPropagation) e.stopPropagation();
            if (dragSrcEl !== this) {{
                let fromIndex = parseInt(dragSrcEl.dataset.index);
                let toIndex = parseInt(this.dataset.index);
                
                let movedFile = playlistFiles.splice(fromIndex, 1)[0];
                let movedName = playlistNames.splice(fromIndex, 1)[0];
                
                playlistFiles.splice(toIndex, 0, movedFile);
                playlistNames.splice(toIndex, 0, movedName);
                
                // Синхронизируем изменения с сервером
                fetch('/api/playlist/set', {{
                    method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ files: playlistFiles, names: playlistNames }})
                }});
                
                renderQueueItems();
            }}
            return false;
        }}

        function handleDragEnd(e) {{
            this.style.opacity = '1';
            document.querySelectorAll('.queue-item').forEach(item => {{
                item.classList.remove('over');
            }});
        }}

        function renderQueueItems() {{
            const list = document.getElementById('queue-list');
            list.innerHTML = '';
            for(let i = 0; i < playlistFiles.length; i++) {{
                const li = document.createElement('li');
                li.className = 'queue-item';
                li.draggable = true;
                li.dataset.index = i;
                
                li.innerHTML = `
                    <div style="display:flex; align-items:center; overflow:hidden; flex-grow:1;">
                        <i class="fas fa-grip-lines drag-handle"></i>
                        <div class="queue-item-name" title="${{playlistNames[i]}}">${{i + 1}}. ${{playlistNames[i]}}</div>
                    </div>
                    <button class="queue-remove-btn" onclick="removeFromPlaylist(${{i}})"><i class="fas fa-times"></i></button>
                `;
                
                li.addEventListener('dragstart', handleDragStart);
                li.addEventListener('dragover', handleDragOver);
                li.addEventListener('dragenter', handleDragEnter);
                li.addEventListener('dragleave', handleDragLeave);
                li.addEventListener('drop', handleDrop);
                li.addEventListener('dragend', handleDragEnd);
                
                list.appendChild(li);
            }}
            if(playlistFiles.length === 0) list.innerHTML = '<li class="queue-item" style="color:#888; justify-content:center; background: transparent; border: none; cursor: default;">Очередь пуста. Выберите медиа из галереи.</li>';
        }}
        
        function openQueueModal() {{
            renderQueueItems();
            document.getElementById('queue-modal').classList.add('active');
        }}

        function startPlaylist() {{
            if(playlistFiles.length > 0) {{
                openOptionsModal(playlistFiles[0], playlistNames[0] + " (Плейлист)", true);
            }}
        }}

        window.addEventListener('DOMContentLoaded', () => {{
            sortCards();
            loadPlaylistFromServer();
        }});

        let currentFileSafeName = "";
        function openOptionsModal(safeName, displayName, isPlaylist = false) {{
            currentFileSafeName = safeName;
            document.getElementById('modal-filename-display').innerHTML = displayName;
            document.getElementById('fps-input').value = ''; 
            document.getElementById('options-modal').classList.add('active');
            
            if (isPlaylist) {{
                sessionStorage.setItem('ofavi_playlist_files', JSON.stringify(playlistFiles));
                sessionStorage.setItem('ofavi_playlist_names', JSON.stringify(playlistNames));
            }} else {{
                sessionStorage.setItem('ofavi_playlist_files', JSON.stringify([]));
                sessionStorage.setItem('ofavi_playlist_names', JSON.stringify([]));
            }}
            sessionStorage.setItem('ofavi_current_file', safeName);
        }}
        
        function closeModal(modalId) {{ document.getElementById(modalId).classList.remove('active'); }}

        async function startTranscoding(quality) {{
            closeModal('options-modal');
            const fpsValue = document.getElementById('fps-input').value;
            const overlay = document.getElementById('loading-overlay');
            const statusText = document.getElementById('status-text');
            const progressBar = document.getElementById('progress-bar');
            
            overlay.classList.add('active');
            progressBar.style.width = '15%';
            statusText.textContent = 'Анализ медиапотока...';
            
            try {{
                const startRes = await fetch('/prepare/' + currentFileSafeName, {{ 
                    method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ quality: quality, fps: fpsValue }})
                }});
                const data = await startRes.json();
                
                if (data.status === 'direct') {{
                    progressBar.style.width = '100%';
                    statusText.textContent = 'Короткое видео! Прямой запуск...';
                    let playerUrl = "/player?direct=" + encodeURIComponent(data.direct_url) + "&quality=" + quality + "&file=" + encodeURIComponent(currentFileSafeName);
                    setTimeout(() => window.location.href = playerUrl, 400);
                    return;
                }}
                
                progressBar.style.width = '40%';
                statusText.textContent = 'Рендеринг потока...';
                
                const checkInterval = setInterval(async () => {{
                    const statusRes = await fetch('/status/' + data.stream_id);
                    const st = await statusRes.json();
                    
                    if (st.ready) {{
                        clearInterval(checkInterval);
                        progressBar.style.width = '100%';
                        statusText.textContent = 'Готово! Запуск плеера...';
                        let playerUrl = "/player?stream=" + encodeURIComponent("/stream/" + data.stream_id + "/index.m3u8") + "&quality=" + quality + "&file=" + encodeURIComponent(currentFileSafeName);
                        setTimeout(() => window.location.href = playerUrl, 800);
                    }}
                }}, 2000);
            }} catch (e) {{
                statusText.textContent = 'Ошибка сервера!'; statusText.style.color = '#f44336';
                setTimeout(() => overlay.classList.remove('active'), 3000);
            }}
        }}
    </script>
</body>
</html>'''
    return render_template_string(html)

# ==========================================
# 2. МАРШРУТ: ЛОКАЛЬНЫЙ ПЛЕЕР (HTML)
# ==========================================
PLAYER_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>AVI Player</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.jsdelivr.net/npm/hls.js@1"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    
    <style>
        body { background: #0f0f1a; color: #bbdefb; font-family: sans-serif; margin: 0; display: flex; flex-direction: column; align-items: center; min-height: 100vh; overflow-x: hidden; }
        h2 { font-weight: 300; margin-top: 20px; }
        #player-wrapper { position: relative; width: 100%; max-width: 1000px; background: #000; border-radius: 12px; overflow: hidden; box-shadow: 0 15px 40px rgba(0,0,0,0.8); margin-top: 20px; user-select: none; }
        video { width: 100%; height: 100%; object-fit: contain; display: block; cursor: pointer; }
        
        /* Fullscreen adjustments */
        #player-wrapper:-webkit-full-screen { max-width: none !important; width: 100vw !important; height: 100vh !important; margin: 0 !important; border-radius: 0 !important; display: flex; align-items: center; justify-content: center; }
        #player-wrapper:-moz-full-screen { max-width: none !important; width: 100vw !important; height: 100vh !important; margin: 0 !important; border-radius: 0 !important; display: flex; align-items: center; justify-content: center; }
        #player-wrapper:fullscreen { max-width: none !important; width: 100vw !important; height: 100vh !important; margin: 0 !important; border-radius: 0 !important; display: flex; align-items: center; justify-content: center; }
        
        #player-wrapper.idle { cursor: none !important; }
        
        #custom-controls { position: absolute; bottom: 0; left: 0; width: 100%; background: rgba(15, 15, 26, 0.85); padding: 15px 20px; box-sizing: border-box; display: flex; align-items: center; gap: 15px; transform: translateY(100%); transition: 0.3s; z-index: 10; border-top: 1px solid rgba(255,255,255,0.1); backdrop-filter: blur(10px); }
        #player-wrapper:hover #custom-controls { transform: translateY(0); }
        #player-wrapper.idle #custom-controls { transform: translateY(100%) !important; }
        #player-wrapper.paused #custom-controls { transform: translateY(0) !important; }

        .ctrl-btn { background: none; border: none; color: #fff; font-size: 20px; cursor: pointer; transition: 0.2s; padding: 0; width: 30px; }
        .ctrl-btn:hover { color: #2196f3; }
        #next-btn { color: #ffca28; display: none; } #next-btn:hover { color: #fff; }

        #progress-container { flex-grow: 1; height: 6px; background: rgba(255,255,255,0.2); border-radius: 3px; cursor: pointer; position: relative; }
        #progress-fill { position: absolute; top: 0; left: 0; height: 100%; background: #2196f3; border-radius: 3px; width: 0%; pointer-events: none; transition: width 0.2s linear; }
        #time-display { font-size: 13px; color: #ddd; min-width: 100px; text-align: center; }

        .vol-wrapper { position: relative; display: flex; align-items: center; justify-content: center; width: 30px; }
        .vol-slider-container { position: absolute; bottom: 45px; left: 50%; transform: translateX(-50%); background: rgba(15, 15, 26, 0.9); padding: 15px 10px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); display: none; height: 100px; align-items: center; justify-content: center; backdrop-filter: blur(5px); }
        .vol-wrapper:hover .vol-slider-container { display: flex; }
        input[type="range"][orient="vertical"] { writing-mode: bt-lr; -webkit-appearance: slider-vertical; width: 8px; height: 100px; margin: 0; cursor: pointer; outline: none; background: transparent; }

        .tap-indicator { position: absolute; top: 50%; transform: translateY(-50%); color: white; font-size: 24px; background: rgba(0,0,0,0.6); padding: 15px 25px; border-radius: 30px; opacity: 0; pointer-events: none; display: flex; align-items: center; gap: 10px; z-index: 5; }
        .tap-indicator.left { left: 10%; } .tap-indicator.right { right: 10%; }
        .tap-indicator.pulse { animation: tapPulse 0.5s ease-out forwards; }
        @keyframes tapPulse { 0% { transform: translateY(-50%) scale(0.8); opacity: 1; } 100% { transform: translateY(-50%) scale(1.2); opacity: 0; } }

        #status-msg { margin-top: 15px; color: #888; font-size: 14px; text-align: center; }
        .back-gallery-btn { position: absolute; top: 20px; left: 20px; color: white; font-size: 24px; cursor: pointer; text-decoration: none; opacity: 0.7; transition: 0.2s; z-index: 100; }
        .back-gallery-btn:hover { opacity: 1; }
        
        #playlist-sidebar { position: fixed; right: 0; top: 0; bottom: 0; width: 300px; background: rgba(15,15,26,0.95); z-index: 2000; transform: translateX(100%); transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1); display: flex; flex-direction: column; border-left: 1px solid rgba(33,150,243,0.3); backdrop-filter: blur(15px); box-shadow: -5px 0 20px rgba(0,0,0,0.5); }
        #playlist-sidebar.active { transform: translateX(0); }
        .sidebar-header { padding: 20px; background: rgba(0,0,0,0.5); font-weight: bold; font-size: 16px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.1); color: #bbdefb; }
        #close-sidebar-btn { font-size: 20px; cursor: pointer; color: #888; transition: 0.2s; } #close-sidebar-btn:hover { color: #f44336; }
        #playlist-items { list-style: none; padding: 0; margin: 0; overflow-y: auto; flex-grow: 1; }
        #playlist-items::-webkit-scrollbar { width: 8px; }
        #playlist-items::-webkit-scrollbar-track { background: rgba(0,0,0,0.2); }
        #playlist-items::-webkit-scrollbar-thumb { background: #2196f3; border-radius: 4px; }
        .pl-item { padding: 15px 20px; border-bottom: 1px solid rgba(255,255,255,0.05); cursor: pointer; transition: 0.2s; color: #bbb; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .pl-item:hover { background: rgba(255,255,255,0.1); color: #fff; padding-left: 25px; }
        .pl-item.active { border-left: 4px solid #2196f3; color: #2196f3; background: rgba(33,150,243,0.1); font-weight: bold; }

        #loading-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(10, 10, 15, 0.95); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 1000; opacity: 0; visibility: hidden; transition: 0.4s; backdrop-filter: blur(15px); }
        #loading-overlay.active { opacity: 1; visibility: visible; }
        .loader-icon { font-size: 50px; color: #2196f3; margin-bottom: 20px; animation: spin 2s linear infinite; }
        @keyframes spin { 100% { transform: rotate(360deg); } }
        .status-text { font-size: 24px; font-weight: 300; margin-bottom: 15px; color: #bbdefb; }
        .progress-container-ld { width: 300px; height: 8px; background: rgba(255,255,255,0.1); border-radius: 4px; overflow: hidden; }
        .progress-bar-ld { height: 100%; width: 0%; background: linear-gradient(90deg, #2196f3, #00bcd4); transition: width 0.5s; }
    </style>
</head>
<body>
    <a href="/" class="back-gallery-btn"><i class="fas fa-arrow-left"></i></a>
    <h2><i class="fas fa-play-circle" style="color: #2196f3;"></i> AVI Player</h2>
    
    <div id="player-wrapper" class="paused">
        <video id="video"></video>
        <div id="tap-left" class="tap-indicator left"><i class="fas fa-backward"></i> 5 сек</div>
        <div id="tap-right" class="tap-indicator right">5 сек <i class="fas fa-forward"></i></div>
        
        <div id="custom-controls">
            <button id="play-pause-btn" class="ctrl-btn"><i class="fas fa-play"></i></button>
            <button id="next-btn" class="ctrl-btn" title="Следующее видео"><i class="fas fa-step-forward"></i></button>
            <div id="progress-container"><div id="progress-fill"></div></div>
            <div id="time-display">00:00 / 00:00</div>
            
            <div class="vol-wrapper">
                <button id="mute-btn" class="ctrl-btn"><i class="fas fa-volume-up"></i></button>
                <div class="vol-slider-container">
                    <input type="range" id="volume-slider" orient="vertical" min="0" max="1" step="0.05" value="1">
                </div>
            </div>
            
            <button id="playlist-toggle-btn" class="ctrl-btn" title="Плейлист" style="display: none;"><i class="fas fa-bars"></i></button>
            <button id="fullscreen-btn" class="ctrl-btn"><i class="fas fa-expand"></i></button>
        </div>
    </div>
    <div id="status-msg">Инициализация плеера...</div>

    <div id="playlist-sidebar">
        <div class="sidebar-header">Плейлист <i class="fas fa-times" id="close-sidebar-btn"></i></div>
        <ul id="playlist-items"></ul>
    </div>

    <div id="loading-overlay">
        <i class="fas fa-cog loader-icon"></i>
        <div class="status-text" id="status-text">Кодируем следующее видео...</div>
        <div class="progress-container-ld"><div class="progress-bar-ld" id="progress-bar"></div></div>
    </div>

    <script>
        var urlParams = new URLSearchParams(window.location.search);
        var streamUrl = urlParams.get('stream');
        var directUrl = urlParams.get('direct');
        var currentQuality = urlParams.get('quality') || 'medium';
        var currentFileName = urlParams.get('file') || sessionStorage.getItem('ofavi_current_file');
        
        var plFiles = JSON.parse(sessionStorage.getItem('ofavi_playlist_files') || "[]");
        var plNames = JSON.parse(sessionStorage.getItem('ofavi_playlist_names') || "[]");
        var currentIndex = plFiles.indexOf(currentFileName);

        var video = document.getElementById('video');
        var statusMsg = document.getElementById('status-msg');

        if (directUrl) {
            statusMsg.innerHTML = 'Прямой поток (короткое видео). Мгновенный запуск!';
            video.src = decodeURIComponent(directUrl);
            video.play().catch(e => { statusMsg.innerHTML = 'Поток готов. Нажмите Play для старта.'; });
        } else if (Hls.isSupported() && streamUrl) {
            var hls = new Hls({ maxBufferLength: 30, maxMaxBufferLength: 600, maxBufferHole: 0.5 });
            hls.loadSource(decodeURIComponent(streamUrl)); hls.attachMedia(video);
            hls.on(Hls.Events.MANIFEST_PARSED, function() { statusMsg.innerHTML = 'HLS Поток готов! Нажмите Play.'; });
        } else if (video.canPlayType('application/vnd.apple.mpegurl') && streamUrl) {
            video.src = decodeURIComponent(streamUrl);
        }

        var wrapper = document.getElementById('player-wrapper');
        var playBtn = document.getElementById('play-pause-btn');
        var muteBtn = document.getElementById('mute-btn');
        var volSlider = document.getElementById('volume-slider');
        var progressContainer = document.getElementById('progress-container');
        var progressFill = document.getElementById('progress-fill');
        var timeDisplay = document.getElementById('time-display');
        var fullscreenBtn = document.getElementById('fullscreen-btn');

        if (plFiles.length > 1) {
            document.getElementById('next-btn').style.display = 'block';
            document.getElementById('playlist-toggle-btn').style.display = 'block';
            let ul = document.getElementById('playlist-items');
            for(let i = 0; i < plFiles.length; i++) {
                let li = document.createElement('li');
                li.className = 'pl-item' + (i === currentIndex ? ' active' : '');
                li.innerText = plNames[i] || plFiles[i];
                li.title = plNames[i] || plFiles[i];
                li.onclick = () => playSpecificFile(i);
                ul.appendChild(li);
            }
        }

        document.getElementById('playlist-toggle-btn').addEventListener('click', () => {
            document.getElementById('playlist-sidebar').classList.add('active');
        });
        document.getElementById('close-sidebar-btn').addEventListener('click', () => {
            document.getElementById('playlist-sidebar').classList.remove('active');
        });

        function formatTime(sec) {
            if (isNaN(sec)) return "00:00";
            var m = Math.floor(sec / 60), s = Math.floor(sec % 60);
            return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
        }

        function togglePlay() { video.paused ? video.play() : video.pause(); }
        
        video.addEventListener('play', () => {
            playBtn.innerHTML = '<i class="fas fa-pause"></i>'; 
            wrapper.classList.remove('paused');
            resetActivity();
        });
        video.addEventListener('pause', () => {
            playBtn.innerHTML = '<i class="fas fa-play"></i>'; 
            wrapper.classList.add('paused');
        });
        video.addEventListener('click', togglePlay);
        playBtn.addEventListener('click', togglePlay);

        volSlider.addEventListener('input', function() {
            video.volume = this.value; video.muted = (this.value == 0);
            muteBtn.innerHTML = video.muted ? '<i class="fas fa-volume-mute"></i>' : '<i class="fas fa-volume-up"></i>';
        });
        muteBtn.addEventListener('click', function() {
            video.muted = !video.muted;
            if (!video.muted && video.volume == 0) { video.volume = 1; volSlider.value = 1; }
            volSlider.value = video.muted ? 0 : video.volume;
            muteBtn.innerHTML = video.muted ? '<i class="fas fa-volume-mute"></i>' : '<i class="fas fa-volume-up"></i>';
        });

        // Кроссбраузерный полноэкранный режим
        fullscreenBtn.addEventListener('click', function() {
            if (!document.fullscreenElement && !document.webkitFullscreenElement && !document.mozFullScreenElement && !document.msFullscreenElement) {
                if (wrapper.requestFullscreen) { wrapper.requestFullscreen(); }
                else if (wrapper.webkitRequestFullscreen) { wrapper.webkitRequestFullscreen(); }
                else if (wrapper.mozRequestFullScreen) { wrapper.mozRequestFullScreen(); }
                else if (wrapper.msRequestFullscreen) { wrapper.msRequestFullscreen(); }
            } else {
                if (document.exitFullscreen) { document.exitFullscreen(); }
                else if (document.webkitExitFullscreen) { document.webkitExitFullscreen(); }
                else if (document.mozCancelFullScreen) { document.mozCancelFullScreen(); }
                else if (document.msExitFullscreen) { document.msExitFullscreen(); }
            }
        });

        progressContainer.addEventListener('click', function(e) {
            var rect = progressContainer.getBoundingClientRect();
            video.currentTime = ((e.clientX - rect.left) / rect.width) * video.duration;
        });

        video.addEventListener('timeupdate', function() {
            if (!video.duration) return;
            progressFill.style.width = ((video.currentTime / video.duration) * 100) + '%';
            timeDisplay.innerText = formatTime(video.currentTime) + " / " + formatTime(video.duration);
        });
        
        video.addEventListener('ended', function() {
            if (plFiles.length > 0 && currentIndex >= 0 && currentIndex < plFiles.length - 1) playNextInPlaylist();
        });

        function playNextInPlaylist() {
            if (currentIndex < 0 || currentIndex >= plFiles.length - 1) return;
            playSpecificFile(currentIndex + 1);
        }

        document.getElementById('next-btn').addEventListener('click', playNextInPlaylist);

        function playSpecificFile(index) {
            if (index < 0 || index >= plFiles.length) return;
            var nextFile = plFiles[index];
            sessionStorage.setItem('ofavi_current_file', nextFile);
            
            document.getElementById('loading-overlay').classList.add('active');
            document.getElementById('progress-bar').style.width = '25%';
            if(video.play) video.pause();
            
            fetch('/prepare/' + nextFile, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ quality: currentQuality, fps: '' })
            }).then(r => r.json()).then(data => {
                if (data.status === 'direct') {
                    document.getElementById('progress-bar').style.width = '100%';
                    window.location.href = "/player?direct=" + encodeURIComponent(data.direct_url) + "&quality=" + currentQuality + "&file=" + encodeURIComponent(nextFile);
                    return;
                }
                
                document.getElementById('progress-bar').style.width = '60%';
                var checkInterval = setInterval(function() {
                    fetch('/status/' + data.stream_id).then(r => r.json()).then(st => {
                        if(st.ready) {
                            clearInterval(checkInterval);
                            document.getElementById('progress-bar').style.width = '100%';
                            window.location.href = "/player?stream=" + encodeURIComponent("/stream/" + data.stream_id + "/index.m3u8") + "&quality=" + currentQuality + "&file=" + encodeURIComponent(nextFile);
                        }
                    });
                }, 2000);
            });
        }

        document.addEventListener('keydown', function(e) {
            if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
            if (e.code === 'ArrowRight') { video.currentTime += 5; }
            if (e.code === 'ArrowLeft') { video.currentTime -= 5; }
            if (e.code === 'KeyF') { fullscreenBtn.click(); }
            if (e.code === 'KeyM') { muteBtn.click(); }
        });
        
        var hideControlsTimer = null;
        function resetActivity() {
            wrapper.classList.remove('idle'); clearTimeout(hideControlsTimer);
            if (!video.paused) hideControlsTimer = setTimeout(() => wrapper.classList.add('idle'), 2500);
        }
        wrapper.addEventListener('mousemove', resetActivity);
    </script>
</body>
</html>"""

@app.route('/player')
def serve_player():
    return render_template_string(PLAYER_HTML)

# ==========================================
# 3. МАРШРУТ: ГЕНЕРАЦИЯ ПРЕВЬЮ (THUMBNAIL)
# ==========================================
@app.route('/thumbnail/<path:filename>')
def get_thumbnail(filename):
    video_path = get_secure_path(filename)
    if not video_path: return "Access Denied", 403
    
    ext = os.path.splitext(video_path)[1].lower()
    if ext in {'.mp3', '.wav', '.flac'}: return "Audio", 404

    file_hash = hashlib.md5(video_path.encode()).hexdigest()
    thumb_path = os.path.join(THUMB_DIR, f"{file_hash}.jpg")

    if not os.path.exists(thumb_path):
        subprocess.run(['ffmpeg', '-y', '-i', video_path, '-vf', r'select=gte(n\,100),scale=320:-2', '-vframes', '1', thumb_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)

    return send_from_directory(THUMB_DIR, f"{file_hash}.jpg") if os.path.exists(thumb_path) else ("Failed", 404)

# ==========================================
# 4. МАРШРУТ: ПОДГОТОВКА С ПРОВЕРКОЙ НА КРАТКОСТЬ (УМНЫЙ ПОТОК)
# ==========================================
@app.route('/prepare/<path:filename>', methods=['POST'])
def prepare_video(filename):
    global current_ffmpeg_process
    
    video_path = get_secure_path(filename)
    if not video_path: return "Access Denied", 403
    
    data = request.json or {}
    quality = data.get('quality', 'medium')
    fps = data.get('fps', '').strip()

    file_size = os.stat(video_path).st_size
    cache_key = f"{os.path.basename(video_path)}_{file_size}"
    
    duration = 0.0
    with meta_lock:
        if os.path.exists(META_FILE):
            try:
                with open(META_FILE, 'r') as f:
                    meta_cache = json.load(f)
                    duration = meta_cache.get(cache_key, 0.0)
            except Exception: pass

    if duration == 0.0:
        duration = get_media_duration(video_path)
        with meta_lock:
            meta_cache = {}
            if os.path.exists(META_FILE):
                try:
                    with open(META_FILE, 'r') as f: meta_cache = json.load(f)
                except Exception: pass
            meta_cache[cache_key] = duration
            try:
                with open(META_FILE, 'w') as f: json.dump(meta_cache, f)
            except Exception: pass

    if 0 < duration < 120:
        return jsonify({"status": "direct", "direct_url": f"/direct/{filename}"})

    stream_id = hashlib.md5(f"{filename}_{quality}_{fps}".encode()).hexdigest()
    stream_dir = os.path.join(HLS_CACHE, stream_id)
    os.makedirs(stream_dir, exist_ok=True)
    m3u8_file = os.path.join(stream_dir, 'index.m3u8')

    if not os.path.exists(m3u8_file):
        if current_ffmpeg_process is not None:
            try:
                current_ffmpeg_process.terminate()
                current_ffmpeg_process.wait(timeout=2)
            except Exception:
                try: current_ffmpeg_process.kill() 
                except: pass

        total_cores = os.cpu_count() or 4
        threads_to_use = max(1, int(total_cores * 0.75))
        
        command = ['ffmpeg', '-i', video_path, '-c:v', 'libx264', '-g', '50', '-keyint_min', '50', '-sc_threshold', '0', '-threads', str(threads_to_use)]
        if fps and fps.isdigit(): command.extend(['-r', fps])

        if quality == 'low': command.extend(['-preset', 'ultrafast', '-vf', 'scale=-2:360', '-crf', '32', '-maxrate', '400k', '-bufsize', '800k', '-c:a', 'aac', '-b:a', '64k'])
        elif quality == 'high': command.extend(['-preset', 'ultrafast', '-crf', '23', '-maxrate', '5000k', '-bufsize', '10000k', '-c:a', 'aac', '-b:a', '192k'])
        elif quality == 'cinema': command.extend(['-preset', 'medium', '-vf', 'scale=-2:720', '-crf', '24', '-maxrate', '2500k', '-bufsize', '5000k', '-c:a', 'aac', '-b:a', '192k'])
        else: command.extend(['-preset', 'ultrafast', '-vf', 'scale=-2:720', '-crf', '28', '-maxrate', '1500k', '-bufsize', '3000k', '-c:a', 'aac', '-b:a', '128k'])

        command.extend(['-start_number', '0', '-hls_time', '5', '-hls_list_size', '0', '-hls_playlist_type', 'event', '-f', 'hls', m3u8_file])
        
        print(f"Запуск FFmpeg HLS: {quality} | Выделено ядер: {threads_to_use}")
        current_ffmpeg_process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    return jsonify({"status": "processing", "stream_id": stream_id})

# ==========================================
# 5. МАРШРУТ: ОТДАЧА ПРЯМОГО СТРИМА
# ==========================================
@app.route('/direct/<path:filename>')
def serve_direct(filename):
    video_path = get_secure_path(filename)
    if not video_path: return "Access Denied", 403
    return send_from_directory(os.path.dirname(video_path), os.path.basename(video_path))

@app.route('/status/<stream_id>')
def check_status(stream_id):
    stream_dir = os.path.join(HLS_CACHE, stream_id)
    return jsonify({"ready": os.path.exists(os.path.join(stream_dir, 'index.m3u8')) and len([f for f in os.listdir(stream_dir) if f.endswith('.ts')]) >= 1})

@app.route('/stream/<stream_id>/<path:file>')
def serve_hls(stream_id, file):
    return send_from_directory(os.path.join(HLS_CACHE, stream_id), file)

if __name__ == '__main__':
    print(f"🚀 [On-Premise Ultimate V3] AVI Media Core запущен на порту {PORT}!")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
