#!/usr/bin/env python3
from flask import Flask, request, jsonify, send_file, Response, redirect
import os
import re
import uuid
import time
import json
import urllib.parse
import requests
import subprocess
import shutil

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HLS_DIR = os.path.join(BASE_DIR, '_hls')
os.makedirs(HLS_DIR, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://cineflix.is/',
}

session = requests.Session()
session.headers.update(HEADERS)

M3U_URL_RE = re.compile(r'^(https?://\S+)$')
MOBILE_RE = re.compile(r'Mobi|Android|iPhone|iPad|iPod|webOS|BlackBerry|Opera Mini|IEMobile|Touch|Silk', re.I)

HLS_SESSIONS = {}

def _cleanup_old_sessions():
    now = time.time()
    expired = [sid for sid, s in HLS_SESSIONS.items() if now - s.get('ts', 0) > 120]
    for sid in expired:
        try:
            s = HLS_SESSIONS[sid]
            p = s.get('proc')
            if p and p.poll() is None:
                p.kill()
            d = s.get('dir')
            if d and os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
        except:
            pass
        HLS_SESSIONS.pop(sid, None)

def _start_hls(url, sid):
    d = os.path.join(HLS_DIR, sid)
    os.makedirs(d, exist_ok=True)
    m3u8_path = os.path.join(d, 'playlist.m3u8')
    proc = subprocess.Popen([
        'ffmpeg', '-hide_banner', '-loglevel', 'warning',
        '-i', url,
        '-c', 'copy',
        '-f', 'hls',
        '-hls_time', '4',
        '-hls_list_size', '10',
        '-hls_flags', 'append_list',
        m3u8_path
    ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    HLS_SESSIONS[sid] = {'url': url, 'dir': d, 'm3u8': m3u8_path, 'proc': proc, 'ts': time.time()}
    return d, m3u8_path

@app.route('/')
def index():
    ua = request.headers.get('User-Agent', '')
    w = request.args.get('w', '')
    if MOBILE_RE.search(ua) or w == 'm':
        return send_file(os.path.join(BASE_DIR, 'mobile.html'))
    return send_file(os.path.join(BASE_DIR, 'tv.html'))

@app.route('/player')
def api_player():
    url = request.args.get('url', '')
    if not url:
        return 'Missing URL', 400
    safe_url = url.replace('"', '\\"').replace("'", "\\'")
    proxy_url = '/stream?url=' + urllib.parse.quote(url, safe='')
    return '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>SŌF MOJITO TV</title>
<style>*{margin:0;padding:0}html,body{width:100%;height:100%;background:#000}video{width:100%;height:100%;background:#000}#back{position:fixed;top:10px;left:10px;z-index:10;background:rgba(139,0,0,0.9);color:#fff;padding:12px 18px;border-radius:8px;font-size:18px;border:none}</style></head><body>
<video id="v" playsinline webkit-playsinline controls></video>
<button id="back" onclick="history.back()">← Volver</button>
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script><script>
var v=document.getElementById("v");
if(typeof Hls!=="undefined"&&Hls.isSupported()){
    var h=new Hls({maxBufferLength:30});
    h.loadSource("''' + proxy_url + '''");h.attachMedia(v);
    h.on(Hls.Events.MANIFEST_PARSED,function(){v.play().catch(function(){})});
}else if(v.canPlayType("application/vnd.apple.mpegurl")){v.src="''' + proxy_url + '''";v.play().catch(function(){})}
</script></body></html>'''

@app.route('/stream')
def api_stream():
    url = request.args.get('url', '')
    if not url:
        return 'Missing URL', 400
    try:
        r = session.head(url, timeout=10, allow_redirects=True)
        ct = r.headers.get('Content-Type', '')
    except:
        ct = ''
    if 'mpegurl' in ct or 'm3u8' in ct or 'x-mpegurl' in ct or url.endswith('.m3u8'):
        try:
            r = session.get(url, stream=True, timeout=30, headers={
                'Referer': 'https://cineflix.is/',
                'User-Agent': HEADERS['User-Agent']
            })
            if r.status_code != 200:
                return 'Stream error', r.status_code
            base = url.rsplit('/', 1)[0] + '/'
            body = []
            for line in r.iter_lines(decode_unicode=True):
                line = line.strip()
                if not line or line.startswith('#'):
                    body.append(line)
                elif line.startswith('http'):
                    body.append('/stream?url=' + urllib.parse.quote(line, safe=''))
                else:
                    body.append('/stream?url=' + urllib.parse.quote(base + line, safe=''))
            resp = Response('\n'.join(body) + '\n', mimetype='application/vnd.apple.mpegurl')
            resp.headers['Access-Control-Allow-Origin'] = '*'
            return resp
        except:
            return 'Stream error', 500
    _cleanup_old_sessions()
    sid = str(uuid.uuid4())
    _start_hls(url, sid)
    for _ in range(20):
        time.sleep(0.5)
        m3u8 = HLS_SESSIONS[sid]['m3u8']
        if os.path.isfile(m3u8):
            try:
                with open(m3u8) as f:
                    if 'EXTINF' in f.read():
                        break
            except:
                pass
    return redirect(f'/hls/{sid}/playlist.m3u8')

@app.route('/hls/<sid>/playlist.m3u8')
def hls_playlist(sid):
    s = HLS_SESSIONS.get(sid)
    if not s or not os.path.isfile(s['m3u8']):
        return 'Not found', 404
    s['ts'] = time.time()
    with open(s['m3u8']) as f:
        raw = f.read()
    lines = []
    for line in raw.splitlines():
        if line.endswith('.ts'):
            lines.append(f'/hls/{sid}/{line}')
        else:
            lines.append(line)
    resp = Response('\n'.join(lines) + '\n', mimetype='application/vnd.apple.mpegurl')
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

@app.route('/hls/<sid>/<fname>')
def hls_segment(sid, fname):
    s = HLS_SESSIONS.get(sid)
    if not s:
        return 'Not found', 404
    s['ts'] = time.time()
    fpath = os.path.join(s['dir'], fname)
    if not os.path.isfile(fpath):
        return 'Not found', 404
    return send_file(fpath, mimetype='video/MP2T')

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip().lower()
    try:
        page = int(request.args.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    if page < 1:
        page = 1

    if not q:
        return jsonify({'streams': []})

    limit = 50
    start_idx = (page - 1) * limit

    try:
        resp = session.get(
            f'https://cineflix.is/search/?query={urllib.parse.quote(q)}',
            timeout=60
        )

        if resp.status_code != 200:
            return jsonify({'streams': []})

        try:
            data = resp.json()
        except ValueError:
            return jsonify({'streams': []})

        if not isinstance(data, dict) or not data:
            return jsonify({'streams': []})

        items = list(data.keys())
        if start_idx >= len(items):
            return jsonify({'streams': [], 'hasMore': False})

        streams = []
        downloaded = 0
        i = start_idx

        while downloaded < limit and i < len(items):
            try:
                item_id = items[i]
                title = data[item_id].get('title', item_id)
                
                # Try stream endpoint first (for TV-like content)
                stream_resp = session.get(
                    f'https://cineflix.is/stream/uuid/{item_id}/',
                    timeout=30,
                    allow_redirects=True
                )
                
                url = ''
                if stream_resp.status_code == 200 and '#EXTM3U' in stream_resp.text:
                    # Extract M3U8 URL from stream response
                    for line in stream_resp.text.splitlines():
                        if M3U_URL_RE.match(line.strip()):
                            url = line.strip()
                            break
                
                # If stream endpoint fails, try movie page
                if not url:
                    page_resp = session.get(
                        f'https://cineflix.is/{item_id}/',
                        timeout=30
                    )
                    if page_resp.status_code == 200:
                        # Extract m3u8/mp4 links from page HTML
                        import re as regex
                        # Find all m3u8/mp4 URLs in the page
                        links = regex.findall(r'https?://[^\s"\'<>]+\.(m3u8|mp4)[^\s"\'<>]*', page_resp.text)
                        if links:
                            url = links[0]
                        # Also check for src attributes in video/iframe tags
                        if not url:
                            src_links = regex.findall(r'(?:src|data-src)="(https?://[^\s"]+\.(?:m3u8|mp4|video)[^\s"]*)"', page_resp.text)
                            if src_links:
                                url = src_links[0]
                
                if url:
                    streams.append({'title': title, 'url': url})
                    downloaded += 1
                else:
                    i += 1
                    continue
            except requests.exceptions.RequestException:
                pass
            i += 1
                    continue
                
                # Extract m3u8/mp4 URLs from page
                page_text = page_resp.text
                url = ''
                
                # Look for m3u8 or mp4 links
                import re as regex
                links = regex.findall(r'https?://[^\s"\']+\.(m3u8|mp4)[^\s"\']*', page_text)
                if links:
                    url = links[0]
                
                # Also check for video src attributes
                if not url:
                    src_links = regex.findall(r'src="(https?://[^\s"]+\.(m3u8|mp4)[^\s"]*)"', page_text)
                    if src_links:
                        url = src_links[0][0]
                
                if url:
                    streams.append({'title': title, 'url': url})
                    downloaded += 1
                else:
                    i += 1
                    continue
            except requests.exceptions.RequestException:
                pass
            i += 1

        streams.sort(key=lambda x: 0 if re.search(r'1080|4k|uhd', x['title'], re.I) else 1 if re.search(r'720|hd', x['title'], re.I) else 2)

        has_more = i < len(items)

        return jsonify({'streams': streams, 'hasMore': has_more})

    except Exception as e:
        return jsonify({'streams': [], 'error': str(e)[:50]})

if __name__ == '__main__':
    print('SŌF TV - HLS Transcode + Fast HD Priority')
    app.run(host='0.0.0.0', port=8080, threaded=True, debug=False)
