"""Carrega a configuração (TOML) e completa com valores padrão."""
import os
import tomllib
from urllib.parse import quote

DEFAULTS = {
    "camera": {
        "host": "",
        "user": "",
        "password": "",
        "rtsp_port": 554,
        "onvif_port": 2020,
        "main_stream": "stream1",  # 1080p: usado só para gravar clipes
        "sub_stream": "stream2",   # 720p: usado para a análise
    },
    "detection": {
        "det_width": 640,          # largura usada pelo detector (o quadro é reduzido)
        "det_score_min": 0.6,      # confiança mínima para considerar um rosto
        "rec_det_score": 0.7,      # confiança mínima para tentar reconhecer
        "min_face_px": 36,         # largura mínima do rosto (px no quadro 720p)
        "yaw_max": 0.35,           # quão de lado o rosto pode estar (0 = de frente)
        "sharp_min": 25.0,         # nitidez mínima do recorte
        "accept": 0.36,            # similaridade mínima para identificar um membro
        "margin": 0.04,            # vantagem mínima sobre o 2º membro mais parecido
        "unknown": 0.26,           # abaixo disso a leitura conta como "desconhecido"
        "same_person": 0.36,       # para agrupar leituras do mesmo desconhecido
        "unknown_attempts": 3,     # leituras ruins parecidas antes de alertar
        "unknown_cooldown_s": 600, # não repetir alerta da mesma pessoa nesse intervalo
        "max_attempts": 8,         # tentativas por rosto acompanhado
        "reverify_s": 45,          # reconfirma a identidade de um rosto acompanhado
        "max_rec_per_cycle": 2,    # reconhecimentos por ciclo (cada um custa ~1 s)
        "track_ttl_s": 6.0,
        "heartbeat_s": 20,         # varredura periódica mesmo sem movimento
        "idle_track_interval_s": 3.0,
        "stable_interval_s": 1.5,  # há movimento, mas todos os rostos visíveis já identificados
        "temp_hot": 78.0,          # °C: acima disso a análise fica mais espaçada
        "temp_critical": 85.0,     # °C: acima disso, bem mais espaçada (protege a TV Box)
        "frame_every": 4,          # usa 1 a cada N quadros do stream (15 fps -> ~4 fps)
        "threads": 4,
        "auto_enrich": True,       # aprende novas amostras quando a certeza é alta
        "auto_enrich_score": 0.48,
        "auto_enrich_max": 30,     # ao encher, a mais antiga é trocada pela nova
        "strong_accept": 0.50,     # acima disso basta uma leitura; abaixo, precisa de duas
    },
    "presence": {
        "session_gap_min": 30,     # sem ver a pessoa por esse tempo = saiu
    },
    "storage": {
        "data_dir": "/opt/visao/data",
        "runtime_dir": "/dev/shm/visao",
        "models_dir": "/opt/visao/models",
        "retention_days": 7,
        "min_free_mb": 800,
        "record_clips": True,
        "clip_before_s": 10,
        "clip_after_s": 20,
    },
    "web": {
        "host": "0.0.0.0",
        "port": 8080,
    },
    "greeting": {
        "enabled": True,
        "message": "{saudacao}, {nome}!",   # {saudacao} = Bom dia / Boa tarde / Boa noite
        "once_per": "dia",                   # "dia" = só na primeira vez que vê a pessoa no dia
        "voice": "mb-br3",                   # espeak-ng: mb-br1, mb-br3, mb-br4 ou pt-br
        "speed": 145,
        "volume": 180,
        "output": "auto",                    # local (TV Box) | camera (Tapo) | auto (câmera, senão local)
        "local_device": "plughw:CARD=analog,DEV=0",  # conector AV; HDMI: plughw:CARD=HDMI,DEV=0
        "go2rtc_url": "http://127.0.0.1:1984",
        "stream": "camera",
        # O alto-falante da Tapo só aceita áudio pelo protocolo próprio da TP-Link, que pede a
        # senha da CONTA TAPO (a do app/nuvem), não a "Conta da câmera" usada no RTSP.
        "tapo_cloud_password": "",
    },
    "security": {
        "enabled": False,          # modo segurança: movimento no horário abaixo vira alerta
        "start": "23:00",
        "end": "06:00",
        "cooldown_min": 5,         # no máximo um alerta a cada N minutos
    },
    "telegram": {
        "token": "",
        "chat_id": "",
        "notify_unknown": True,
        "notify_entries": False,
    },
}


class Section(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None


def load(path=None):
    path = path or os.environ.get("VISAO_CONFIG", "/opt/visao/config.toml")
    user = {}
    if os.path.exists(path):
        with open(path, "rb") as f:
            user = tomllib.load(f)
    cfg = Section()
    for sec, vals in DEFAULTS.items():
        merged = Section(vals)
        merged.update(user.get(sec, {}))
        cfg[sec] = merged
    return cfg


def rtsp_url(cam, which="sub"):
    stream = cam.sub_stream if which == "sub" else cam.main_stream
    cred = f"{quote(cam.user, safe='')}:{quote(cam.password, safe='')}@" if cam.user else ""
    return f"rtsp://{cred}{cam.host}:{cam.rtsp_port}/{stream}"
