"""One consistent icon set (24x24, 1.8px round strokes), drawn here as SVG so no image files are needed and colour follows the theme."""
_I = {
 "home": '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
 "crop": '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M2 6h14a2 2 0 0 1 2 2v14"/>',
 "resize": '<path d="M4 14v6h6"/><path d="M20 10V4h-6"/><path d="M4 20L20 4"/>',
 "rotate": '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/>',
 "transform": '<rect x="5" y="5" width="14" height="14" rx="1"/><circle cx="5" cy="5" r="1.6"/><circle cx="19" cy="5" r="1.6"/><circle cx="5" cy="19" r="1.6"/><circle cx="19" cy="19" r="1.6"/>',
 "select": '<path d="M5 3h3M11 3h3M17 3h2v2M19 8v3M19 14v3M19 19h-3M13 19h-3M7 19H5v-2M5 14v-3M5 8V5" />',
 "move": '<path d="M12 2v20M2 12h20"/><path d="M9 5l3-3 3 3M9 19l3 3 3-3M5 9l-3 3 3 3M19 9l3 3-3 3"/>',
 "hand": '<path d="M8 13V5a1.5 1.5 0 0 1 3 0v6M11 10V3.5a1.5 1.5 0 0 1 3 0V10M14 10V5a1.5 1.5 0 0 1 3 0v8"/><path d="M8 13l-2-2a1.6 1.6 0 0 0-2.4 2.1L8 20a5 5 0 0 0 4 2h2a5 5 0 0 0 5-5v-4a1.5 1.5 0 0 0-3 0"/>',
 "brush": '<path d="M18 3l3 3-9.5 9.5-3-3z"/><path d="M8.5 12.5C6 12.5 5 14 5 16c0 2-1 3-2 4 3 1 8 1 8-3"/>',
 "eraser": '<path d="M20 20H9L3.5 14.5a2 2 0 0 1 0-2.8L12 3.2a2 2 0 0 1 2.8 0l6 6a2 2 0 0 1 0 2.8L13 20"/><path d="M7 11l6 6"/>',
 "text": '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
 "shape": '<rect x="3" y="11" width="10" height="10" rx="1"/><circle cx="16" cy="8" r="5"/>',
 "picker": '<path d="M14 6l4 4M3 21l2-6L16 4a2.8 2.8 0 0 1 4 4L9 19z"/>',
 "adjust": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
 "ai": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
 "doc": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
 "passport": '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="11" r="2.2"/><path d="M5.5 16.5c.6-2 2-3 3.5-3s2.900 1 3.500 3M15 10h4M15 14h3"/>',
 "layout": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>',
 "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
 "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
 "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>',
 "new": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M12 11v6M9 14h6"/>',
 "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
 "save": '<path d="M5 3h11l4 4v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M8 3v5h7V3M8 21v-7h8v7"/>',
 "export": '<path d="M12 15V3M7 8l5-5 5 5"/><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/>',
 "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5M3 17.500l9 5 9-5"/>',
 "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
 "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
 "copy": '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/>',
 "up": '<path d="M12 19V5M6 11l6-6 6 6"/>', "down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
 "plus": '<path d="M12 5v14M5 12h14"/>',
 "fit": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
 "zoomin": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.500-4.500M11 8v6M8 11h6"/>', "zoomout": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.500-4.500M8 11h6"/>',
 "compare": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/><path d="M7 9l-2 3 2 3M17 9l2 3-2 3"/>',
 "cancel": '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
 "check": '<path d="M5 12.500l4.500 4.500L19 7"/>',
 "print": '<path d="M7 9V3h10v6"/><rect x="4" y="9" width="16" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
 "flip": '<path d="M12 3v18M8 7L3 12l5 5zM16 7l5 5-5 5z"/>',
 "merge": '<path d="M6 3v6a6 6 0 0 0 6 6 6 6 0 0 0 6-6V3M12 15v6M9 18l3 3 3-3"/>',
 "face": '<circle cx="12" cy="12" r="9"/><circle cx="9" cy="10" r="1"/><circle cx="15" cy="10" r="1"/><path d="M8 15c1.200 1.500 2.500 2.200 4 2.200s2.800-.7 4-2.200"/>',
 "lasso": '<path d="M12 4c-4.400 0-8 2-8 4.500S7.600 13 12 13s8-2 8-4.500S16.400 4 12 4z"/><path d="M8 12.500c-1.500 2.500-.5 5 2.500 6.500 1 .5 1.500 1.500 1 2.500"/>',
 "poly": '<path d="M4 18L7 6l9-2 4 8-6 6z"/><circle cx="7" cy="6" r="1.200"/><circle cx="16" cy="4" r="1.200"/><circle cx="20" cy="12" r="1.200"/>',
 "wand": '<path d="M4 20L15 9"/><path d="M15 9l2.500 2.500"/><path d="M17 3v3M21 7h-3M20 4l-2 2M13 4v1"/>',
 "bucket": '<path d="M5 11l7-7 7 7-6.500 6.500a2 2 0 0 1-3 0z"/><path d="M5 11h14"/><path d="M20 15c0 1.500-1 2.500-1 3.500a1 1 0 0 0 2 0c0-1-1-2-1-3.500z"/>',
 "gradient": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 17L17 7M7 12l5-5M12 17l5-5"/>',
 "stamp": '<path d="M9 14h6l1 5H8z"/><path d="M12 14V9a3 3 0 1 0-3-3"/><path d="M5 21h14"/>',
 "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16l-5-5-8 9"/>',
 "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
}
NAMES = tuple(_I)
_cache = {}

def svg(name, color="#e7e9ee", stroke=1.8):
    body = _I.get(name, _I["image"])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="{stroke}" '
            f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')

def icon(name, color="#e7e9ee", size=22):
    """QIcon for `name` (needs QtSvg; imported lazily so the SVG data stays testable without Qt)."""
    key = (name, color, size)
    if key in _cache: return _cache[key]
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QIcon, QPixmap, QPainter
    from PySide6.QtSvg import QSvgRenderer
    r = QSvgRenderer(QByteArray(svg(name, color).encode("utf-8")))
    pm = QPixmap(size * 2, size * 2); pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm); r.render(p); p.end()
    ic = QIcon(pm); _cache[key] = ic; return ic
