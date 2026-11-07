"""Cumprimento falado: gera a frase com espeak-ng (offline) e toca no alto-falante da câmera.

O áudio chega à Tapo pelo go2rtc (serviço visao-go2rtc), que fala o protocolo de áudio de
duas vias da câmera. O detector só enfileira; a fala roda numa thread separada.
"""
import hashlib
import logging
import os
import queue
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime

log = logging.getLogger("visao.speaker")


def saudacao(hour=None):
    h = datetime.now().hour if hour is None else hour
    if 5 <= h < 12:
        return "Bom dia"
    if 12 <= h < 18:
        return "Boa tarde"
    return "Boa noite"


class Speaker:
    def __init__(self, gcfg, cache_dir):
        self.cfg = gcfg
        # sem a senha da conta Tapo a câmera recusa o áudio: nem tenta (evita erro a cada pessoa)
        self.enabled = bool(gcfg.enabled and gcfg.tapo_cloud_password)
        self.cache = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.q = queue.Queue(maxsize=5)
        self.results = queue.Queue()  # (member_id, ok, ts) para o detector registrar
        self.last_ok, self.last_error, self.spoken, self.fails = None, None, 0, 0
        if gcfg.enabled and not self.enabled:
            self.last_error = "falta a senha da conta Tapo (greeting.tapo_cloud_password)"

    def start(self):
        if self.enabled:
            threading.Thread(target=self._run, daemon=True, name="speaker").start()

    def greet(self, name, member_id=None):
        text = self.cfg.message.format(saudacao=saudacao(), nome=name)
        self.say(text, member_id)
        return text

    def say(self, text, member_id=None):
        if not self.enabled:
            return
        try:
            self.q.put_nowait((text, member_id))
        except queue.Full:
            log.warning("fila de fala cheia; descartando: %s", text)
            self.results.put((member_id, False, time.time()))

    def synth(self, text):
        """Gera (ou reaproveita) o WAV da frase."""
        key = hashlib.sha1(f"{self.cfg.voice}|{self.cfg.speed}|{text}".encode()).hexdigest()[:16]
        path = os.path.join(self.cache, f"{key}.wav")
        if not os.path.exists(path):
            tmp = path + ".tmp.wav"
            subprocess.run(["espeak-ng", "-v", self.cfg.voice, "-s", str(self.cfg.speed),
                            "-a", str(self.cfg.volume), "-w", tmp, text],
                           check=True, capture_output=True, timeout=30)
            os.replace(tmp, path)
        return path

    def play(self, path):
        src = f"ffmpeg:{path}#audio=pcma#input=file"
        url = (f"{self.cfg.go2rtc_url}/api/streams?dst={urllib.parse.quote(self.cfg.stream)}"
               f"&src={urllib.parse.quote(src, safe='')}")
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()

    def _run(self):
        while True:
            text, member_id = self.q.get()
            ok = False
            try:
                self.play(self.synth(text))
                self.last_ok, self.last_error, ok = time.time(), None, True
                self.spoken += 1
                log.info("falou: %s", text)
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                log.warning("não foi possível falar '%s': %s", text, self.last_error)
            self.fails = 0 if ok else self.fails + 1
            if self.fails >= 3:
                # a Tapo bloqueia a conta depois de muitas falhas de login: para de tentar
                self.enabled = False
                self.last_error = ("desligado após 3 falhas seguidas (confira a senha da conta Tapo "
                                   "e reinicie o visao-detector)")
                log.error(self.last_error)
            self.results.put((member_id, ok, time.time()))
            if not self.enabled:
                while not self.q.empty():
                    _, mid = self.q.get_nowait()
                    self.results.put((mid, False, time.time()))
                return
            time.sleep(1)
