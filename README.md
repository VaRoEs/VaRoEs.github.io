# AVI Media Core 📺

**Your own sovereign, minimalist media streaming infrastructure.**
WORK ON WINDOWS 7!
AVI Media Core is a "YouTube for the minimalist." It is a lightweight, self-hosted media streaming solution designed for performance, portability, and sovereignty. No bloated databases, no heavy dependencies, no corporate tracking — just pure, efficient streaming.

### ⚡ Why?
Most modern media servers (like Jellyfin or Plex) are "over-engineered" — they require heavy databases, massive RAM, and constant updates. AVI Media Core goes the opposite way:
* **Minimalist Architecture:** Flask + Python + FFmpeg. That's it.
* **Sovereign Infrastructure:** Your data stays on your machine; your frontend lives on secure GitHub Pages.
* **Performance:** Works on old hardware (Win7/Linux/macOS) and low-end devices.
* **No Bloat:** No unnecessary telemetry or complex dependency hell.

### 🚀 How it works
1. **The Core:** A lightweight Python script handles HLS transcoding on-the-fly using FFmpeg.
2. **The Frontend:** A sleek, custom-built HTML5/JS player that lives on GitHub Pages.
3. **The Connection:** It treats your browser as the client and your machine as the CDN, allowing you to stream your own library anywhere.

### 🛠 Quick Start

1. **Install FFmpeg:** Download and put `ffmpeg.exe` in the same folder as the script.
2. **Configure:** Edit the `FOLDER` variable in `avi.py` to point to your video library.
3. **Make:**
   ```bash
   pip install flask flask-cors
5. **Run:**
   ```bash
   python avi.py

⚙️ Features
HLS Streaming: Dynamic video chunking for smooth playback.

Smart Buffering: Minimal memory usage by utilizing disk-based "swapping" logic.

Keyboard Shortcuts: Full control (Space, Arrows, F, M).

Zero Database: Everything is managed through filesystem lookups and lightweight JSON logs.

🛡 Philosophy
Don't build for the masses. Build for yourself. AVI Media Core is a protest against bloated software. It’s a tool for those who want to control their digital space without the overhead of enterprise-grade complexity.

Created with the philosophy of "Less is More".
<img width="1099" height="479" alt="Screenshot_30" src="https://github.com/user-attachments/assets/58eb3299-a0ff-4fd0-84ca-2e68d88199c3" />
<img width="985" height="596" alt="Screenshot_31" src="https://github.com/user-attachments/assets/70a3c440-aae4-4fd6-a960-5802312f8bec" />
<img width="1275" height="860" alt="Screenshot_33" src="https://github.com/user-attachments/assets/d49f0345-cf3c-4cd1-ac17-215c742a8162" />
<img width="577" height="455" alt="Screenshot_34" src="https://github.com/user-attachments/assets/d1a1acd0-b0d8-477e-8917-91050dba005d" />
Write custom fps, but if you dont write, you can use video original fps.
And executable files, ll be made in future.
