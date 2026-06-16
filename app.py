import os
import json
import requests
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import re

app = Flask(__name__)
CORS(app)

# Store for data received from extension
captured_streams = {}

@app.route("/")
def index():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StreamIMDB Pro Hub (v7)</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #0a0a0a; color: #e0e0e0; margin: 0; padding: 20px; }
        .container { max-width: 900px; margin: 0 auto; }
        header { text-align: center; padding: 40px 0; border-bottom: 1px solid #333; margin-bottom: 30px; }
        h1 { color: #bb86fc; margin: 0; font-size: 2.5rem; }
        .status-card { background: #1e1e1e; padding: 20px; border-radius: 12px; border-left: 5px solid #03dac6; margin-bottom: 30px; }
        .stream-card { background: #1e1e1e; padding: 25px; border-radius: 12px; margin-bottom: 20px; border: 1px solid #333; position: relative; }
        .stream-card:hover { border-color: #bb86fc; }
        .tag { display: inline-block; background: #bb86fc; color: #000; padding: 3px 10px; border-radius: 4px; font-size: 0.75rem; font-weight: bold; margin-bottom: 10px; }
        .url-text { background: #000; padding: 12px; border-radius: 6px; font-family: monospace; font-size: 0.85rem; word-break: break-all; margin: 10px 0; border: 1px solid #222; color: #03dac6; }
        .proxy-box { margin-top: 20px; }
        .proxy-url { background: #121212; padding: 15px; border-radius: 6px; font-family: monospace; font-size: 1rem; color: #ff79c6; border: 1px dashed #444; word-break: break-all; }
        .btn { background: #bb86fc; color: #000; border: none; padding: 12px 25px; border-radius: 6px; cursor: pointer; font-weight: bold; transition: 0.3s; margin-top: 15px; }
        .btn:hover { background: #d7b7fd; transform: translateY(-2px); }
        .empty-state { text-align: center; padding: 60px; color: #666; font-style: italic; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>StreamIMDB Pro Hub</h1>
            <p>Waiting for links from your Brave Extension...</p>
        </header>

        <div class="status-card">
            <strong>System Status:</strong> Active & Listening on Port 5000<br>
            <small>If you don't see links, ensure you've clicked "Update" in brave://extensions and re-played the video.</small>
        </div>

        <div id="streamList">
            <div class="empty-state" id="emptyMsg">No streams captured yet. Start a video to see links here.</div>
            <div id="listContent"></div>
        </div>
    </div>

    <script>
        async function updateList() {
            try {
                const response = await fetch('/streams');
                const data = await response.json();
                const container = document.getElementById('listContent');
                const emptyMsg = document.getElementById('emptyMsg');
                
                const streamIds = Object.keys(data).filter(id => data[id].url.includes('.m3u8') || data[id].url.includes('.mp4'));
                
                if (streamIds.length === 0) {
                    emptyMsg.style.display = 'block';
                    container.innerHTML = "";
                    return;
                }

                emptyMsg.style.display = 'none';
                let html = "";
                for (const id of streamIds) {
                    const item = data[id];
                    // Ensure all links are proxied
                    const proxyUrl = `http://${window.location.hostname}:5000/proxy/${id}/playlist.m3u8`;
                    html += `
                        <div class="stream-card">
                            <span class="tag">DETECTED STREAM</span>
                            <div><strong>Source:</strong></div>
                            <div class="url-text">${item.url}</div>
                            
                            <div class="proxy-box">
                                <strong>Your Proxied Link (Bypasses Redirection):</strong>
                                <div class="proxy-url" id="url-${id}">${proxyUrl}</div>
                                <button class="btn" onclick="copyText('url-${id}')">COPY PROXY LINK</button>
                            </div>
                        </div>
                    `;
                }
                container.innerHTML = html;
            } catch (e) {}
        }

        function copyText(id) {
            const text = document.getElementById(id).innerText;
            navigator.clipboard.writeText(text);
            alert("Copied to clipboard!");
        }

        setInterval(updateList, 1500);
    </script>
</body>
</html>
"""

@app.route("/receive", methods=["POST"])
def receive():
    data = request.json
    url = data.get('url')
    if not url: return jsonify({"error": "No URL"}), 400
    
    stream_id = str(hash(url))
    captured_streams[stream_id] = data
    
    print("\n" + "="*50)
    print(f"[SUCCESS] CAPTURED NEW STREAM")
    print(f"URL: {url[:80]}...")
    print("="*50 + "\n")
    
    return jsonify({"status": "ok", "id": stream_id})

@app.route("/streams")
def get_streams():
    return jsonify(captured_streams)

def get_absolute_url(base, relative):
    if relative.startswith('http'):
        return relative
    return os.path.join(base, relative)

@app.route("/proxy/<stream_id>/playlist.m3u8")
def proxy_m3u8(stream_id):
    if stream_id not in captured_streams:
        return "Stream not found", 404
    
    stream_data = captured_streams[stream_id]
    target_url = stream_data['url']
    headers = stream_data['headers']
    
    print(f"[PROXY] Fetching M3U8: {target_url[:60]}...")
    
    try:
        resp = requests.get(target_url, headers=headers, timeout=10)
        resp.raise_for_status() # Raise an exception for HTTP errors
        content = resp.text
        
        base_url_match = re.match(r'(https?://[^/]+(?:/[^/]+)*)/', target_url)
        base_url = base_url_match.group(1) if base_url_match else target_url.rsplit('/', 1)[0]
        
        new_lines = []
        for line in content.splitlines():
            if line.startswith('#') or not line.strip():
                new_lines.append(line)
            else:
                # Handle relative URLs in M3U8 playlists
                full_segment_url = get_absolute_url(base_url, line)
                
                # If it's another M3U8 or MP4, proxy it too
                if '.m3u8' in full_segment_url or '.mp4' in full_segment_url:
                    segment_id = str(hash(full_segment_url))
                    captured_streams[segment_id] = {"url": full_segment_url, "headers": headers}
                    new_lines.append(f"http://localhost:5000/proxy/{segment_id}/playlist.m3u8")
                else:
                    # Otherwise, it's a segment, proxy it as a segment
                    segment_id = str(hash(full_segment_url))
                    captured_streams[segment_id] = {"url": full_segment_url, "headers": headers}
                    new_lines.append(f"http://localhost:5000/proxy_segment/{segment_id}")
            
    
        return Response("\n".join(new_lines), mimetype='application/vnd.apple.mpegurl')
    except requests.exceptions.RequestException as e:
        print(f"[PROXY ERROR] Failed to fetch M3U8 from {target_url}: {e}")
        return str(e), 500

@app.route("/proxy_segment/<segment_id>")
def proxy_segment(segment_id):
    if segment_id not in captured_streams:
        return "Segment not found", 404
        
    stream_data = captured_streams[segment_id]
    target_url = stream_data['url']
    headers = stream_data['headers']
    
    print(f"[PROXY] Fetching Segment: {target_url[:60]}...")
    
    try:
        req = requests.get(target_url, headers=headers, stream=True, timeout=15)
        req.raise_for_status() # Raise an exception for HTTP errors
        return Response(stream_with_context(req.iter_content(chunk_size=4096)), 
                        content_type=req.headers.get('content-type', 'video/MP2T'))
    except requests.exceptions.RequestException as e:
        print(f"[PROXY ERROR] Failed to fetch segment from {target_url}: {e}")
        return str(e), 500

if __name__ == "__main__":
    print("\n" + "*"*40)
    print("  STREAMIMDB PRO HUB IS RUNNING")
    print("  URL: http://localhost:5000")
    print("*"*40 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
