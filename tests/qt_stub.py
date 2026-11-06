"""A permissive FAKE of PySide6 - ONLY for headless smoke tests of our own UI code (name errors, wrong attributes, wrong call signatures,
logic bugs). It cannot check real Qt behaviour (layout, painting, enum names): run the app on Windows for that.
Widgets that our code reads values back from (combo, spin, slider, check, line edit, list, tabs, stack) behave like the real ones."""
import sys, types

class _Meta(type):
    def __getattr__(cls, n):
        if n.startswith("__"): raise AttributeError(n)
        d = cls.__dict__.get("_enum_cache")
        if d is None: d = {}; type.__setattr__(cls, "_enum_cache", d)
        if n not in d: d[n] = _Any()      # Qt.AlignmentFlag.AlignCenter ... stable per name, so `x == Qt.Something.Yes` behaves like a real enum
        return d[n]

class _Any:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n):
        if n.startswith("__"): raise AttributeError(n)
        c = self.__dict__.setdefault("_c", {})                  # stable per name (enum-like), so `x == Qt.Foo.Bar` works
        if n not in c: c[n] = _Any()
        return c[n]
    def __call__(self, *a, **k): return _Any()
    def __iter__(self): return iter(())
    def __bool__(self): return True
    def __or__(self, o): return _Any()
    __ror__ = __and__ = __rand__ = __mul__ = __add__ = __or__
    def __eq__(self, o): return self is o
    def __hash__(self): return id(self)

class _Sig:
    def __init__(self): self.fns = []
    def connect(self, f): self.fns.append(f)
    def disconnect(self, *a): self.fns = []
    def emit(self, *a):
        for f in list(self.fns): f(*a)

class Signal:
    def __init__(self, *a): pass
    def __set_name__(self, owner, name): self.name = "_sig_" + name
    def __get__(self, obj, typ=None):
        if obj is None: return self
        if self.name not in obj.__dict__: obj.__dict__[self.name] = _Sig()
        return obj.__dict__[self.name]

def _sig(obj, name):
    k = "_sig_" + name
    if k not in obj.__dict__: obj.__dict__[k] = _Sig()
    return obj.__dict__[k]

class Base(metaclass=_Meta):
    def __init__(self, *a, **k): pass
    def __getattr__(self, n):
        if n.startswith("__") or n.startswith("_sig_"): raise AttributeError(n)
        if n in ("clicked", "toggled", "valueChanged", "currentIndexChanged", "textChanged", "triggered", "timeout", "itemChanged", "currentItemChanged", "itemActivated",
                 "sliderReleased", "currentChanged", "tabCloseRequested", "accepted", "rejected", "paintRequested", "aboutToShow", "colorChanged_"): return _sig(self, n)
        if n in ("width", "height"): return lambda *a: 900 if n == "width" else 650
        if n in ("logicalDpiX", "logicalDpiY"): return lambda *a: 96
        if n in ("count", "rowCount", "columnCount"): return lambda *a: 0          # layouts / tables: empty, so 'while layout.count()' loops end
        return _Any()
    def __bool__(self): return True
    def __eq__(self, o): return self is o
    def __hash__(self): return id(self)

class Combo(Base):
    def __init__(self, *a): self._items = []; self._i = -1
    def addItem(self, text, data=None): self._items.append((text, data)); self._i = max(self._i, 0)               # like Qt: no data -> None
    def addItems(self, ts): [self.addItem(t) for t in ts]
    def currentIndex(self): return self._i
    def setCurrentIndex(self, i): self._i = i; _sig(self, "currentIndexChanged").emit(i)
    def currentData(self): return self._items[self._i][1] if self._i >= 0 else None
    def currentText(self): return self._items[self._i][0] if self._i >= 0 else ""
    def setCurrentText(self, t):
        for i, (a, _) in enumerate(self._items):
            if a == t: self._i = i
    def count(self): return len(self._items)
    def itemData(self, i): return self._items[i][1]
    def clear(self): self._items = []; self._i = -1

class Spin(Base):
    def __init__(self, *a): self._v = 0; self._lo = 0; self._hi = 99
    def setRange(self, lo, hi): self._lo, self._hi = lo, hi
    def setValue(self, v): self._v = max(self._lo, min(self._hi, v)); _sig(self, "valueChanged").emit(self._v)
    def value(self): return self._v

class Slider(Spin):
    def __init__(self, *a): super().__init__(); self._blocked = False
    def blockSignals(self, b): self._blocked = b
    def setValue(self, v):
        self._v = max(self._lo, min(self._hi, v))
        if not self._blocked: _sig(self, "valueChanged").emit(self._v)

