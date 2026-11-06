"""MODNet portrait matting through onnxruntime (no torch). Ported from the earlier Ripon Computer AI Studio, which used the same model file
(<models>/modnet/modnet.onnx) and the official MODNet resize rule (shorter side -> `ref`, sizes multiples of 32)."""
import numpy as np, cv2
from .onnxutil import OnnxModel, dtype_of

class MODNetMatter:
    def __init__(self, path, prefer_gpu=True):
        self.path = path; self.model = OnnxModel(path, prefer_gpu)
    @property
    def providers(self): return self.model.providers
    def matte(self, rgb, ref=640):
        """RGB uint8 -> float32 alpha (H, W) in 0..1."""
        rgb = np.ascontiguousarray(np.asarray(rgb)[..., :3]); H, W = rgb.shape[:2]; ref = int(ref)
        if max(H, W) < ref or min(H, W) > ref: rh, rw = (ref, int(W / H * ref)) if W >= H else (int(H / W * ref), ref)
        else: rh, rw = H, W
        rw, rh = max(32, rw - rw % 32), max(32, rh - rh % 32)
        im = cv2.resize(rgb, (rw, rh), interpolation=cv2.INTER_AREA if rw < W else cv2.INTER_CUBIC)
        x = ((im.astype(np.float32) / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None]
        o = self.model.run(lambda s: {s.get_inputs()[0].name: x.astype(dtype_of(s.get_inputs()[0]))})[0]
        m = np.asarray(o, np.float32).reshape(rh, rw)
        return np.clip(cv2.resize(m, (W, H), interpolation=cv2.INTER_CUBIC), 0, 1)
