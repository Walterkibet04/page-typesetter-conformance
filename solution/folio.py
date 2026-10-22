#!/usr/bin/env python3
"""folio: a small page typesetter. Reads a .fol document, writes the laid-out pages as JSON."""
import json
import re
import sys

MEASURE = 360
SPACE_MIN = 3
NAT_SPACE = 4
LOOSE = 7
ROW = 12
PAGE_ROWS = 36
INDENT = 24
DC_W = 30
DC_ROWS = 3
HYPH_W = 5
MARK_W = 3
LINE_PEN = 13
HYPH_PEN = 65
HARD_PEN = 20
DOUBLE_HYPH = 4200
ADJ_FIT = 2600
FINAL_HYPH = 2200
RUNT_DEM = 1700
RUNT_W = 44
TOL1 = 650
TOL2 = 3500
TOL3 = 10000
GLUE_STRETCH = 3
GLUE_SHRINK = 1
FN_SPACE = 3
FN_RULE_PT = 18
FN_LINE_PT = 9
HEAD_BEFORE = {1: 3, 2: 2}
HEAD_ROWS = {1: 2, 2: 1}
HEAD_AFTER = {1: 1, 2: 1}
EXCEPTIONS = {"typography": [2, 5, 7], "programme": [3], "throughout": [], "interesting": [2, 5]}
DIGRAPHS = {"th", "ch", "sh", "tr", "gr", "cl", "pl"}
NARROW = set("ilItfj!.,;:'|()")
WIDE = set("mwMW")
VOWELS = set("aeiou")
MAX_PASSES = 6
START_PAGE = 3
REF_RE = re.compile(r"\{@([a-z0-9]+)\}")
ANCHOR_RE = re.compile(r"\{#([a-z0-9]+)\}\s*")
ROMAN = ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
         (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"))

def cw(c):
    if c in NARROW:
        return 4
    if c in WIDE:
        return 12
    if c == "-":
        return 5
    if c == "\u00a0":
        return NAT_SPACE
    if c.isupper():
        return 10
    return 8


def width(s):
    return sum(cw(c) for c in s)


def fn_width(s):
    return (width(s) * 18) // 25


class Word:
    def __init__(self, text, mark=None):
        self.text = text
        self.mark = mark

    @property
    def w(self):
        return width(self.text) + (MARK_W if self.mark else 0)


def hyph_points(text):
    low = text.lower()
    if low in EXCEPTIONS:
        return list(EXCEPTIONS[low])
    if not (text.isalpha() and text.islower() and len(text) >= 6):
        return []
    pts = []
    n = len(text)
    for p in range(3, n - 1):
        a, b = text[p - 1], text[p]
        if a in VOWELS and b not in VOWELS and p + 1 < n and text[p + 1] in VOWELS:
            pts.append(p)
        elif (p >= 2 and text[p - 2] in VOWELS and a not in VOWELS and b not in VOWELS
              and p + 1 < n and text[p + 1] in VOWELS and (a + b) not in DIGRAPHS):
            pts.append(p)
    return pts


def badness(x, tot):
    return min(10000, (85 * x ** 3) // tot ** 3)


def line_fit(adj, g, last):
    """Badness and fitness class of a line whose natural width differs from the
    available width by adj and which holds g glue gaps; None if it cannot shrink enough."""
    if adj >= 0:
        if last:
            return 0, 1
        st = GLUE_STRETCH * g
        if st == 0:
            return (0, 1) if adj == 0 else (10000, 1)
        cls = 3 if adj > st else (2 if 2 * adj > st else 1)
        return badness(adj, st), cls
    sh = GLUE_SHRINK * g
    if -adj > sh:
        return None
    return badness(-adj, sh), (0 if 2 * (-adj) > sh else 1)


def pieces_of(words):
    P = []
    for W in words:
        t = W.text
        cuts = {}
        for i, ch in enumerate(t[:-1]):
            if ch == "-" and i + 1 >= 2:
                cuts[i + 1] = "hard"
        if W.mark is None:
            for p in hyph_points(t):
                if 0 < p < len(t):
                    cuts.setdefault(p, "soft")
        pos = 0
        for c in sorted(cuts):
            P.append({"t": t[pos:c], "k": cuts[c], "mark": None})
            pos = c
        P.append({"t": t[pos:], "k": "glue", "mark": W.mark})
    P[-1]["k"] = "end"
    for p in P:
        p["w"] = width(p["t"]) + (MARK_W if p["mark"] else 0)
    return P


def kp_path(P, indent_first, dropcap, tol, overfull):
    N = len(P)
    pre = [0]
    gl = [0]
    for p in P:
        pre.append(pre[-1] + p["w"])
        gl.append(gl[-1] + (1 if p["k"] == "glue" else 0))

    def avail(j):
        if j == 0 and indent_first:
            return MEASURE - INDENT
        if dropcap and j < DC_ROWS:
            return MEASURE - DC_W
        return MEASURE

    states = {-1: {(0, 1): (0, ())}}
    for i in range(-1, N):
        cur = states.get(i)
        if not cur:
            continue
        for (l, pf), (dem, path) in sorted(cur.items()):
            av = avail(l)
            prevflag = i >= 0 and P[i]["k"] in ("hard", "soft")
            found = False
            for e in range(i + 1, N):
                g = gl[e] - gl[i + 1]
                if pre[e + 1] - pre[i + 1] + 3 * g > av and found:
                    break
                if pre[e + 1] - pre[i + 1] + 3 * g > av and not overfull:
                    break
                brk = P[e]["k"]
                wsum = pre[e + 1] - pre[i + 1] + (HYPH_W if brk == "soft" else 0)
                adj = av - (wsum + NAT_SPACE * g)
                fit = line_fit(adj, g, e == N - 1)
                if fit is None:
                    if not overfull:
                        continue
                    fit = (10000, 0)
                b, cls = fit
                if b > tol and not (overfull and fit == (10000, 0)):
                    continue
                flag = brk in ("hard", "soft")
                p = (HYPH_PEN if brk == "soft" else HARD_PEN) if flag else 0
                d = (LINE_PEN + b) ** 2 + p * p
                if flag and prevflag:
                    d += DOUBLE_HYPH
                if e == N - 1 and prevflag:
                    d += FINAL_HYPH
                if e == N - 1 and i >= 0 and g == 0 and pre[e + 1] - pre[i + 1] < RUNT_W:
                    d += RUNT_DEM
                if abs(cls - pf) > 1:
                    d += ADJ_FIT
                l2 = min(l + 1, 3)
                key = (l2, cls)
                new = (dem + d, path + (e,))
                tgt = states.setdefault(e, {})
                old = tgt.get(key)
                if old is None or new < old:
                    tgt[key] = new
                found = True
                if overfull and fit == (10000, 0):
                    break
    fin = states.get(N - 1)
    if not fin:
        return None
    return min(fin.values())[1]


def break_paragraph(words, indent_first, dropcap):
    P = pieces_of(words)
    path = None
    for tol, over in ((TOL1, False), (TOL2, False), (TOL3, True)):
        path = kp_path(P, indent_first, dropcap, tol, over)
        if path is not None:
            break
    lines = []
    start = 0
    for j, e in enumerate(path):
        seg = P[start:e + 1]
        if j == 0 and indent_first:
            ind = INDENT
        elif dropcap and j < DC_ROWS:
            ind = DC_W
        else:
            ind = 0
        avail = MEASURE - ind
        last = e == len(P) - 1
        brk = P[e]["k"]
        toks = []
        curw = ""
        wsum = 0
        g = 0
        marks = []
        for q, p in enumerate(seg):
            curw += p["t"]
            wsum += p["w"]
            if p["mark"]:
                marks.append(p["mark"])
            if p["k"] in ("glue", "end"):
                toks.append(curw + ("^%d" % p["mark"] if p["mark"] else ""))
                curw = ""
                if q < len(seg) - 1:
                    g += 1
        if curw:
            toks.append(curw + ("-" if brk == "soft" else ""))
        if brk == "soft":
            wsum += HYPH_W
        slack = avail - wsum
        if g == 0:
            gaps = []
        elif last:
            gaps = [min(NAT_SPACE, slack // g)] * g
        else:
            base, extra = slack // g, slack % g
            gaps = [base + (1 if ((q + 1) * extra) // g > (q * extra) // g else 0) for q in range(g)]
        lines.append({"t": " ".join(toks), "x": ind, "g": gaps, "fn": marks, "s": brk == "soft"})
        start = e + 1
    return lines


def break_footnote(label, text):
    words = [label] + text.split()
    lines = []
    cur = []
    s = 0
    for w in words:
        sw = fn_width(w)
        n = len(cur) + 1
        if cur and s + sw + (n - 1) * FN_SPACE > MEASURE:
            lines.append(" ".join(cur))
            cur, s = [], 0
            n = 1
        cur.append(w)
        s += sw
    if cur:
        lines.append(" ".join(cur))
    return lines


def block_rows(L):
    if L == 0:
        return 0
    return -(-(FN_RULE_PT + FN_LINE_PT * L) // ROW)


def roman(n):
    out = ""
    for v, sym in ROMAN:
        while n >= v:
            out += sym
            n -= v
    return out


def parse(text):
    blocks = []
    footnotes = {}
    counter = 0
    for raw in text.replace("\r", "").split("\n\n"):
        raw = raw.strip("\n")
        if not raw.strip():
            continue
        if raw.startswith("## "):
            blocks.append({"k": "h2", "text": raw[3:].strip()})
            continue
        if raw.startswith("# "):
            blocks.append({"k": "h1", "text": raw[2:].strip()})
            continue
        anchor = None
        m = ANCHOR_RE.match(raw)
        if m:
            anchor = m.group(1)
            raw = raw[m.end():]
        dropcap = raw.startswith("^")
        if dropcap:
            raw = raw[1:]
        body = " ".join(raw.split("\n"))
        out = []
        i = 0
        while i < len(body):
            if body.startswith("[[", i):
                e = body.index("]]", i)
                counter += 1
                footnotes[counter] = body[i + 2:e].strip()
                out.append("\x01%d\x02" % counter)
                i = e + 2
            else:
                out.append(body[i])
                i += 1
        body = "".join(out)
        toks = []
        for tok in body.split():
            mark = None
            if "\x01" in tok:
                a = tok.index("\x01")
                mark = int(tok[a + 1:tok.index("\x02")])
                tok = tok[:a]
            toks.append((tok, mark))
        blocks.append({"k": "p", "toks": toks, "dropcap": dropcap, "anchor": anchor})
    return blocks, footnotes


class Page:
    def __init__(self, number, carry):
        self.number = number
        self.entries = []
        self.used = 0
        self.parts = list(carry)
        self.closed = False

    @property
    def fnlines(self):
        return sum(len(p[1]) for p in self.parts)


def layout(blocks, fn_lines, table, cache):
    pages = []
    pending = []
    anchors = {}

    def new_page():
        nonlocal pending
        pages.append(Page(len(pages) + 1, pending))
        pending = []

    new_page()

    def cur():
        return pages[-1]

    def fl(line):
        return sum(len(fn_lines[m]) for m in line["fn"])

    def split_point(used, L, j, ln):
        parts = [(m, fn_lines[m]) for m in ln["fn"]]
        total = sum(len(p[1]) for p in parts)
        c = -1
        for t in range(total):
            if used + (j + 1) + block_rows(L + t) <= PAGE_ROWS:
                c = t
            else:
                break
        if c < 0:
            return None
        start = 0
        for pi, (m, lines) in enumerate(parts):
            if start <= c < start + len(lines):
                a = c - start
                b = len(lines) - a
                if b == 1:
                    a -= 1
                    b = 2
                if a < 3 or b < 2:
                    return None
                keep = parts[:pi] + [(m, lines[:a])]
                carry = [(m, lines[a:])] + parts[pi + 1:]
                return keep, carry
            start += len(lines)
        return None

    def fit_count(used, L, lines, allow_split):
        k = 0
        for j, ln in enumerate(lines):
            L2 = L + fl(ln)
            if used + (j + 1) + block_rows(L2) <= PAGE_ROWS:
                L = L2
                k += 1
                continue
            if allow_split:
                sp = split_point(used, L, j, ln)
                if sp:
                    return k + 1, sp
            break
        return k, None

    def place_lines(lines, dropcap, first_chunk, pad, split):
        nonlocal pending
        pg = cur()
        for j, ln in enumerate(lines):
            if dropcap and first_chunk and j == 0:
                pg.entries.append({"k": "cap", "pg": pg.number, "y": pg.used * ROW, "x": 0,
                                   "t": dropcap, "r": DC_ROWS})
            pg.entries.append({"k": "body", "pg": pg.number, "y": (pg.used + j) * ROW, "x": ln["x"],
                               "t": ln["t"], "g": ln["g"]})
            if split and j == len(lines) - 1:
                keep, carry = split
                pg.parts += keep
                pending = carry
                pg.closed = True
            else:
                pg.parts += [(m, fn_lines[m]) for m in ln["fn"]]
        pg.used += len(lines) + pad

    def min_unit_fits(idx, used, L):
        if idx >= len(blocks):
            return True
        b = blocks[idx]
        if b["k"] in ("h1", "h2"):
            lv = 1 if b["k"] == "h1" else 2
            before = HEAD_BEFORE[lv] if (used > 0 and not (idx > 0 and blocks[idx - 1]["k"] != "p")) else 0
            u2 = used + before + HEAD_ROWS[lv] + HEAD_AFTER[lv]
            if u2 + block_rows(L) > PAGE_ROWS:
                return False
            return min_unit_fits(idx + 1, u2, L)
        lines = b["lines"]
        n = len(lines)
        m = n if n < 6 else 3
        rows = max(m, DC_ROWS) if b["dropcap"] and n < 3 else m
        L2 = L + sum(fl(ln) for ln in lines[:m])
        return used + rows + block_rows(L2) <= PAGE_ROWS

    prev = None
    for b in blocks:
        if b["k"] == "p":
            words = []
            for tok, mark in b["toks"]:
                tok = REF_RE.sub(lambda mm: roman(table[mm.group(1)]) if mm.group(1) in table else "?", tok)
                words.append(Word(tok.replace("~", "\u00a0"), mark))
            cap = None
            if b["dropcap"]:
                first = words[0]
                cap = first.text[0]
                words = [Word(first.text[1:], first.mark)] + words[1:]
            b["cap"] = cap
            indent_first = prev == "p" and not b["dropcap"]
            key = (tuple((w.text, w.mark) for w in words), indent_first, b["dropcap"])
            if key not in cache:
                cache[key] = break_paragraph(words, indent_first, b["dropcap"])
            b["lines"] = cache[key]
        prev = b["k"] if b["k"] == "p" else "h"

    for idx, b in enumerate(blocks):
        if cur().closed:
            new_page()
        pg = cur()
        if b["k"] in ("h1", "h2"):
            lv = 1 if b["k"] == "h1" else 2
            before = HEAD_BEFORE[lv] if (pg.used > 0 and not (idx > 0 and blocks[idx - 1]["k"] != "p")) else 0
            if pg.used > 0 and not min_unit_fits(idx, pg.used, pg.fnlines):
                new_page()
                pg = cur()
                before = 0
            pg.used += before
            pg.entries.append({"k": b["k"], "pg": pg.number, "y": pg.used * ROW, "x": 0, "t": b["text"]})
            pg.used += HEAD_ROWS[lv] + HEAD_AFTER[lv]
            continue
        remaining = b["lines"]
        first_chunk = True
        while remaining:
            pg = cur()
            n = len(remaining)
            pad = 0
            if b["dropcap"] and first_chunk and n < DC_ROWS:
                pad = DC_ROWS - n
            k, sp = fit_count(pg.used, pg.fnlines, remaining, not pad)
            kfit = k
            if pad and k == n:
                if pg.used + n + pad + block_rows(pg.fnlines + sum(fl(x) for x in remaining)) > PAGE_ROWS:
                    k = 0
            if k < n:
                if n < 6:
                    k = 0
                else:
                    if b["dropcap"] and first_chunk and k < DC_ROWS:
                        k = 0
                    if k < 2:
                        k = 0
                    if n - k < 3:
                        k = n - 3
                        if k < 2:
                            k = 0
                        if b["dropcap"] and first_chunk and k < DC_ROWS:
                            k = 0
                    if k > 0 and remaining[k - 1]["s"]:
                        k -= 1
                        if k < 2:
                            k = 0
                        if b["dropcap"] and first_chunk and k < DC_ROWS:
                            k = 0
                if k == 0 and pg.used == 0:
                    k = max(1, kfit)
            if k == 0:
                new_page()
                continue
            if k != kfit:
                sp = None
            if first_chunk and b["anchor"] and b["anchor"] not in anchors:
                anchors[b["anchor"]] = pg.number
            place_lines(remaining[:k], b["cap"], first_chunk, pad if k == n else 0, sp)
            remaining = remaining[k:]
            first_chunk = False
            if remaining:
                new_page()
    if pending:
        new_page()
    out = []
    for pg in pages:
        ents = list(pg.entries)
        L = pg.fnlines
        if L:
            rows = block_rows(L)
            top = (PAGE_ROWS - rows) * ROW
            ents.append({"k": "rule", "pg": pg.number, "y": top, "x": 0})
            i = 0
            for m, lines in pg.parts:
                for t in lines:
                    ents.append({"k": "fn", "pg": pg.number, "y": top + FN_RULE_PT + FN_LINE_PT * i, "x": 0, "t": t})
                    i += 1
        out.append(ents)
    return {"pages": out}, anchors


def typeset(text):
    blocks, footnotes = parse(text)
    fn_lines = {n: break_footnote("%d." % n, t) for n, t in footnotes.items()}
    table = {}
    for b in blocks:
        if b["k"] == "p" and b["anchor"] and b["anchor"] not in table:
            table[b["anchor"]] = START_PAGE
    cache = {}
    passes = 0
    while True:
        result, anchors = layout(blocks, fn_lines, table, cache)
        passes += 1
        new = {l: anchors[l] for l in table}
        if new == table or passes >= MAX_PASSES:
            break
        table = new
    return result


def main():
    if len(sys.argv) != 2:
        print("usage: folio.py document.fol", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        print(json.dumps(typeset(f.read()), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
