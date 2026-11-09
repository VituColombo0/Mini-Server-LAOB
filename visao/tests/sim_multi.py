"""Simulação dos cenários com várias pessoas (sem câmera): python -m tests.sim_multi"""
import logging, time
import numpy as np
from visao import db
from visao.config import load
from visao.detector import Detector
from visao.faces import Gallery, Face
from visao.presence import Presence
from visao.tracker import Tracker

logging.basicConfig(level=logging.INFO, format="%(message)s")
rng = np.random.default_rng(1)
base = {m: v / np.linalg.norm(v) for m, v in {1: rng.normal(size=128), 2: rng.normal(size=128),
                                              3: rng.normal(size=128), 9: rng.normal(size=128)}.items()}

def emb_of(m, sim):
    """Embedding com similaridade ~sim com o membro m (9 = visitante)."""
    noise = rng.normal(size=128); noise -= (noise @ base[m]) * base[m]; noise /= np.linalg.norm(noise)
    v = sim * base[m] + np.sqrt(1 - sim ** 2) * noise
    return (v / np.linalg.norm(v)).astype(np.float32)

class FakeSpeaker:
    enabled = True
    def __init__(self): self.said = []
    def greet(self, names, ids, people):
        self.said.append((sorted(names), people)); return f"{names} p={people}"

class FakeEngine:
    def __init__(self): self.next = {}
    def assess(self, frame, f, dc):
        return None, {"q": 0.8, "w": f.w, "yaw": 0.0, "side": False}, True
    def embed(self, aligned): raise RuntimeError

def make():
    cfg = load("/nonexistent.toml")
    d = Detector.__new__(Detector)
    d.cfg = cfg
    d.con = db.connect(":memory:")
    for i, n in ((1, "Victor"), (2, "Gazziro"), (3, "Mario")):
        d.con.execute("INSERT INTO members(id,name,created_at) VALUES(?,?,0)", (i, n))
    g = Gallery(); g.names = {1: "Victor", 2: "Gazziro", 3: "Mario"}
    g.matrix = np.stack([base[1], base[2], base[3]]).astype(np.float32); g.labels = np.array([1, 2, 3])
    d.gallery = g
    d.tracker = Tracker(ttl=6.0)
    d.presence = Presence(d.con, 1800)
    d.speaker = FakeSpeaker()
    d.greet_batch, d.greeted, d.pending_accepts = None, {}, {}
    from collections import deque
    d.recent_confirmed, d.low, d.recent_unknown, d.pending_unknown = deque(maxlen=60), deque(maxlen=80), deque(maxlen=50), []
    d.recent_uncertain = deque(maxlen=50)
    d.on_entry = lambda *a: None
    d.maybe_auto_enrich = lambda *a: None
    d.learn_hard = lambda *a: None
    d.on_track_end = lambda t: None
    d.capture = None
    d.last_faces = 0
    return d

def face(x, w=60):
    r = np.zeros(15, np.float32); r[:4] = (x, 200, w, w); r[14] = 0.9
    return Face(r)

def step(d, ts, people):
    """people: lista de (x, membro, similaridade). Roda um ciclo."""
    faces = [face(x) for x, _, _ in people]
    matched, expired = d.tracker.update(faces, ts)
    by_x = {round(f.center[0]): (m, s) for f, (x, m, s) in zip(faces, people)}
    for t, f in matched:
        m, s = by_x[round(f.center[0])]
        if t.member_id is None or t.recheck or ts - t.last_rec_ts > 45:
            d.recognize(t, emb_of(m, s), None, {"q": 0.8, "side": False}, None, ts)
    d.flush_greeting(ts)

def names(d):
    return {t.id: d.gallery.names.get(t.member_id) for t in d.tracker.tracks.values()}

ok = True
def check(label, cond):
    global ok; ok &= bool(cond); print(("OK   " if cond else "FALHA"), label)

# 1) uma pessoa sozinha: cumprimento logo depois de confirmar (2 leituras)
d = make(); t0 = 1000.0
for i in range(4): step(d, t0 + i, [(100, 1, 0.40)])
check("sozinho: Victor cumprimentado pelo nome em <= 2 ciclos", d.speaker.said == [(["Victor"], 1)])

# 2) dois membros juntos: frase com os dois nomes
d = make()
for i in range(5): step(d, t0 + i, [(100, 1, 0.42), (400, 2, 0.42)])
check("dois membros: cumprimento único com os dois nomes", d.speaker.said == [(["Gazziro", "Victor"], 2)])

