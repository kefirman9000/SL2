"""SL2's local web app: a small HTTP server (standard library) serving the skin and a JSON API.

Bound to 127.0.0.1 only. Every API call must carry the session token that is written into the page, and the Host
header must be the local address, so other web pages can't drive it.
"""
import json
import mimetypes
import os
import platform
import re
import secrets
import shutil
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__, analyze, genres, prompt, store
from .synth import LABELS

UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui')
# Explicit types: on Windows, mimetypes reads the registry, where .js is sometimes registered as text/plain
# (and browsers then refuse to run the page's script).
TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
         '.ttf': 'font/ttf', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json',
         '.txt': 'text/plain; charset=utf-8', '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.mid': 'audio/midi', '.ico': 'image/x-icon'}
TOKEN = secrets.token_urlsafe(24)
MAX_UPLOAD = 300 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = 'SL2'

    def log_message(self, fmt, *args):
        pass

    # ---- helpers
    def _host_ok(self):
        host = (self.headers.get('Host') or '').split(':')[0]
        return host in ('127.0.0.1', 'localhost')

    def _send(self, code, body, ctype='application/json', extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg):
        self._send(code, dict(error=msg))

    def _authed(self):
        return secrets.compare_digest(self.headers.get('X-SL2-Token', ''), TOKEN) or \
            secrets.compare_digest(parse_qs(urlparse(self.path).query).get('t', [''])[0], TOKEN)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_UPLOAD:
            raise ValueError('too large')
        return self.rfile.read(n) if n else b''

    def _file(self, path, ctype=None, download=None):
        size = os.path.getsize(path)
        ctype = ctype or TYPES.get(os.path.splitext(path)[1].lower()) or mimetypes.guess_type(path)[0] or 'application/octet-stream'
        rng = self.headers.get('Range')
        start, end = 0, size - 1
        code = 200
        if rng:
            m = re.match(r'bytes=(\d*)-(\d*)', rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = size - int(m.group(2))
                end = min(end, size - 1)
                code = 206
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        if code == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        if download:
            self.send_header('Content-Disposition', f'attachment; filename="{download}"')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        with open(path, 'rb') as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    # ---- GET
    def do_GET(self):
        if not self._host_ok():
            return self._err(403, 'forbidden')
        u = urlparse(self.path)
        p = u.path
        if p in ('/', '/index.html'):
            with open(os.path.join(UI, 'index.html'), 'rb') as f:
                page = f.read().replace(b'__SL2_TOKEN__', TOKEN.encode()).replace(b'__SL2_VERSION__', __version__.encode())
            return self._send(200, page, 'text/html; charset=utf-8', {'X-Frame-Options': 'DENY'})
        if p.startswith('/ui/'):
            name = os.path.normpath(p[4:]).replace('\\', '/')
            if name.startswith('..') or name.startswith('/'):
                return self._err(404, 'not found')
            fp = os.path.join(UI, name)
            if not os.path.isfile(fp):
                return self._err(404, 'not found')
            return self._file(fp)
        if not self._authed():
            return self._err(403, 'missing token')
        try:
            return self._get_api(p, parse_qs(u.query))
        except FileNotFoundError:
            return self._err(404, 'not found')
        except Exception as e:
            return self._err(500, f'{type(e).__name__}: {e}')

    def _get_api(self, p, q):
        if p == '/api/genres':
            from .compose import CHOICES
            from .fx import menu as fx_menu
            return self._send(200, dict(genres=genres.summary(), sounds=LABELS, choices=CHOICES, effects=fx_menu(),
                                        caps=dict(mp3=bool(shutil.which('ffmpeg')))))
        if p == '/api/diag':
            return self._send(200, diagnostics())
        if p == '/api/library':
            return self._send(200, store.library())
        if p.startswith('/api/job/'):
            j = store.JOBS.get(p.split('/')[-1])
            return self._send(200, j) if j else self._err(404, 'no such job')
        m = re.fullmatch(r'/api/song/([^/]+)(?:/([\w.]+))?', p)
        if m:
            sid, what = m.group(1), m.group(2)
            if what is None:
                return self._send(200, store.song_view(sid))
            if what == 'notes':
                return self._send(200, store.track_notes(sid, q.get('track', [''])[0]))
            if what == 'history':
                return self._send(200, store.history(sid))
            if what == 'mix.wav':
                return self._file(os.path.join(store._dir(sid), 'mix.wav'), 'audio/wav')
            if what == 'wav':
                meta = store.load_meta(sid)
                return self._file(os.path.join(store._dir(sid), 'mix.wav'), 'audio/wav', download=_fname(meta, 'wav'))
            if what == 'mp3':
                meta = store.load_meta(sid)
                return self._file(store.export_mp3(sid), 'audio/mpeg', download=_fname(meta, 'mp3'))
            if what == 'midi':
                meta = store.load_meta(sid)
                return self._file(store.export_midi(sid), 'audio/midi', download=_fname(meta, 'mid'))
            if what == 'json':
                meta = store.load_meta(sid)
                return self._file(os.path.join(store._dir(sid), 'song.json'), 'application/json', download=_fname(meta, 'sl2.json'))
            if what == 'stems':
                meta = store.load_meta(sid)
                data = store.export_stems_zip(sid)
                return self._send(200, data, 'application/zip', {'Content-Disposition': f'attachment; filename="{_fname(meta, "stems.zip")}"'})
        return self._err(404, 'not found')

    # ---- POST
    def do_POST(self):
        if not self._host_ok() or not self._authed():
            return self._err(403, 'forbidden')
        p = urlparse(self.path).path
        try:
            if p == '/api/analyze':
                raw = self._body()
                name = os.path.basename(self.headers.get('X-Filename') or 'ref.wav')
                ext = os.path.splitext(name)[1].lower() or '.wav'
                fd, tmp = tempfile.mkstemp(suffix=ext)
                with os.fdopen(fd, 'wb') as f:
                    f.write(raw)

                def job(progress=None):
                    try:
                        if progress:
                            progress(0.2, 'measuring tempo, key, drums, tone')
                        a = analyze.analyze(tmp)
                        ranked = analyze.match_genres(a, genres.all_genres())
                        return dict(analysis=a, matches=[dict(score=s, genre=gid, why=why, bpm=b) for s, gid, why, b in ranked[:4]])
                    finally:
                        os.remove(tmp)
                return self._send(200, dict(job=store.start_job('analyze', job)))
            if p == '/api/import':
                text = self._body().decode('utf-8-sig')
                return self._send(200, dict(job=store.start_job('open', store.import_song, text)))
            body = json.loads(self._body() or b'{}')
            if p == '/api/prompt':
                s, said = prompt.parse(body.get('text', ''))
                return self._send(200, dict(settings=s, understood=said))
            if p == '/api/generate':
                return self._send(200, dict(job=store.start_job('generate', store.generate, body)))
            m = re.fullmatch(r'/api/song/([^/]+)/(\w+)', p)
            if m:
                sid, what = m.groups()
                if what == 'reroll':
                    return self._send(200, dict(job=store.start_job('reroll', store.reroll, sid, body.get('what', 'all'))))
                if what == 'lock':
                    return self._send(200, store.set_lock(sid, body['track'], body.get('on', True)))
                if what == 'instrument':
                    return self._send(200, dict(job=store.start_job('sound', store.set_instrument, sid, body['track'], body['instrument'])))
                if what == 'notes':
                    return self._send(200, dict(job=store.start_job('edit', store.edit_notes, sid, body['track'], body['notes'])))
                if what == 'mix':
                    return self._send(200, dict(job=store.start_job('mix', store.remix, sid, body.get('mix', {}))))
                if what == 'section':
                    if body.get('action') == 'take':
                        return self._send(200, dict(job=store.start_job('section', store.reroll_section, sid, body['index'])))
                    return self._send(200, dict(job=store.start_job('section', store.edit_section, sid, body['index'], body['action'],
                                                                    body.get('track'), body.get('bars', 4))))
                if what == 'fx':
                    return self._send(200, dict(job=store.start_job('effects', store.set_fx, sid, body['track'], body.get('fx', []))))
                if what == 'variation':
                    return self._send(200, dict(job=store.start_job('variation', store.variation, sid, body.get('keep', []))))
                if what == 'star':
                    return self._send(200, store.star(sid, body.get('on', True)))
                if what == 'delete':
                    return self._send(200, store.delete(sid))
            return self._err(404, 'not found')
        except Exception as e:
            return self._err(400, f'{type(e).__name__}: {e}')


def diagnostics():
    import numpy
    import scipy
    return dict(sl2=__version__, python=sys.version.split()[0], platform=platform.platform(), machine=platform.machine(),
                numpy=numpy.__version__, scipy=scipy.__version__, cpus=os.cpu_count(), frozen=bool(getattr(sys, 'frozen', False)),
                ffmpeg=bool(shutil.which('ffmpeg')), songs=store.HOME, workers=__import__('sl2.render', fromlist=['x']).default_workers())


def _fname(meta, ext):
    t = re.sub(r'[^A-Za-z0-9]+', '-', meta.get('title', 'song')).strip('-') or 'song'
    return f"{t}_{meta.get('genre', '')}_{str(meta.get('key', '')).replace(' ', '-')}_{int(meta.get('bpm', 0))}bpm.{ext}"


def run(port=8770, open_browser=True):
    os.makedirs(store.HOME, exist_ok=True)
    srv = None
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(('127.0.0.1', p), Handler)
            break
        except OSError:
            continue
    if srv is None:
        raise SystemExit('no free port')
    url = f'http://127.0.0.1:{srv.server_address[1]}/'
    print(f'SL2 is running at {url}  (Ctrl+C to quit)')
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
