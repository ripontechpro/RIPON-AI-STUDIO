"""Builds a tiny REAL ONNX file by hand (no 'onnx' package needed) so onnxruntime paths can be tested:
input x [1,3,H,W] float32  ->  ReduceMean over channels -> Sigmoid  ->  y [1,1,H,W]   (a stand-in for a matting network, same tensor shapes as MODNet)."""
def _v(n):
    out = b""
    while True:
        b = n & 0x7F; n >>= 7
        if n: out += bytes([b | 0x80])
        else: return out + bytes([b])
def _key(num, wt): return _v((num << 3) | wt)
def _ld(num, data): return _key(num, 2) + _v(len(data)) + data
def _vi(num, n): return _key(num, 0) + _v(n)
def _s(num, text): return _ld(num, text.encode())
def _dim_param(name): return _ld(1, _s(2, name))
def _dim_value(n): return _ld(1, _vi(1, n))
def _value_info(name, dims):
    shape = b"".join(dims); tensor = _vi(1, 1) + _ld(2, shape)
    return _s(1, name) + _ld(2, _ld(1, tensor))
def build(path, opset=13):
    attr_axes = _s(1, "axes") + _ld(8, _v(1)) + _vi(20, 7)                       # axes = [1] (INTS)
    n1 = _s(1, "x") + _s(2, "m") + _s(3, "mean") + _s(4, "ReduceMean") + _ld(5, attr_axes)
    n2 = _s(1, "m") + _s(2, "y") + _s(3, "sig") + _s(4, "Sigmoid")
    graph = _ld(1, n1) + _ld(1, n2) + _s(2, "tiny") + _ld(11, _value_info("x", [_dim_value(1), _dim_value(3), _dim_param("h"), _dim_param("w")])) \
          + _ld(12, _value_info("y", [_dim_value(1), _dim_value(1), _dim_param("h"), _dim_param("w")]))
    model = _vi(1, 8) + _s(2, "ripon-test") + _s(6, "x" * 2000) + _ld(7, graph) + _ld(8, _s(1, "") + _vi(2, opset))
    with open(path, "wb") as f: f.write(model)
    return path

# ---- general builder: tiny stand-ins with the same input/output signatures as the real networks --------------------------------------------
def _node(op, ins, outs, name): return _ld(1, b"".join(_s(1, i) for i in ins) + b"".join(_s(2, o) for o in outs) + _s(3, name) + _s(4, op))
def build_custom(path, nodes, inputs, outputs, opset=13):
    """nodes: [(op, [in..], [out..])]; inputs/outputs: [(name, [dims])] where dims are ints or strings (symbolic)."""
    vi = lambda name, dims: _value_info(name, [_dim_value(d) if isinstance(d, int) else _dim_param(d) for d in dims])
    graph = b"".join(_node(op, i, o, f"n{k}") for k, (op, i, o) in enumerate(nodes)) + _s(2, "tiny") + b"".join(_ld(11, vi(n, d)) for n, d in inputs) + b"".join(_ld(12, vi(n, d)) for n, d in outputs)
    model = _vi(1, 8) + _s(2, "ripon-test") + _s(6, "x" * 2000) + _ld(7, graph) + _ld(8, _s(1, "") + _vi(2, opset))
    with open(path, "wb") as f: f.write(model)
    return path
def build_lama_like(path):          # out = image + mask   (inputs named like big-lama's ONNX export)
    return build_custom(path, [("Add", ["image", "mask"], ["out"])], [("image", [1, 3, "h", "w"]), ("mask", [1, 1, "h", "w"])], [("out", [1, 3, "h", "w"])])
def build_gfpgan_like(path):        # out = x   (identity)
    return build_custom(path, [("Identity", ["input"], ["output"])], [("input", [1, 3, 512, 512])], [("output", [1, 3, 512, 512])])
def build_codeformer_like(path):    # out = x * weight   (weight is a scalar input like CodeFormer's fidelity)
    return build_custom(path, [("Mul", ["x", "w"], ["y"])], [("x", [1, 3, 512, 512]), ("w", [])], [("y", [1, 3, 512, 512])])
