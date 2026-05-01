#!/usr/bin/env python3
from flask import Flask, request, jsonify, send_file
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