# 3) membro + visitante: espera e cumprimenta o grupo
d = make()
for i in range(8): step(d, t0 + i, [(100, 1, 0.45), (400, 9, 0.9)])
check("membro + visitante: cumprimento para o grupo", d.speaker.said and d.speaker.said[0][1] == 2)

# 4) Victor já cumprimentado hoje, Mario chega: Mario pelo nome (não "pessoal")
d = make()
for i in range(3): step(d, t0 + i, [(100, 1, 0.55)])
d.greeted[1] = time.strftime("%Y-%m-%d", time.localtime(t0)); d.speaker.said.clear()
for i in range(3, 8): step(d, t0 + i, [(100, 1, 0.55), (400, 3, 0.45)])
check("já cumprimentado + novo membro: só o novo, pelo nome", d.speaker.said == [(["Mario"], 1)])

# 5) troca de pessoa no mesmo lugar: Victor sai, Gazziro senta ali 3 s depois
d = make()
for i in range(3): step(d, t0 + i, [(100, 1, 0.55)])
step(d, t0 + 6, [(100, 2, 0.55)])
check("troca de pessoa no mesmo lugar: nome atualizado", list(names(d).values()) == ["Gazziro"])

# 6) o mesmo membro em dois rostos: fica só no de maior certeza
d = make()
for i in range(3): step(d, t0 + i, [(100, 1, 0.38), (400, 1, 0.60)])
check("mesmo nome em dois rostos: só um fica com o nome",
      sorted(v or "-" for v in names(d).values()) == ["-", "Victor"])

# 7) leitura fraca isolada de um membro não identifica
d = make()
step(d, t0, [(100, 2, 0.34)])
check("uma leitura fraca não basta", list(names(d).values()) == [None])
# 8) visitante que já apareceu antes é reconhecido como "já visto"
d = make()
v_old = emb_of(9, 0.85)
d.con.execute("INSERT INTO events(ts, kind, embedding) VALUES(?, 'unknown', ?)", (t0 - 86400, db.emb_to_blob(v_old)))
seen, first, today = d.visitor_history(emb_of(9, 0.85), t0)
check("visitante de ontem: 'já visto 1 vez', sem marcar aviso de hoje", seen == 1 and not today)
seen, _, _ = d.visitor_history(emb_of(2, 0.9), t0)
check("outra pessoa não é confundida com o visitante", seen == 0)
# 9) membro com a base completa: não captura mais o rosto dele; com poucas amostras, captura
d = make(); added = []
d.add_sample = lambda mid, *a: added.append(mid)
d.last_auto = {}
d.gallery.matrix = np.stack([emb_of(1, 0.9) for _ in range(25)] + [base[2]]).astype(np.float32)
d.gallery.labels = np.array([1] * 25 + [2])
Detector.maybe_auto_enrich(d, 1, emb_of(1, 0.6), None, {"q": 0.9}, 0.6, t0)
Detector.maybe_auto_enrich(d, 2, emb_of(2, 0.6), None, {"q": 0.9}, 0.6, t0)
check("base completa (25): Victor não é mais capturado; Gazziro (1 amostra) é", added == [2])
# 10) na sala desde antes da meia-noite (sessão aberta há 2 h): não cumprimenta no "novo dia"
d = make()
d.presence.seen(1, t0 - 7200, 0.6)
for k in range(12): d.presence.touch(1, t0 - 7200 + 600 * (k + 1))  # visto o tempo todo
for i in range(3): step(d, t0 + i, [(100, 1, 0.55)])
check("já estava na sala há 2 h: não cumprimenta", d.speaker.said == [])

# 11) frases de dupla e de prewarm fazem sentido (com a classe real do Speaker)
from visao.speaker import Speaker
import tempfile
sp = Speaker(load("/nonexistent.toml").greeting, tempfile.mkdtemp())
f1 = sp.phrase(["Victor", "Gazziro"], 2, 15, 0); f2 = sp.phrase(["Gazziro", "Victor"], 2, 15, 0)
check(f"dupla com ordem fixa dos nomes: '{f1}'", f1 == f2 == "Boa tarde, Gazziro e Victor!")
check("sozinho de manhã: " + sp.phrase(["Mario"], 1, 9, 0), sp.phrase(["Mario"], 1, 9, 0) == "Bom dia, Mario! Que bom te ver.")
check("3 pessoas à noite: " + sp.phrase(["Mario"], 3, 20, 0), sp.phrase(["Mario"], 3, 20, 0) == "Boa noite, pessoal! Que bom ver vocês.")
print("TUDO OK" if ok else "HÁ FALHAS")
