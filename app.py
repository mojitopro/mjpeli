#!/usr/bin/env python3
from flask import Flask, request, jsonify, send_file, Response, redirect
import os
import re
import urllib.parse
import requests

app = Flask(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://searchtv.net/',
}

session = requests.Session()
session.headers.update(HEADERS)

M3U_URL_RE = re.compile(r'^(https?://\S+)$')
MOBILE_RE = re.compile(r'Mobi|Android|iPhone|iPad|iPod|webOS|BlackBerry|Opera Mini|IEMobile|Touch|Silk', re.I)

@app.route('/')
def index():
    ua = request.headers.get('User-Agent', '')
    w = request.args.get('w', '')
    if MOBILE_RE.search(ua) or w == 'm':
        return send_file(os.path.join(os.path.dirname(__file__), 'mobile.html'))
    return send_file(os.path.join(os.path.dirname(__file__), 'tv.html'))

@app.route('/player')
def api_player():
    url = request.args.get('url', '')
    if not url:
        return 'Missing URL', 400
    safe_url = url.replace('"', '\\"').replace("'", "\\'")
    return '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>SŌF MOJITO TV</title>
<style>
*{margin:0;padding:0}html,body{width:100%;height:100%;background:#000}
#player{position:relative;width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:#000}
video{width:100%;height:100%;background:#000;object-fit:contain}
#back{position:fixed;top:10px;left:10px;z-index:10;background:rgba(139,0,0,0.8);color:#fff;padding:10px 15px;border-radius:8px;font-size:16px;cursor:pointer;border:none}
#status{color:#fff;position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:16px;pointer-events:none}
</style></head><body>
<div id="player"><div id="status">Cargando...</div><video id="v" playsinline webkit-playsinline controls></video></div>
<button id="back" onclick="history.back()">← Volver</button>
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script><script>
var u="''' + safe_url + '''";
var v=document.getElementById("v"), s=document.getElementById("status");
v.style.display='none';
function ok(){s.style.display='none';v.style.display='block';v.play().catch(function(){})}
if(typeof Hls!=="undefined"&&Hls.isSupported()){
    var h=new Hls({maxBufferLength:30,startLevel:-1});
    h.loadSource(u);h.attachMedia(v);
    h.on(Hls.Events.MANIFEST_PARSED,function(){ok()});
    h.on(Hls.Events.ERROR,function(e,d){
        if(d.fatal){h.destroy();if(d.type===Hls.ErrorTypes.NETWORK_ERROR)h.loadSource(u);
        else{v.src=u;ok()}}
    });
}else if(v.canPlayType('application/vnd.apple.mpegurl')){
    v.src=u;v.addEventListener('loadedmetadata',function(){ok()});
}else{v.src=u;ok()}
</script></body></html>'''

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
            f'https://searchtv.net/search/?query={urllib.parse.quote(q)}',
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
                stream_resp = session.get(
                    f'https://searchtv.net/stream/uuid/{items[i]}/',
                    timeout=30
                )
                if stream_resp.status_code != 200:
                    i += 1
                    continue

                text = stream_resp.text
                if '#EXTM3U' not in text:
                    i += 1
                    continue

                title = data[items[i]].get('title', items[i])
                url = ''

                for line in text.splitlines():
                    if line.startswith('#EXTINF:'):
                        parts = line.split(',', 1)
                        if len(parts) > 1:
                            raw = parts[1].strip().split('==>')[0].strip()
                            clean = re.sub(r'\s*\(\d+\)\s*$', '', raw).strip()
                            if clean:
                                title = clean
                    elif M3U_URL_RE.match(line.strip()):
                        url = line.strip()
                        break

                if url:
                    streams.append({'title': title, 'url': url})
                    downloaded += 1
            except requests.exceptions.RequestException:
                pass
            i += 1

        streams.sort(key=lambda x: 0 if re.search(r'1080|4k|uhd', x['title'], re.I) else 1 if re.search(r'720|hd', x['title'], re.I) else 2)

        has_more = i < len(items)

        return jsonify({'streams': streams, 'hasMore': has_more})

    except Exception as e:
        return jsonify({'streams': [], 'error': str(e)[:50]})

if __name__ == '__main__':
    print('SŌF TV - Fast HD Priority')
    app.run(host='0.0.0.0', port=8080, threaded=True, debug=False)
