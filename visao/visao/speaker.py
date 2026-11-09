"""Cumprimento falado: gera a frase com espeak-ng (offline) e toca no alto-falante.

Saídas (greeting.output):
  local  - saída de som da própria TV Box (conector AV de 3,5 mm ou HDMI), via aplay;
  camera - alto-falante da Tapo, pelo go2rtc (precisa da senha da conta Tapo);
  auto   - tenta a câmera e, se falhar, toca na saída local.
O detector só enfileira; a fala roda numa thread separada.
"""
import hashlib
import logging
import os
import queue
import random
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import wave
from datetime import datetime

import numpy as np

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
        self.output = str(gcfg.output).lower()
        # câmera só entra no jogo se houver senha da conta Tapo
        self.camera_ok = self.output in ("camera", "auto") and bool(gcfg.tapo_cloud_password)
        self.local_ok = self.output in ("local", "auto")
        self.enabled = bool(gcfg.enabled and (self.camera_ok or self.local_ok))
        self.cache = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.q = queue.Queue(maxsize=5)
        self.results = queue.Queue()  # (member_id, ok, ts) para o detector registrar
        self.last_ok, self.last_error, self.spoken, self.cam_fails = None, None, 0, 0
        self.last_route = None
        self._piper_lock = threading.Lock()
        self._gen_lock = threading.Lock()
        self._gen_list, self._gen_queued, self._gen_running = [], set(), False
        self._piper_broken, self._piper_fails = False, 0
        if gcfg.enabled and not self.enabled:
            self.last_error = "saída 'camera' sem a senha da conta Tapo (greeting.tapo_cloud_password)"

    def start(self):
        if self.enabled:
            threading.Thread(target=self._run, daemon=True, name="speaker").start()

    def _templates(self, names, people):
        names = list(names)
        people = max(people or 0, len(names))
        if people <= 1 and len(names) == 1:
            return "one", self.cfg.messages_one, {"nome": names[0]}
        if people == 2 and len(names) == 2:
            return "two", self.cfg.messages_two, {"nome1": names[0], "nome2": names[1]}
        return "group", self.cfg.messages_group, {}

    def phrase(self, names, people=None, hour=None, pick=None):
        """Monta o cumprimento: individual, para duas pessoas ou para o grupo."""
        _, options, fmt = self._templates(names, people)
        tpl = options[pick % len(options)] if pick is not None else random.choice(options)
        return tpl.format(saudacao=saudacao(hour), **fmt)

    def candidates(self, names, people=None):
        """Frases possíveis, em ordem de preferência (variações sorteadas; dupla cai para grupo)."""
        kind, options, fmt = self._templates(names, people)
        sau = saudacao()
        out = [t.format(saudacao=sau, **fmt) for t in random.sample(options, len(options))]
        if kind == "two":
            out += [t.format(saudacao=sau) for t in random.sample(self.cfg.messages_group,
                                                                   len(self.cfg.messages_group))]
        return out

    def greet(self, names, member_ids, people=None):
        """Fala uma frase já pronta na voz natural; se nenhuma estiver pronta, usa o espeak agora
        e deixa a voz natural sendo gerada para a próxima vez (nunca atrasa o cumprimento)."""
        options = self.candidates(names, people)
        if self.engine() == "piper":
            ready = next((t for t in options if os.path.exists(self._path(t, "piper"))), None)
            if ready is not None:
                self.say(ready, list(member_ids), "piper")
                return ready
            self.generate_later([options[0]])
            self.say(options[0], list(member_ids), "espeak")
            return options[0] + " (voz reserva; a natural está sendo gerada)"
        self.say(options[0], list(member_ids), "espeak")
        return options[0]

    def say(self, text, member_id=None, engine=None):
        if not self.enabled:
            return
        try:
            self.q.put_nowait((text, member_id, engine))
        except queue.Full:
            log.warning("fila de fala cheia; descartando: %s", text)
            self.results.put((member_id, False, time.time()))

    def prewarm(self, names):
        """Gera na voz natural, em segundo plano, todas as frases dos membros (período atual
        primeiro). Fica salvo em disco: só é refeito se mudar a voz, a frase ou o nome."""
        if not self.enabled or self.engine() != "piper":
            return
        now = datetime.now().hour
        hours = [now] + [h for h in (9, 15, 20) if saudacao(h) != saudacao(now)]
        texts = []
        for h in hours:
            texts += [self.phrase([n], 1, h, i) for n in names for i in range(len(self.cfg.messages_one))]
            texts += [self.phrase([], 3, h, i) for i in range(len(self.cfg.messages_group))]
        self.generate_later(texts)

    def generate_later(self, texts):
        with self._gen_lock:
            todo = [t for t in texts if t not in self._gen_queued
                    and not os.path.exists(self._path(t, "piper"))]
            self._gen_queued.update(todo)
            self._gen_list.extend(todo)
            if todo and not self._gen_running:
                self._gen_running = True
                threading.Thread(target=self._gen_worker, daemon=True, name="tts-piper").start()

    def _gen_worker(self):
        while True:
            with self._gen_lock:
                if not self._gen_list or self.engine() != "piper":
                    self._gen_running = False
                    return
                text = self._gen_list.pop(0)
            try:
                t0 = time.time()
                self.synth(text, "piper")
                log.info("voz natural pronta (%.0f s): %s", time.time() - t0, text)
            except Exception as e:
                self._piper_fails += 1
                log.warning("Piper falhou (%s) em '%s'", e, text)
                if self._piper_fails >= 3:
                    self._piper_broken = True
                    log.error("Piper desligado após 3 falhas; usando a voz do espeak")
            finally:
                with self._gen_lock:
                    self._gen_queued.discard(text)

    def pending(self):
        with self._gen_lock:
            return len(self._gen_list)

    def _path(self, text, engine):
        pad = float(self.cfg.lead_silence_s)
        voice = (f"piper|{self.cfg.piper_model}|{self.cfg.piper_length_scale}" if engine == "piper"
                 else f"espeak|{self.cfg.voice}|{self.cfg.speed}|{self.cfg.volume}")
        key = hashlib.sha1(f"{voice}|{pad}|{text}".encode()).hexdigest()[:16]
        return os.path.join(self.cache, f"{key}.wav")

    def synth(self, text, engine=None):
        """Gera (ou reaproveita) o WAV da frase com o motor pedido."""
        engine = engine or self.engine()
        path = self._path(text, engine)
        if os.path.exists(path):
            return path
        tmp = f"{path}.{threading.get_ident()}.tmp.wav"
        if engine == "piper":
            with self._piper_lock:  # um Piper por vez (pesado para a TV Box)
                self._piper(text, tmp)
        else:
            subprocess.run(["espeak-ng", "-v", self.cfg.voice, "-s", str(self.cfg.speed),
                            "-a", str(self.cfg.volume), "-w", tmp, text],
                           check=True, capture_output=True, timeout=30)
        # silêncio no começo: a câmera leva ~1-2 s para ativar o alto-falante e
        # "come" o início do áudio; sem isso, frases curtas somem inteiras
        pad = float(self.cfg.lead_silence_s)
        with wave.open(tmp, "rb") as src:
            params, frames = src.getparams(), src.readframes(src.getnframes())
        silence = b"\x00" * int(params.framerate * pad) * params.sampwidth * params.nchannels
        with wave.open(tmp + ".pad", "wb") as dst:
            dst.setparams(params)
            dst.writeframes(silence + frames + silence[: len(silence) // 2])
        os.remove(tmp)
        os.replace(tmp + ".pad", path)
        return path

    def engine(self):
        if (str(self.cfg.engine).lower() == "piper" and not self._piper_broken
                and os.path.exists(self.cfg.piper_bin) and os.path.exists(self.cfg.piper_model)):
            return "piper"
        return "espeak"

    def _piper(self, text, out):
        """Voz neural (Piper), offline. Lenta na TV Box (~30 s por frase): roda com prioridade
        mínima para não atrapalhar o reconhecimento, e o resultado fica guardado."""
        env = dict(os.environ, LD_LIBRARY_PATH=os.path.dirname(self.cfg.piper_bin),
                   ESPEAK_DATA_PATH=os.path.join(os.path.dirname(self.cfg.piper_bin), "espeak-ng-data"))
        subprocess.run(["nice", "-n", "19", self.cfg.piper_bin, "--model", self.cfg.piper_model,
                        "--length_scale", str(self.cfg.piper_length_scale),
                        "--sentence_silence", "0.25", "--output_file", out],
                       input=text.encode(), check=True, capture_output=True, timeout=600, env=env)

    def play_camera(self, path):
        src = f"ffmpeg:{path}#audio=pcma/8000#input=file"  # G.711 A-law 8 kHz mono, o que a C200 aceita
        url = (f"{self.cfg.go2rtc_url}/api/streams?dst={urllib.parse.quote(self.cfg.stream)}"
               f"&src={urllib.parse.quote(src, safe='')}")
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()

    def play_local(self, path):
        subprocess.run(["aplay", "-q", "-D", self.cfg.local_device, path],
                       check=True, capture_output=True, timeout=30)

    def louder(self, path):
        """Versão mais alta da frase (greeting.loudness: 1.25 = +25% de volume percebido).
        Os picos da voz já batem no máximo, então um limitador suave segura só os picos em
        vez de estourar o som. Fica guardada ao lado do original."""
        target = float(self.cfg.loudness)
        if abs(target - 1.0) < 0.01:
            return path
        out = f"{path[:-4]}.v{int(round(target * 100))}.wav"
        if os.path.exists(out):
            return out
        with wave.open(path, "rb") as src:
            params, raw = src.getparams(), src.readframes(src.getnframes())
        if params.sampwidth != 2:
            return path
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
        knee = 0.6

        def limit(v):
            a = np.abs(v)
            over = a > knee
            a[over] = knee + (1 - knee) * np.tanh((a[over] - knee) / (1 - knee))
            return np.sign(v) * a * 0.97

        base = float(np.sqrt(np.mean(x * x))) or 1.0
        lo, hi = 1.0, 4.0
        for _ in range(14):  # acha o ganho que dá o volume pedido depois do limitador
            g = (lo + hi) / 2
            if float(np.sqrt(np.mean(limit(x * g) ** 2))) / base < target:
                lo = g
            else:
                hi = g
        y = (limit(x * lo) * 32767).astype(np.int16)
        tmp = f"{out}.{threading.get_ident()}.tmp"
        with wave.open(tmp, "wb") as dst:
            dst.setparams(params)
            dst.writeframes(y.tobytes())
        os.replace(tmp, out)
        return out

    def play(self, path):
        """Toca pela saída configurada. Retorna o nome da saída usada."""
        path = self.louder(path)
        if self.camera_ok:
            try:
                self.play_camera(path)
                self.cam_fails = 0
                return "câmera"
            except Exception as e:
                self.cam_fails += 1
                log.warning("câmera não tocou o áudio (%s: %s)", type(e).__name__, e)
                if self.cam_fails >= 3:
                    # a Tapo bloqueia a conta depois de muitas falhas de login: para de tentar
                    self.camera_ok = False
                    log.error("saída pela câmera desligada após 3 falhas seguidas "
                              "(confira a conta Tapo e reinicie o visao-detector)")
                if not self.local_ok:
                    raise
        if self.local_ok:
            self.play_local(path)
            return "TV Box"
        raise RuntimeError("nenhuma saída de som disponível")

    def _run(self):
        while True:
            text, member_id, engine = self.q.get()
            ok = False
            try:
                self.last_route = self.play(self.synth(text, engine))
                self.last_ok, self.last_error, ok = time.time(), None, True
                self.spoken += 1
                log.info("falou (%s): %s", self.last_route, text)
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                log.warning("não foi possível falar '%s': %s", text, self.last_error)
            if not (self.camera_ok or self.local_ok):
                self.enabled = False
            self.results.put((member_id, ok, time.time()))
            if not self.enabled:
                while not self.q.empty():
                    _, mid, _ = self.q.get_nowait()
                    self.results.put((mid, False, time.time()))
                return
            time.sleep(1)
