"""A small PDF writer with no dependencies: A4 pages, Helvetica text, lines, rectangles and polylines. Enough for
printable reports (tables and simple charts) that open in any PDF reader. Pure Python (unit-tested)."""
from __future__ import annotations

import zlib

A4 = (595.28, 841.89)

# Helvetica / Helvetica-Bold advance widths (1/1000 em) for ASCII 32..126, from the Adobe core-font metrics
_W = {
    "F1": [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556,
           556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278,
           500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469,
           556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500,
           278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584],
    "F2": [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556,
           556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278,
           556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584,
           556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556,
           333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584],
}
_EXTRA = {"°": 400, "–": 556, "—": 1000, "•": 350, "·": 278, "×": 584, "±": 584, "’": 222, "‘": 222, "“": 333,
          "”": 333, "€": 556, "µ": 556, "²": 333, "³": 333}
_SUBST = {"✓": "OK", "✗": "x", "→": "->", "≥": ">=", "≤": "<=", "…": "...", "³": "3", "₂": "2", " ": " ",
          " ": " "}


def clean(s: str) -> str:
    """Text the core fonts can show (Windows-1252); anything else becomes '?'."""
    s = "".join(_SUBST.get(c, c) for c in str(s))
    return s.encode("cp1252", "replace").decode("cp1252")


def text_width(s: str, size: float, bold: bool = False) -> float:
    w = _W["F2" if bold else "F1"]
    total = 0
    for c in clean(s):
        o = ord(c)
        total += w[o - 32] if 32 <= o <= 126 else _EXTRA.get(c, 556)
    return total * size / 1000


def fit(s: str, size: float, width: float, bold: bool = False) -> str:
    """Shorten text with '...' so it fits the width."""
    s = clean(s)
    if text_width(s, size, bold) <= width:
        return s
    while s and text_width(s + "...", size, bold) > width:
        s = s[:-1]
    return s + "..."


def wrap(s: str, size: float, width: float, bold: bool = False) -> list[str]:
    lines, cur = [], ""
    for word in clean(s).split():
        t = f"{cur} {word}".strip()
        if text_width(t, size, bold) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def _esc(s: str) -> bytes:
    b = clean(s).encode("cp1252")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _rgb(c: str | tuple) -> str:
    if isinstance(c, str):
        c = c.lstrip("#")
        c = tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return " ".join(f"{x:.3f}" for x in c)


class Page:
    """Coordinates in points from the TOP-left corner (y grows downwards), converted on output."""

    def __init__(self, size: tuple[float, float]) -> None:
        self.w, self.h = size
        self.ops: list[bytes] = []

    def _y(self, y: float) -> float:
        return self.h - y

    def text(self, x: float, y: float, s: str, size: float = 10, bold: bool = False, color: str = "#1b1b1b",
             align: str = "left") -> None:
        """y is the baseline."""
        if align != "left":
            w = text_width(s, size, bold)
            x -= w if align == "right" else w / 2
        self.ops.append(b"BT /%s %.1f Tf %s rg %.2f %.2f Td (" % (b"F2" if bold else b"F1", size, _rgb(color).encode(),
                                                                   x, self._y(y)) + _esc(s) + b") Tj ET")

    def line(self, x1: float, y1: float, x2: float, y2: float, color: str = "#999999", width: float = 0.5,
             dash: tuple[float, float] | None = None) -> None:
        d = b"[%.1f %.1f] 0 d " % dash if dash else b"[] 0 d "
        self.ops.append(d + b"%s RG %.2f w %.2f %.2f m %.2f %.2f l S" % (
            _rgb(color).encode(), width, x1, self._y(y1), x2, self._y(y2)))

    def rect(self, x: float, y: float, w: float, h: float, fill: str | None = None, stroke: str | None = None,
             width: float = 0.5) -> None:
        """x, y = top-left corner."""
        op = b"B" if fill and stroke else (b"f" if fill else b"S")
        parts = [b"[] 0 d"]
        if fill:
            parts.append(_rgb(fill).encode() + b" rg")
        if stroke:
            parts.append(_rgb(stroke).encode() + b" RG %.2f w" % width)
        parts.append(b"%.2f %.2f %.2f %.2f re %s" % (x, self._y(y + h), w, h, op))
        self.ops.append(b" ".join(parts))

    def polyline(self, pts: list[tuple[float, float]], color: str = "#1f6feb", width: float = 1.0) -> None:
        if len(pts) < 2:
            return
        path = [b"%.2f %.2f m" % (pts[0][0], self._y(pts[0][1]))]
        path += [b"%.2f %.2f l" % (x, self._y(y)) for x, y in pts[1:]]
        self.ops.append(b"[] 0 d 1 J 1 j %s RG %.2f w " % (_rgb(color).encode(), width) + b" ".join(path) + b" S")


class Pdf:
    def __init__(self, title: str = "", author: str = "", size: tuple[float, float] = A4) -> None:
        self.size, self.title, self.author = size, title, author
        self.pages: list[Page] = []

    def page(self) -> Page:
        p = Page(self.size)
        self.pages.append(p)
        return p

    def output(self) -> bytes:
        objs: list[bytes] = []

        def add(b: bytes) -> int:
            objs.append(b)
            return len(objs)

        f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        pages = self.pages or [Page(self.size)]
        pages_id = len(objs) + 2 * len(pages) + 2                 # after the page objects and the info object
        kids = []
        for p in pages:
            data = zlib.compress(b"\n".join(p.ops))
            c = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
            kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font << "
                            b"/F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>" % (pages_id, p.w, p.h, f1, f2, c)))
        info = add(b"<< /Title (" + _esc(self.title) + b") /Author (" + _esc(self.author) +
                   b") /Producer (Milesight LoRaWAN for Home Assistant) >>")
        pid = add(b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids))
        assert pid == pages_id, (pid, pages_id)
        root = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pid)
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, o in enumerate(objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objs) + 1, root, info, xref)
        return bytes(out)
