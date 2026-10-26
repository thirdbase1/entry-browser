"""entrybrowser.html — HTML5 tokenizer + tree builder.

Spec-conformant subset of the WHATWG tokenizer: DOCTYPE, start/end tags,
attributes (single/double/unquoted), text, comments, script/style RAWTEXT,
void elements, implied html/head/body, entity decoding for the common set.
"""
from __future__ import annotations
import html as _html
import re

VOID = {"area","base","br","col","embed","hr","img","input","link","meta",
        "param","source","track","wbr"}
RAWTEXT = {"script","style","xmp","iframe","noembed","noframes","noscript"}
# auto-closing: <p> closes an open <p>; <li> closes open <li>; block-in-p closes p
_AUTOCLOSE = {"p": {"p"},
              "li": {"li"},
              "dt": {"dt","dd"}, "dd": {"dt","dd"},
              "tr": {"tr","td","th"}, "td": {"td","th"}, "th": {"td","th"},
              "option": {"option"}}
_BLOCKISH = {"div","p","h1","h2","h3","h4","h5","h6","ul","ol","table","blockquote",
             "pre","section","article","header","footer","nav","aside","main","hr",
             "form","figure","dl","address","li","tr","td","th"}

class Node:
    __slots__ = ("tag","attrs","children","parent","text","_mutated")
    def __init__(self, tag: str, attrs: dict | None = None, parent: "Node | None" = None,
                 text: str = ""):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[Node] = []
        self.parent = parent
        self.text = text
        self._mutated = False
    def append(self, n: "Node"):
        n.parent = self
        self.children.append(n)
    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()
    def query_all(self, tag: str):
        return [n for n in self.walk() if n.tag == tag]
    def attr(self, k, default=None):
        return self.attrs.get(k, default)
    def text_content(self) -> str:
        if self.tag == "#text": return self.text
        return "".join(c.text_content() for c in self.children)
    def __repr__(self):
        return f"<{self.tag}{' ' + repr(self.attrs) if self.attrs else ''}>"

_ENTITIES = {"&amp;":"&","&lt;":"<","&gt;":">","&quot;":'"',"&#39;":"'",
             "&apos;":"'","&nbsp;":" ","&copy;":"\u00a9","&mdash;":"\u2014","&ndash;":"\u2013",
             "&hellip;":"\u2026","&times;":"\u00d7","&divide;":"\u00f7","&rsquo;":"\u2019","&lsquo;":"\u2018",
             "&ldquo;":"\u201c","&rdquo;":"\u201d","&reg;":"\u00ae","&trade;":"\u2122","&euro;":"\u20ac",
             "&pound;":"\u00a3","&deg;":"\u00b0","&middot;":"\u00b7","&laquo;":"\u00ab","&raquo;":"\u00bb"}
_ENT_RE = re.compile("|".join(_ENTITIES))
def decode_entities(s: str) -> str:
    s = _ENT_RE.sub(lambda m: _ENTITIES[m.group(0)], s)
    if "&" in s:
        s = _html.unescape(s)
    return s

_TOKEN_RE = re.compile(
    r"<!--.*?-->"
    r"|<!DOCTYPE[^>]*>"
    r"|<!\[CDATA\[.*?\]\]>"
    r"|</\s*([a-zA-Z][^\s>]*)\s*>"
    r"|<([a-zA-Z][^\s/>]*)"
    r"|(>)",
    re.DOTALL | re.IGNORECASE,
)
_ATTR_RE = re.compile(
    r"([^\s=/>]+)"
    r"(?:\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]*))?",
)
_WS = " \t\n\r\f"

