"""Detecção (YuNet), alinhamento, qualidade e reconhecimento (SFace) de rostos."""
import os
from dataclasses import dataclass

import cv2
import numpy as np

from . import db

DET_MODEL = "face_detection_yunet_2023mar.onnx"
REC_MODEL = "face_recognition_sface_2021dec.onnx"


@dataclass
class Face:
    row: np.ndarray  # 15 valores do YuNet, já no referencial do quadro original

    @property
    def box(self):
        x, y, w, h = self.row[:4]
        return int(x), int(y), int(w), int(h)

    @property
    def w(self):
        return float(self.row[2])

    @property
    def score(self):
        return float(self.row[14])

    @property
    def center(self):
        x, y, w, h = self.row[:4]
        return float(x + w / 2), float(y + h / 2)

    def yaw(self):
        """Aproximação de quão virado o rosto está (0 = de frente)."""
        lm = self.row[4:14].reshape(5, 2)
        eye_mid = (lm[0] + lm[1]) / 2
        eye_dist = float(np.linalg.norm(lm[0] - lm[1])) + 1e-6
        return float((lm[2][0] - eye_mid[0]) / eye_dist)


def sharpness(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


class FaceEngine:
    def __init__(self, models_dir, det_width=640, det_score=0.6, threads=4):
        cv2.setNumThreads(int(threads))
        self.det = cv2.FaceDetectorYN.create(
            os.path.join(models_dir, DET_MODEL), "", (320, 320), float(det_score), 0.3, 50)
        self.rec = cv2.FaceRecognizerSF.create(os.path.join(models_dir, REC_MODEL), "")
        self.det_width = int(det_width)
        self._size = None

    def detect(self, frame, max_width=None):
        max_width = max_width or self.det_width
        h, w = frame.shape[:2]
        s = min(1.0, max_width / w)
        img = frame
        if s < 1.0:
            img = cv2.resize(frame, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_AREA)
        size = (img.shape[1], img.shape[0])
        if size != self._size:
            self.det.setInputSize(size)
            self._size = size
        _, faces = self.det.detect(img)
        if faces is None:
            return []
        faces = faces.astype(np.float32).copy()
        faces[:, :14] /= s
        return [Face(r) for r in faces]

    def align(self, frame, face):
        return self.rec.alignCrop(frame, face.row)

    def embed(self, aligned):
        f = self.rec.feature(aligned).reshape(-1).astype(np.float32)
        n = float(np.linalg.norm(f))
        return f / n if n > 0 else f

    def assess(self, frame, face, dc):
        """Alinha o rosto e mede a qualidade. Retorna (recorte, info, apto_para_reconhecer)."""
        aligned = self.align(frame, face)
        sh = sharpness(aligned)
        yaw = face.yaw()
        ok = (face.w >= dc.min_face_px and abs(yaw) <= dc.yaw_max
              and sh >= dc.sharp_min and face.score >= dc.rec_det_score)
        q = (min(face.w / 80.0, 1.5) * max(0.0, 1 - abs(yaw))
             * min(sh / 150.0, 1.5) * face.score)
        return aligned, {"w": face.w, "yaw": yaw, "sharp": sh, "score": face.score, "q": q}, ok

    def enroll_image(self, img):
        """Para fotos de cadastro: escolhe o maior rosto. Levanta ValueError se não servir."""
        h, w = img.shape[:2]
        s = min(1.0, 1280 / max(h, w))
        if s < 1.0:
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        faces = self.detect(img, max_width=img.shape[1])
        if not faces:
            raise ValueError("nenhum rosto encontrado na foto")
        faces.sort(key=lambda f: -f.w)
        if len(faces) > 1 and faces[1].w > 0.7 * faces[0].w:
            raise ValueError("mais de um rosto na foto; envie uma foto só da pessoa")
        f = faces[0]
        if f.w < 40:
            raise ValueError("rosto muito pequeno na foto")
        aligned = self.align(img, f)
        emb = self.embed(aligned)
        info = {"w": f.w, "yaw": f.yaw(), "sharp": sharpness(aligned), "score": f.score}
        return aligned, emb, info


class Gallery:
    """Embeddings de todos os membros ativos, para comparação rápida."""

    def __init__(self):
        self.matrix = np.zeros((0, 128), np.float32)
        self.labels = np.zeros(0, np.int64)
        self.names = {}

    def __len__(self):
        return len(self.labels)

    def load(self, con):
        rows = con.execute(
            "SELECT s.member_id, s.embedding FROM samples s JOIN members m ON m.id = s.member_id "
            "WHERE s.status = 'ok' AND s.embedding IS NOT NULL AND m.active = 1").fetchall()
        embs = [db.blob_to_emb(r["embedding"]) for r in rows]
        self.matrix = np.stack(embs).astype(np.float32) if embs else np.zeros((0, 128), np.float32)
        self.labels = np.array([r["member_id"] for r in rows], np.int64)
        self.names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM members")}

    def match(self, emb):
        """Lista (member_id, similaridade) do mais parecido para o menos parecido."""
        if not len(self.labels):
            return []
        sims = self.matrix @ emb
        best = {}
        for label, s in zip(self.labels.tolist(), sims.tolist()):
            if s > best.get(label, -2.0):
                best[label] = s
        return sorted(best.items(), key=lambda kv: -kv[1])

    def member_sims(self, member_id, emb):
        mask = self.labels == member_id
        return self.matrix[mask] @ emb if mask.any() else np.zeros(0, np.float32)