class Check(Base):
    def __init__(self, *a): self._c = False
    def setChecked(self, c):
        if c != self._c: self._c = c; _sig(self, "toggled").emit(c)
    def isChecked(self): return self._c

class Edit(Base):
    def __init__(self, t="", *a): self._t = t if isinstance(t, str) else ""
    def text(self): return self._t
    def setText(self, t): self._t = t; _sig(self, "textChanged").emit(t)

class Label(Base):
    def __init__(self, t="", *a): self._t = t if isinstance(t, str) else ""
    def text(self): return self._t
    def setText(self, t): self._t = t

class Item(Base):
    def __init__(self, t="", *a): self._t, self._d, self._cs = t, {}, None
    def setData(self, role, v): self._d[id(role) if not isinstance(role, (int, str)) else role] = v
    def data(self, role): return self._d.get(id(role) if not isinstance(role, (int, str)) else role)
    def text(self): return self._t
    def flags(self): return 0
    def setFlags(self, f): pass
    def setCheckState(self, s): self._cs = s
    def checkState(self): return self._cs

class ListW(Base):
    def __init__(self, *a): self._items = []; self._cur = None
    def clear(self): self._items = []; self._cur = None
    def addItem(self, it): self._items.append(it)
    def setCurrentItem(self, it): self._cur = it
    def currentItem(self): return self._cur
    def count(self): return len(self._items)

class Stack(Base):
    def __init__(self, *a): self._w = []; self._i = -1
    def addWidget(self, w): self._w.append(w); self._i = max(self._i, 0); return len(self._w) - 1
    def setCurrentIndex(self, i): self._i = i
    def setCurrentWidget(self, w): self._i = self._w.index(w)
    def currentIndex(self): return self._i
    def currentWidget(self): return self._w[self._i] if 0 <= self._i < len(self._w) else None
    def widget(self, i): return self._w[i]
    def count(self): return len(self._w)

class Tabs(Base):
    def __init__(self, *a): self._w = []; self._t = []; self._i = -1
    def addTab(self, w, t): self._w.append(w); self._t.append(t); return len(self._w) - 1
    def setCurrentIndex(self, i): self._i = i; _sig(self, "currentChanged").emit(i)
    def currentIndex(self): return self._i
    def currentWidget(self): return self._w[self._i] if 0 <= self._i < len(self._w) else None
    def widget(self, i): return self._w[i]
    def count(self): return len(self._w)
    def setTabText(self, i, t): self._t[i] = t
    def tabText(self, i): return self._t[i]
    def removeTab(self, i):
        del self._w[i]; del self._t[i]; self._i = min(self._i, len(self._w) - 1); _sig(self, "currentChanged").emit(self._i)

class Timer(Base):
    def __init__(self, *a): pass
    @staticmethod
    def singleShot(ms, fn): fn()
    def start(self, *a): pass
    def stop(self): pass

class Application(Base):
    _inst = None
    def __init__(self, *a): Application._inst = self
    @staticmethod
    def instance(): return Application._inst or Application()

_SPECIAL = {"QComboBox": Combo, "QSpinBox": Spin, "QDoubleSpinBox": Spin, "QSlider": Slider, "QCheckBox": Check, "QRadioButton": Check, "QLineEdit": Edit, "QLabel": Label,
            "QListWidgetItem": Item, "QListWidget": ListW, "QStackedWidget": Stack, "QTabWidget": Tabs, "QTimer": Timer, "QApplication": Application, "Signal": Signal}
_cache = {}

def _mk(modname):
    m = types.ModuleType("PySide6." + modname)
    def __getattr__(name):
        if name.startswith("__"): raise AttributeError(name)
        if name not in _cache:
            if name in _SPECIAL: _cache[name] = _SPECIAL[name]
            else: _cache[name] = _Meta(name, (Base,), {})
        return _cache[name]
    m.__getattr__ = __getattr__; return m

def install():
    if "PySide6" in sys.modules and getattr(sys.modules["PySide6"], "_is_stub", False): return
    pkg = types.ModuleType("PySide6"); pkg.__path__ = []; pkg._is_stub = True; sys.modules["PySide6"] = pkg
    for n in ("QtCore", "QtGui", "QtWidgets", "QtSvg", "QtPrintSupport"):
        sub = _mk(n); sys.modules["PySide6." + n] = sub; setattr(pkg, n, sub)
