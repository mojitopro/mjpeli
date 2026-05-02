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
    # Get recent movies and series using cloudscraper to bypass Cloudflare
    try:
        import cloudscraper
        import re as regex

        # Use cloudscraper to bypass Cloudflare
        scraper = cloudscraper.create_scraper()
        resp = scraper.get('https://cineflix.is/search/?query=2026', timeout=60)

        if resp.status_code != 200:
            return f'Error loading content: {resp.status_code}', 500

        try:
            data = resp.json()
        except:
            return 'Error parsing content', 500

        items = list(data.keys())[:24]  # Get first 24 results

        # Build HTML
        html = '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CineFlix - Movies & Series</title>
<style>
* { margin:0; padding:0; box-sizing: border-box; }
body { font-family: Arial, sans-serif; background: #000; color: #fff; }
.container { max-width: 1200px; margin:0 auto; padding: 20px; }
h1 { color: #b78a62; margin-bottom: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px; }
.card { background: #111; border-radius: 8px; overflow: hidden; cursor: pointer; transition: transform 0.2s; }
.card:hover { transform: scale(1.05); }
.card-body { padding: 10px; }
.card-title { font-size: 14px; margin-bottom: 5px; }
.card:hover .card-title { color: #b78a62; }
</style></head><body>
<div class="container">
    <h1>CineFlix - Recent Movies & Series 2026</h1>

    <div class="grid">'''

        # Add items
        for item_id in items:
            title = data[item_id].get('title', item_id)
            # Extract IMDB ID from item_id (mm... or ss... -> tt...)
            imdb_id = item_id.replace('mm', 'tt').replace('ss', 'tt')
            html += f'<div class="card" onclick="location.href=\'/player?url={urllib.parse.quote("https://player.how/movie/?imdb_id=" + imdb_id, safe="")}\'"><div class="card-body"><div class="card-title">{title}</div></div></div>'

        html += '''</div></div>
</body></html>'''
        return html
    except Exception as e:
        return f'Error: {str(e)[:100]}', 500

@app.route('/player')
def api_player():
    url = request.args.get('url', '')
    if not url:
        return 'Missing URL', 400
    safe_url = url.replace('"', '\\"').replace("'", "\\'")
    return '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>CineFlix</title>
<style>*{margin:0;padding:0}html,body{width:100%;height:100%;background:#000}iframe{width:100%;height:100%;border:none}#back{position:fixed;top:10px;left:10px;z-index:10;background:rgba(139,0,0,0.9);color:#fff;padding:12px 18px;border-radius:8px;font-size:18px;border:none}</style></head><body>
<iframe id="player" src="''' + safe_url + '''" allowfullscreen allow="autoplay; fullscreen; picture-in-picture; encrypted-media"></iframe>
<button id="back" onclick="history.back()">← Volver</button>
</body></html>'''

@app.route('/stream')
def api_stream():
    url = request.args.get('url', '')
    if not url:
        return 'Missing URL', 400

    # Handle player.how URLs with Cloudflare bypass
    if 'player.how' in url:
        try:
            import cloudscraper
            from playwright.sync_api import sync_playwright
            import re as regex

            # Use cloudscraper to get Cloudflare cookies
            scraper = cloudscraper.create_scraper()
            scraper.get('https://player.how/', timeout=30)

            # Use playwright with cloudscraper cookies to render JavaScript
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )

                # Add cloudscraper cookies to playwright
                for cookie in scraper.cookies:
                    context.add_cookies([{
                        'name': cookie.name,
                        'value': cookie.value,
                        'domain': cookie.domain,
                        'path': cookie.path,
                    }])

                page = context.new_page()
                page.goto(url, wait_until='networkidle', timeout=30000)

                # Get the iframe src (which should be the stream URL)
                iframe_src = page.get_attribute('iframe#player', 'src')
                if not iframe_src:
                    iframe_src = page.evaluate('''() => {
                        const iframe = document.getElementById("player");
                        return iframe ? iframe.src : null;
                    }''')

                browser.close()

                if iframe_src and iframe_src.startswith('http'):
                    # Check if it's an m3u8/mp4 URL
                    if '.m3u8' in iframe_src or '.mp4' in iframe_src:
                        return redirect(f'/stream?url={urllib.parse.quote(iframe_src, safe="")}')
                    else:
                        # It's another page, fetch it
                        return redirect(f'/stream?url={urllib.parse.quote(iframe_src, safe="")}')

            return 'Unable to extract stream from player.how', 502
        except Exception as e:
            return f'Error: {str(e)[:100]}', 502

    # Handle regular m3u8 streams
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
        # Use cloudscraper to bypass Cloudflare
        import cloudscraper
        scraper = cloudscraper.create_scraper()
        
        resp = scraper.get(
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

                # Extract stream URL using cloudscraper
                page_resp = scraper.get(
                    f'https://movies.cineflix.is/watch/{item_id}/',
                    timeout=30
                )

                url = ''
                if page_resp.status_code == 200:
                    html = page_resp.text

                    # Extract player.how URL from iframe
                    import re as regex
                    player_match = regex.search(r'data-src="(https?://player\.how[^"]+)"', html)
                    if player_match:
                        url = player_match.group(1)
                    
                    if not url:
                        player_match = regex.search(r'<iframe[^>]+src="(https?://player\.how[^"]+)"', html)
                        if player_match:
                            url = player_match.group(1)

                if url:
                    streams.append({'title': title, 'url': url})
                    downloaded += 1
                else:
                    i += 1
                    continue
            except Exception:
                pass
            i += 1

        streams.sort(key=lambda x: 0 if re.search(r'1080|4k|uhd', x['title'], re.I) else 1 if re.search(r'720|hd', x['title'], re.I) else 2)

        has_more = i < len(items)

        return jsonify({'streams': streams, 'hasMore': has_more})

    except Exception as e:
        return jsonify({'streams': [], 'error': str(e)[:50]})

if __name__ == '__main__':
    print('CineFlix - Movies & Series Streaming')
    app.run(host='0.0.0.0', port=8080, threaded=True, debug=False)