def parse(html: str) -> Node:
    """Parse HTML into a #document tree with implied html/head/body."""
    doc = Node("#document")
    html_n = Node("html"); doc.append(html_n)
    head = Node("head"); html_n.append(head)
    body = Node("body"); html_n.append(body)

    stack = [html_n, head]   # open elements; target = stack[-1]
    def target(): return stack[-1]
    def in_body(): return any(n is body for n in stack)
    def ensure_body():
        if not in_body():
            stack.append(body)
    def pop_through(tag):
        # pop until (and including) the nearest matching open tag
        for k in range(len(stack)-1, 1, -1):   # never pop html/head
            if stack[k].tag == tag:
                del stack[k:]
                return True
        return False

    i, n = 0, len(html)
    while i < n:
        if html[i] != "<":
            j = html.find("<", i)
            j = n if j == -1 else j
            chunk = html[i:j]
            if stack[-1].tag == "head" and chunk.strip():
                ensure_body()
            text = re.sub(r"\s+", " ", chunk)
            if text:
                # keep single-space runs (they separate inline elements); drop leading ws
                if text.strip() or (target().children and target().children[-1].tag == "#text"):
                    target().append(Node("#text", text=decode_entities(text)))
                elif text.strip() == "" and target().children:
                    target().append(Node("#text", text=" "))
            i = j
            continue
        m = _TOKEN_RE.match(html, i)
        if not m:
            ensure_body()
            target().append(Node("#text", text="<"))
            i += 1
            continue
        tok = m.group(0)
        if tok.startswith("<!--") or tok.startswith("<![CDATA[") or tok.upper().startswith("<!DOCTYPE"):
            i = m.end(); continue
        end_tag = m.group(1)
        if end_tag is not None:
            pop_through(end_tag.lower())
            i = m.end(); continue
        start_name = m.group(2).lower() if m.group(2) else ""
        if not start_name:
            i = m.end(); continue
        # parse attributes
        j = m.end()
        attrs = {}
        while j < n:
            while j < n and html[j] in _WS: j += 1
            if j >= n or html[j] == ">":
                j += 1; break
            am = _ATTR_RE.match(html, j)
            if not am:
                j += 1; continue
            name = am.group(1).lower()
            val = am.group(2)
            if val is None: val = ""
            elif val[:1] in "\"'": val = val[1:-1]
            attrs[name] = decode_entities(val)
            j = am.end()
        i = j
        # rawtext: swallow to matching end tag
        if start_name in RAWTEXT:
            close = re.compile(rf"</{start_name}\s*>", re.IGNORECASE).search(html, i)
            content = html[i:close.start()] if close else html[i:]
            i = close.end() if close else n
            node = Node(start_name, attrs, text=content)
            if start_name in ("script","style","title","meta","link","base") and not in_body():
                head.append(node)
            else:
                ensure_body(); target().append(node)
            continue
        # autoclose siblings
        closes = _AUTOCLOSE.get(start_name)
        if closes and stack[-1].tag in closes:
            stack.pop()
        # a block-level start tag closes an open <p> (HTML5 implied end tag)
        if start_name in _BLOCKISH:
            for k in range(len(stack)-1, 1, -1):
                if stack[k].tag == "p":
                    del stack[k:]
                    break
        if start_name in ("html","head"):
            continue
        if start_name == "body":
            # move to body if not already
            while stack[-1] is not html_n and stack[-1] is not body:
                stack.pop()
            if stack[-1] is not body:
                stack.append(body)
            continue
        if start_name in VOID:
            node = Node(start_name, attrs)
            if start_name in ("title","meta","link","base") and not in_body():
                head.append(node)
            else:
                ensure_body(); target().append(node)
            continue
        _HEADONLY = ("title","meta","link","base")
        if start_name in _HEADONLY and not in_body():
            node = Node(start_name, attrs)
            head.append(node)
            stack.append(node)   # stays open; </title> pops via pop_through
            continue
        ensure_body()
        node = Node(start_name, attrs)
        target().append(node)
        stack.append(node)
    return doc

def parse_title(doc: Node) -> str:
    for t in doc.query_all("title"):
        return t.text_content().strip()
    return ""
