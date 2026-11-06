"""One place that opens ONNX models: GPU (CUDA / DirectML) when allowed and present, CPU otherwise, with an automatic CPU retry if the GPU run fails."""
import numpy as np

def dtype_of(inp):
    t = (getattr(inp, "type", "") or "").lower()
    return np.float64 if "double" in t else (np.float16 if "float16" in t else np.float32)

class OnnxModel:
    def __init__(self, path, prefer_gpu=True):
        import onnxruntime as ort
        self._ort, self.path = ort, path; self.sess = None; self.providers = []; self._open(prefer_gpu)
    def _open(self, gpu):
        avail = self._ort.get_available_providers(); prov = [p for p in ("CUDAExecutionProvider", "DmlExecutionProvider") if gpu and p in avail] + ["CPUExecutionProvider"]
        try: self.sess = self._ort.InferenceSession(self.path, providers=prov)
        except Exception:
            if prov == ["CPUExecutionProvider"]: raise
            self.sess = self._ort.InferenceSession(self.path, providers=["CPUExecutionProvider"])
        self.providers = self.sess.get_providers(); self.inputs = self.sess.get_inputs()
    def run(self, build_feed):
        """build_feed(session) -> {input_name: array}. Returns the list of outputs."""
        try: return self.sess.run(None, build_feed(self.sess))
        except Exception:
            if self.providers and self.providers[0] != "CPUExecutionProvider": self._open(False); return self.sess.run(None, build_feed(self.sess))
            raise
