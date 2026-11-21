"""SL2 as a desktop program: its own window instead of a browser tab.

The interface is the same page the browser shows, drawn by the system's web view (Microsoft Edge WebView2 on
Windows - part of Windows 10 and 11 - WebKit on macOS, GTK/Qt on Linux) through pywebview. The SL2 server runs inside
the program and stops when the window closes. Exports open a real "Save as" dialog. If no web view is available, SL2
falls back to your browser.

    SL2.exe                    the window
    SL2.exe --selftest FILE    open the window, check the page loaded, write the result to FILE, close (used by CI)
"""
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.request

from . import __version__


def _state_file():
    base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), '.config')
    d = os.path.join(base, 'SL2')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'window.json')


def _load_state():
    try:
        with open(_state_file(), encoding='utf-8') as f:
            s = json.load(f)
        return {k: int(s[k]) for k in ('width', 'height', 'x', 'y') if k in s}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def _save_state(w):
    try:
        st = dict(width=w.width, height=w.height, x=w.x, y=w.y)
        if st['width'] >= 800 and st['height'] >= 560:
            with open(_state_file(), 'w', encoding='utf-8') as f:
                json.dump(st, f)
    except Exception:            # (best effort: never stop the program from closing)
        pass


class Api:
    """Functions the page can call as window.pywebview.api.<name>(...)."""

    def __init__(self, url, token):
        self.url = url.rstrip('/')
        self.token = token
        self.window = None

    def save(self, path):
        """Download one of SL2's exports (path like /api/song/<id>/wav) to a place the user picks."""
        import webview
        if not re.fullmatch(r'/api/song/[A-Za-z0-9_.-]+/(wav|wav24|mp3|stems|midi|json)', path or ''):
            return dict(ok=False, error='not an export')
        req = urllib.request.Request(self.url + path, headers={'X-SL2-Token': self.token})
        with urllib.request.urlopen(req) as r:
            cd = r.headers.get('Content-Disposition', '')
            m = re.search(r'filename="?([^";]+)"?', cd)
            name = m.group(1) if m else 'sl2-export'
            dest = self.window.create_file_dialog(webview.SAVE_DIALOG, directory=os.path.expanduser('~'), save_filename=name)
            if not dest:
                return dict(ok=False, cancelled=True)
            dest = dest if isinstance(dest, str) else dest[0]
            tmp = dest + '.part'
            with open(tmp, 'wb') as f:
                shutil.copyfileobj(r, f, 1 << 20)
            os.replace(tmp, dest)
        return dict(ok=True, path=dest)

    def reveal(self, path):
        """Show a saved file in Explorer / Finder."""
        if not path or not os.path.exists(path):
            return False
        if sys.platform == 'win32':
            import subprocess
            subprocess.Popen(['explorer', '/select,', os.path.normpath(path)])
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.Popen(['open', '-R', path])
        return True

    def songs_folder(self):
        from . import store
        if sys.platform == 'win32':
            os.startfile(store.HOME)        # noqa: S606 - our own folder
        return store.HOME


def _message(text, title='SL2'):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    else:
        print(text)


def run(selftest=None):
    from . import render, server
    srv, url = server.start()
    threading.Thread(target=srv.serve_forever, daemon=True, name='sl2-server').start()
    try:
        import webview
    except Exception:                       # no pywebview: the browser it is
        import webbrowser
        webbrowser.open(url)
        _message(f'SL2 is running in your browser at {url}\n\nClick OK to quit SL2.')
        srv.shutdown()
        return 0
    api = Api(url, server.TOKEN)
    st = _load_state()
    try:
        webview.settings['ALLOW_DOWNLOADS'] = True
    except Exception:
        pass
    w = webview.create_window(f'SL2 {__version__}', url, js_api=api, width=st.get('width', 1440), height=st.get('height', 940),
                              x=st.get('x'), y=st.get('y'), min_size=(1080, 700), background_color='#0B0B12', text_select=True)
    api.window = w
    w.events.closing += lambda: _save_state(w)
    result = {}

    def watchdog():
        """--selftest never hangs: whatever happens, after 90 s the result so far is written and the program exits."""
        time.sleep(90)
        result.setdefault('timeout', True)
        try:
            with open(selftest, 'w', encoding='utf-8') as f:
                json.dump(result, f)
        finally:
            os._exit(3)

    def check():
        """--selftest: wait for the page, count the genres it lists, then close."""
        threading.Thread(target=watchdog, daemon=True).start()
        try:
            w.events.loaded.wait(60)
        except Exception:
            pass
        t0 = time.time()
        n = 0
        has_api = False
        while time.time() - t0 < 60:
            time.sleep(1.0)
            try:
                n = int(w.evaluate_js("document.querySelectorAll('#genres .g').length") or 0)
                has_api = bool(w.evaluate_js("!!(window.pywebview && window.pywebview.api && window.pywebview.api.save)"))
            except Exception as e:      # page not ready yet
                result['last_error'] = repr(e)
                continue
            if n > 0 and has_api:
                break
        result.update(genres=n, api=has_api if n else False, seconds=round(time.time() - t0, 1))
        w.destroy()
    storage = os.path.join(os.path.dirname(_state_file()), 'webview')
    try:
        webview.start(check if selftest else None, private_mode=False, storage_path=storage)
    except Exception as e:                  # no web view runtime: fall back to the browser
        if selftest:
            result['error'] = repr(e)
        else:
            import webbrowser
            webbrowser.open(url)
            _message(f'SL2 could not open its window ({e}).\nIt is running in your browser at {url}\n\nClick OK to quit SL2.')
    finally:
        srv.shutdown()
        render._reset_pool()
    if selftest:
        with open(selftest, 'w', encoding='utf-8') as f:
            json.dump(result, f)
        return 0 if result.get('genres', 0) > 0 and result.get('api') else 1
    return 0
