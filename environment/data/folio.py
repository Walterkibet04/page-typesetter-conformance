#!/usr/bin/env python3
"""folio: a small page typesetter. Reads a .fol document, writes the laid-out pages as JSON.

First draft: it understands the file format and produces the output format, but its
layout rules are placeholders (greedy line filling, no hyphenation, simple pagination).
"""
import json
import re
import sys

MEASURE = 360
ROW = 12
PAGE_ROWS = 36
INDENT = 24
DC_W = 30
DC_ROWS = 3
NAT_SPACE = 4
MARK_W = 3
NARROW = set("ilItfj!.,;:'|()")
WIDE = set("mwMW")


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


def roman(n):
    out = ""
    for v, sym in ((10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out += sym
            n -= v
    return out


def parse(text):
    blocks, footnotes, counter = [], {}, 0
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
        m = re.match(r"\{#([a-z0-9]+)\}\s*", raw)
        if m:
            anchor, raw = m.group(1), raw[m.end():]
        dropcap = raw.startswith("^")
        if dropcap:
            raw = raw[1:]
        body = " ".join(raw.split("\n"))
        words = []
        i = 0
        cur = ""
        while i < len(body):
            if body.startswith("[[", i):
                e = body.index("]]", i)
                counter += 1
                footnotes[counter] = body[i + 2:e].strip()
                words.append((cur, counter))
                cur = ""
                i = e + 2
                while i < len(body) and not body[i].isspace():
                    i += 1
            elif body[i].isspace():
                if cur:
                    words.append((cur, None))
                cur = ""
                i += 1
            else:
                cur += body[i]
                i += 1
        if cur:
            words.append((cur, None))
        blocks.append({"k": "p", "words": words, "dropcap": dropcap, "anchor": anchor})
    return blocks, footnotes


def break_paragraph(words, indent_first, dropcap):
    """Greedy: put as many words on a line as fit at natural spacing."""
    lines = []
    cur, w, marks = [], 0, []
    for text, mark in words:
        ww = width(text) + (MARK_W if mark else 0)
        ind = INDENT if (not lines and indent_first) else (DC_W if dropcap and len(lines) < DC_ROWS else 0)
        if cur and w + NAT_SPACE + ww > MEASURE - ind:
            lines.append((cur, marks, ind, w))
            cur, w, marks = [], 0, []
            ind = DC_W if dropcap and len(lines) < DC_ROWS else 0
        w += ww + (NAT_SPACE if cur else 0)
        cur.append(text + ("^%d" % mark if mark else ""))
        if mark:
            marks.append(mark)
    if cur:
        ind = INDENT if (not lines and indent_first) else (DC_W if dropcap and len(lines) < DC_ROWS else 0)
        lines.append((cur, marks, ind, w))
    out = []
    for j, (toks, marks, ind, w) in enumerate(lines):
        g = len(toks) - 1
        last = j == len(lines) - 1
        slack = MEASURE - ind - (w - NAT_SPACE * g)
        if g == 0:
            gaps = []
        elif last:
            gaps = [NAT_SPACE] * g
        else:
            gaps = [slack // g] * g
        out.append({"t": " ".join(toks), "x": ind, "g": gaps, "fn": marks})
    return out


def break_footnote(label, text):
    lines, cur, s = [], [], 0
    for w in [label] + text.split():
        sw = width(w) * 3 // 4
        if cur and s + sw + 3 * len(cur) > MEASURE:
            lines.append(" ".join(cur))
            cur, s = [], 0
        cur.append(w)
        s += sw
    if cur:
        lines.append(" ".join(cur))
    return lines


def block_rows(L):
    return 0 if L == 0 else -(-(18 + 9 * L) // ROW)


def typeset(text):
    blocks, footnotes = parse(text)
    fn_lines = {n: break_footnote("%d." % n, t) for n, t in footnotes.items()}
    pages = [[]]
    used = [0]
    notes = [[]]

    def new_page():
        pages.append([])
        used.append(0)
        notes.append([])

    prev = None
    for b in blocks:
        if b["k"] in ("h1", "h2"):
            rows = 2 if b["k"] == "h1" else 1
            if used[-1] + rows + 1 + block_rows(sum(map(len, notes[-1]))) > PAGE_ROWS:
                new_page()
            pages[-1].append({"k": b["k"], "pg": len(pages), "y": used[-1] * ROW, "x": 0, "t": b["text"]})
            used[-1] += rows + 1
            prev = "h"
            continue
        words = [(re.sub(r"\{@[a-z0-9]+\}", "i", t).replace("~", "\u00a0"), m) for t, m in b["words"]]
        cap = None
        if b["dropcap"]:
            cap = words[0][0][0]
            words[0] = (words[0][0][1:], words[0][1])
        lines = break_paragraph(words, prev == "p" and not b["dropcap"], b["dropcap"])
        prev = "p"
        for j, ln in enumerate(lines):
            need = sum(len(fn_lines[m]) for m in ln["fn"])
            have = sum(map(len, notes[-1]))
            if used[-1] + 1 + block_rows(have + need) > PAGE_ROWS:
                new_page()
            pg = pages[-1]
            if cap and j == 0:
                pg.append({"k": "cap", "pg": len(pages), "y": used[-1] * ROW, "x": 0, "t": cap, "r": DC_ROWS})
            pg.append({"k": "body", "pg": len(pages), "y": used[-1] * ROW, "x": ln["x"], "t": ln["t"], "g": ln["g"]})
            used[-1] += 1
            for m in ln["fn"]:
                notes[-1].append(fn_lines[m])
    out = []
    for pi, ents in enumerate(pages):
        ents = list(ents)
        flat = [t for n in notes[pi] for t in n]
        if flat:
            top = (PAGE_ROWS - block_rows(len(flat))) * ROW
            ents.append({"k": "rule", "pg": pi + 1, "y": top, "x": 0})
            for i, t in enumerate(flat):
                ents.append({"k": "fn", "pg": pi + 1, "y": top + 18 + 9 * i, "x": 0, "t": t})
        out.append(ents)
    return {"pages": out}


def main():
    if len(sys.argv) != 2:
        print("usage: folio.py document.fol", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        print(json.dumps(typeset(f.read()), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
