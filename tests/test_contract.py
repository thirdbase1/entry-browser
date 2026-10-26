"""Contract tests: parse -> css -> layout -> render on local fixtures."""
import os, sys, json, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from entrybrowser import Tab
from entrybrowser.html import parse, Node
from entrybrowser.css import Stylesheet, parse_color, parse_length

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "page.html")

def test_parse_basic():
    doc = parse("<html><head><title>T</title></head><body><p>hi</p></body></html>")
    assert doc.query_all("title")[0].text_content() == "T"
    body = doc.query_all("body")[0]
    assert [c.tag for c in body.children] == ["p"]
    assert body.children[0].text_content() == "hi"

def test_parse_unclosed():
    doc = parse("<p>one<p>two<div>x</div>")
    ps = doc.query_all("p")
    assert len(ps) == 2
    assert ps[0].text_content() == "one"
    assert ps[1].text_content() == "two"

def test_parse_void_and_attrs():
    doc = parse('<img src="a.png" width=40><input type=text disabled>')
    imgs = doc.query_all("img")
    assert imgs[0].attr("src") == "a.png" and imgs[0].attr("width") == "40"
    inp = doc.query_all("input")[0]
    assert inp.attr("type") == "text" and inp.attr("disabled") == ""

def test_parse_entities():
    doc = parse("<p>a &amp; b &lt;c&gt; &#39;d&#39;</p>")
    assert doc.query_all("p")[0].text_content() == "a & b <c> 'd'"

def test_parse_rawtext_style():
    doc = parse("<style>p { color: red; }</style><p>x</p>")
    assert doc.query_all("style") and doc.query_all("style")[0].text.strip().startswith("p")

def test_parse_comments():
    doc = parse("<!-- hidden --><p>shown</p>")
    assert doc.query_all("p")[0].text_content() == "shown"

def test_css_color_parsing():
    assert parse_color("#fff") == (255,255,255,255)
    assert parse_color("#ff8800") == (255,136,0,255)
    assert parse_color("rgb(1,2,3)") == (1,2,3,255)
    assert parse_color("rgba(1,2,3,0.5)") == (1,2,3,127)
    assert parse_color("navy") == (0,0,128,255)

def test_css_specificity():
    ss = Stylesheet.parse("p { color: red } .intro { color: blue } p.intro { color: green }")
    doc = parse('<body><p class="intro">x</p></body>')
    st = ss.computed(doc.query_all("p")[0], None, em=16)
    assert st["color"] == (0,128,0,255)

def test_css_inheritance():
    ss = Stylesheet.parse("body { color: #123456 } ")
    doc = parse("<body><p>x</p></body>")
    b = ss.computed(doc.query_all("body")[0], None, em=16)
    p = ss.computed(doc.query_all("p")[0], b, em=16)
    assert p["color"] == (0x12,0x34,0x56,255)

def test_css_page_overrides_ua():
    doc = parse("<body><h1 style='font-size: 50px'>x</h1></body>")
    tab = Tab(viewport_w=800).load(doc.tohtml() if hasattr(doc,'tohtml') else "<html><body><h1 style='font-size: 50px'>x</h1></body></html>", is_url=False)
    h1 = tab.doc.query_all("h1")[0]
    assert tab.layout.style_for(h1, {})["font-size"] == 50.0

def test_layout_blocks_and_wrapping():
    tab = Tab(viewport_w=400).load(FIX, is_url=False)
    body = tab.root_box
    assert len(body.children) >= 3
    # text wraps: long paragraph produces >1 line
    pboxes = [b for b in body.children if b.node and b.node.tag == "p"]
    assert pboxes and max(len(getattr(b, 'spans', [])) for b in pboxes) > 3

def test_layout_bg_and_color():
    tab = Tab(viewport_w=400).load(FIX, is_url=False)
    # fixture has a styled .box with background
    assert any(b.bg for b in tab.root_box.children), "expected at least one painted background"

def test_render_png():
    tab = Tab(viewport_w=400).load(FIX, is_url=False)
    out = "/tmp/eb-contract.png"
    tab.render_png(out)
    assert os.path.exists(out) and os.path.getsize(out) > 1000

def test_text_extraction():
    tab = Tab(viewport_w=400).load(FIX, is_url=False)
    txt = tab.text()
    assert "EntryBrowser" in txt and "wraps" in txt

def test_live_example_com():
    t = Tab(viewport_w=1024).load("https://example.com", is_url=True)
    assert t.status == 200
    assert "documentation examples" in t.text()

def test_cli_info():
    r = subprocess.run([sys.executable, "-m", "entrybrowser", "info", FIX],
                       capture_output=True, text=True,
                       cwd=os.path.join(os.path.dirname(__file__), ".."))
    assert r.returncode == 0 and "dom_nodes" in r.stdout


def test_js_textcontent_and_title():
    h = """<html><head><title>Old</title></head><body><p id="g">before</p>
    <script>document.getElementById('g').textContent = 'after';
    document.title = 'New';</script></body></html>"""
    t = Tab(viewport_w=600).load(h, is_url=False)
    assert "after" in t.text() and t.title == "New"

def test_js_innerhtml_and_console():
    h = """<html><body><div id="o"></div>
    <script>document.getElementById('o').innerHTML = '<b>deep</b>';
    console.log('ran');</script></body></html>"""
    t = Tab(viewport_w=600).load(h, is_url=False)
    assert "deep" in t.text() and "ran" in t.js_logs

def test_table_grid():
    h = "<html><body><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table></body></html>"
    t = Tab(viewport_w=600).load(h, is_url=False)
    tables = [b for b in t.root_box.children if b.node and b.node.tag == "table"]
    assert tables and len(tables[0].children) >= 4  # 2 rows x 2 cells

def test_media_query_desktop():
    h = """<html><head><style>
    @media (max-width: 768px) { .box { display: none; } }
    @media (min-width: 769px) { .box { background-color: #00ff00; } }
    </style></head><body><div class="box">x</div></body></html>"""
    t = Tab(viewport_w=1280).load(h, is_url=False)
    box = next(b for b in t.root_box.children if b.node and b.node.tag == "div")
    assert box.bg is not None and box.bg[1] == 255 and box.bg[0] == 0  # green

def test_media_query_mobile_hides():
    h = """<html><head><style>
    @media (max-width: 768px) { .box { display: none; } }
    </style></head><body><div class="box">x</div></body></html>"""
    t = Tab(viewport_w=400).load(h, is_url=False)
    box = next(b for b in t.root_box.children if b.node and b.node.tag == "div")
    assert box.h == 0 and not box.children

def test_image_data_uri():
    # 1x1 red PNG
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    import io as _io
    b64 = base64.b64encode(png).decode()
    h = f'<html><body><img src="data:image/png;base64,{b64}" width="10" height="10"></body></html>'
    t = Tab(viewport_w=400).load(h, is_url=False)
    imgs = []
    def walk(b):
        if b.node is not None and b.node.tag == "img": imgs.append(b)
        for c in b.children: walk(c)
    walk(t.root_box)
    assert imgs and imgs[0].img is not None

def test_link_span_color():
    h = '<html><body><p>see <a href="#">the link</a> here</p></body></html>'
    t = Tab(viewport_w=400).load(h, is_url=False)
    all_spans = []
    def walk(b):
        all_spans.extend(b.spans)
        for c in b.children: walk(c)
    walk(t.root_box)
    spans = [s for s in all_spans if s[0] and "link" in s[0]]
    assert spans and spans[0][5] == (0, 0, 238, 255) and spans[0][6]  # blue + underline
