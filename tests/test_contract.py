"""Contract tests: parse -> css -> layout -> render on local fixtures."""
import os, sys, json, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from entrybrowser import Tab, Browser
from entrybrowser.html import parse, Node
from entrybrowser.css import Stylesheet, parse_color, parse_length

def _walk_box(b):
    yield b
    for c in b.children:
        yield from _walk_box(c)

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


def test_flex_row_and_gap():
    h = """<html><head><style>.f { display: flex; gap: 10px; }</style></head>
    <body><div class="f"><div>A</div><div>B</div><div>C</div></div></body></html>"""
    t = Tab(viewport_w=600).load(h, is_url=False)
    f = next(b for b in t.root_box.children if b.node and b.node.tag == "div")
    assert len(f.children) == 3
    xs = sorted(round(c.x) for c in f.children)
    assert xs[1] - xs[0] >= 10  # at least the gap; items shrink-to-fit

def test_flex_column():
    h = """<html><head><style>.f { display: flex; flex-direction: column; }</style></head>
    <body><div class="f"><div>A</div><div>B</div></div></body></html>"""
    t = Tab(viewport_w=600).load(h, is_url=False)
    f = next(b for b in t.root_box.children if b.node and b.node.tag == "div")
    assert len(f.children) == 2
    assert f.children[1].y > f.children[0].y

def test_grid_three_columns():
    h = """<html><head><style>.g { display: grid; grid-template-columns: repeat(3, 1fr); }</style></head>
    <body><div class="g"><div>1</div><div>2</div><div>3</div><div>4</div></div></body></html>"""
    t = Tab(viewport_w=800).load(h, is_url=False)
    g = next(b for b in t.root_box.children if b.node and b.node.tag == "div")
    assert len(g.children) == 4
    row1_x = sorted(round(c.x) for c in g.children[:3])
    assert len(set(row1_x)) == 3          # three distinct columns
    assert g.children[3].y >= g.children[0].y + g.children[0].h  # second row

def test_float_left_with_text_wrap():
    h = """<html><body>
    <img src="x.png" width="80" height="80" style="float: left">
    <p>This text should wrap around the floated image on the left side of the page here.</p>
    </body></html>"""
    t = Tab(viewport_w=400).load(h, is_url=False)
    spans = []
    def walk(b):
        spans.extend(b.spans)
        for c in b.children: walk(c)
    walk(t.root_box)
    assert spans

def test_absolute_position():
    h = """<html><head><style>.abs { position: absolute; top: 50px; left: 100px; }</style></head>
    <body><div class="abs">positioned</div></body></html>"""
    t = Tab(viewport_w=600).load(h, is_url=False)
    d = next(b for b in t.root_box.children if b.node and b.node.tag == "div")
    assert abs(d.x - 108) < 3 and abs(d.y - 58) < 3  # relative to body padding box (margin 8)

def test_js_click_reflow():
    h = """<html><body><button id="b" onclick="document.getElementById('o').textContent='pressed'">Go</button>
    <div id="o"></div></body></html>"""
    t = Tab(viewport_w=600).load(h, is_url=False)
    t.click("#b")
    assert "pressed" in t.text()

def test_js_addEventListener_and_timer():
    h = """<html><body><div id="d"></div><script>
    document.getElementById('d').addEventListener('click', function(){ this; });
    setTimeout(function(){ console.log('t'); }, 50);
    </script></body></html>"""
    t = Tab(viewport_w=600).load(h, is_url=False)
    assert t.js.run_timers() >= 1 and "t" in t.js_logs

def test_svg_data_uri_image():
    import base64
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><circle cx="20" cy="20" r="18" fill="red"/></svg>'
    h = f'<html><body><img src="data:image/svg+xml;base64,{base64.b64encode(svg).decode()}" width="40" height="40"></body></html>'
    t = Tab(viewport_w=400).load(h, is_url=False)
    imgs = []
    def walk(b):
        if b.node is not None and b.node.tag == "img": imgs.append(b)
        for c in b.children: walk(c)
    walk(t.root_box)
    assert imgs and imgs[0].img is not None

def test_box_sizing_border_box():
    h = """<html><head><style>.b { box-sizing: border-box; width: 100px; padding: 20px; }</style></head>
    <body><div class="b">x</div></body></html>"""
    t = Tab(viewport_w=400).load(h, is_url=False)
    d = next(b for b in t.root_box.children if b.node and b.node.tag == "div")
    assert abs(d.w - 100) < 2  # width includes padding

def test_overflow_hidden():
    h = """<html><head><style>.c { overflow: hidden; height: 20px; }</style></head>
    <body><div class="c"><p>line1</p><p>line2</p></div></body></html>"""
    t = Tab(viewport_w=400).load(h, is_url=False)
    d = next(b for b in t.root_box.children if b.node and b.node.tag == "div")
    assert d.h <= 21  # clipped


# ---------------- v0.4.0 ----------------

HTML_AREAS = """<html><head><style>
.page { display: grid; gap: 10px;
  grid-template: 'side main' 1fr 'side foot' 80px / 200px 1fr; }
.side { grid-area: side; } .main { grid-area: main; } .foot { grid-area: foot; }
</style></head><body><div class="page">
<div class="side">S</div><div class="main">M</div><div class="foot">F</div></div></body></html>"""

def test_grid_template_areas():
    t = Tab(viewport_w=800).load(HTML_AREAS, is_url=False)
    page = next(b for b in t.root_box.children if b.node and b.node.tag == "div")
    cells = {c.node.attrs["class"]: c for c in page.children}
    assert abs(cells["side"].x - cells["main"].x) > 150   # side col0 (200px), main col1
    assert abs(cells["side"].y - cells["foot"].y) > 20    # different rows
    assert cells["foot"].x > cells["side"].x + 150        # foot in col1

def test_paint_order_floats_then_positioned():
    h = """<html><head><style>
.f { float: left; width: 50px; height: 50px; background-color: #0f0; }
.p { position: absolute; top: 0; left: 60px; width: 50px; height: 50px;
     background-color: #00f; }
</style></head><body><div class="f"></div><div class="p"></div></body></html>"""
    t = Tab(viewport_w=400).load(h, is_url=False)
    png = t.render_png("/tmp/t-paint.png")
    import os
    assert os.path.exists(png)

def test_form_widgets_layout():
    h = """<html><body><form>
<input type="text" value="hello" size="10"><input type="checkbox" checked>
<button>Go</button><select><option>One</option><option selected>Two</option></select>
<textarea rows="2" cols="10">abc</textarea></form></body></html>"""
    t = Tab(viewport_w=600).load(h, is_url=False)
    tags = [b.node.tag for b in _walk_box(t.root_box) if getattr(b, "is_widget", False)]
    assert tags.count("input") == 2 and "button" in tags and "select" in tags and "textarea" in tags
    btn = next(b for b in _walk_box(t.root_box) if b.node.tag == "button")
    assert btn.w > 30   # sized to label "Go"

def test_form_widget_paint():
    h = """<html><body><input type="text" value="hello" size="10">
    <button>Go</button></body></html>"""
    t = Tab(viewport_w=400).load(h, is_url=False)
    png = t.render_png("/tmp/t-form.png")
    import os
    assert os.path.exists(png) and os.path.getsize(png) > 0

def test_js_value_checked_classlist():
    h = """<html><body><input id="i" value="a">
    <div id="d" class="x">t</div>
    <script>document.getElementById('i').value='b';
    document.getElementById('d').classList.add('y');</script></body></html>"""
    t = Tab(viewport_w=300).load(h, is_url=False)
    assert t.js.run("document.getElementById('i').value") == "b"
    assert str(t.js.run("document.getElementById('d').classList.contains('y')")) in ("True", "true")
    d = t.js._bridge._n("d")
    assert "y" in d.attrs["class"].split()

def test_event_bubbling():
    h = """<html><body><div id="outer" onclick="document.getElementById('o').textContent='hit'">
    <button id="inner">press</button></div><div id="o">idle</div></body></html>"""
    t = Tab(viewport_w=300).load(h, is_url=False)
    t.click("#inner")
    o = t.js._bridge._n("o")
    assert "".join(c.text or "" for c in o.children) == "hit"

def test_rowspan_colspan():
    h = """<html><body><table width=400>
    <tr><td rowspan="2">A</td><td>B1</td><td>C1</td></tr>
    <tr><td colspan="2">BC</td></tr></table></body></html>"""
    t = Tab(viewport_w=600).load(h, is_url=False)
    gbs = [b for b in t.root_box.children if b.node and b.node.tag == "table"]
    cells = [c for gb in gbs for c in gb.children]
    a_cell = next(c for c in cells if c.node.text_content() == "A")
    bc_cell = next(c for c in cells if c.node.text_content() == "BC")
    b1_cell = next(c for c in cells if c.node.text_content() == "B1")
    assert a_cell.h > b1_cell.h * 1.5       # rowspan spans both rows
    assert bc_cell.w > b1_cell.w * 1.5      # colspan spans two cols

def test_hover_pseudo_class():
    h = """<html><head><style>.b { background-color: #eee; }
    .b:hover { background-color: #33f; }</style></head>
    <body><button class="b" id="b1">Hi</button></body></html>"""
    t = Tab(viewport_w=300).load(h, is_url=False)
    def bg():
        for b in _walk_box(t.root_box):
            if b.node.attrs.get("id") == "b1":
                return b.bg
    bg1 = bg()
    t.set_hover("#b1")
    bg2 = bg()
    assert bg1 != bg2 and bg2 == (51, 51, 255, 255)

def test_first_child_pseudo():
    h = """<html><head><style>li:first-child { color: #f00; }</style></head>
    <body><ul><li>a</li><li>b</li></ul></body></html>"""
    t = Tab(viewport_w=300).load(h, is_url=False)
    lis = [b for b in _walk_box(t.root_box) if b.node.tag == "li"]
    c1 = lis[0].spans[0][5]
    c2 = lis[1].spans[0][5]
    assert c1 == (255, 0, 0, 255) and c2 != c1

def test_transform_translate_rotate_scale():
    h = """<html><head><style>
    #a { width: 50px; height: 50px; background-color: #f00; transform: translate(30px, 15px); }
    #b { width: 50px; height: 50px; background-color: #00f; transform: rotate(45deg); }
    #c { width: 50px; height: 50px; background-color: #0a0; transform: scale(1.5); }
    </style></head><body><div id="a"></div><div id="b"></div><div id="c"></div></body></html>"""
    t = Tab(viewport_w=400).load(h, is_url=False)
    trs = {b.node.attrs["id"]: b.transform for b in _walk_box(t.root_box)
           if b.node and b.node.attrs.get("id")}
    assert trs["a"][0] == 30.0 and trs["a"][1] == 15.0
    assert trs["b"][2] == 45.0
    assert trs["c"][3] == 1.5
    png = t.render_png("/tmp/t-xform.png")
    assert os.path.exists(png)

def test_letter_spacing():
    h = """<html><body><p style="letter-spacing: 4px">AB</p></body></html>"""
    t = Tab(viewport_w=300).load(h, is_url=False)
    spans = [s for b in _walk_box(t.root_box) for s in (b.spans or [])]
    assert spans and spans[0][9] == 4.0    # ls carried on span tuple

def test_animate_width():
    h = """<html><head><style>#box { width: 40px; height: 40px; }</style></head>
    <body><div id="box"></div></body></html>"""
    t = Tab(viewport_w=300).load(h, is_url=False)
    frames = t.animate("#box", "width", 200, duration_ms=300, steps=5)
    assert len(frames) == 5
    assert frames[-1]["width"] == 200.0
    assert frames[0]["width"] < frames[2]["width"] < 200.0   # eased monotonic

def test_history_back_forward(monkeypatch):
    import entrybrowser as eb
    calls = []
    def fake_fetch(url, timeout=15, use_cache=True):
        calls.append(url)
        return f"<html><body>{url}</body></html>", url, 200
    monkeypatch.setattr(eb.net, "fetch", fake_fetch)
    t = eb.Tab(viewport_w=300)
    t.history = ["http://x/1", "http://x/2", "http://x/3"]
    t._hist_pos = 2
    assert t.back() is True
    assert t._hist_pos == 1 and t.url == "http://x/2"
    assert t.forward() is True
    assert t._hist_pos == 2
    assert t.forward() is False

def test_browser_multitab():
    br = Browser(viewport_w=300)
    t1 = br.new_tab()
    t2 = br.new_tab()
    assert len(br.tabs) == 2 and br.current is t2
    br.close_tab(0)
    assert len(br.tabs) == 1 and br.current is t2

def test_cookie_jar_roundtrip():
    from entrybrowser.net import CookieJar
    class FakeResp:
        headers = {"Set-Cookie": "sid=abc123; Path=/"}
    jar = CookieJar()
    jar.store("http://example.com/x", FakeResp())
    assert "sid=abc123" in jar.header("http://example.com/y")
    class DelResp:
        headers = {"Set-Cookie": "sid=; Expires=Thu, 01 Jan 1970 00:00:00 GMT"}
    jar.store("http://example.com/x", DelResp())
    assert jar.header("http://example.com/y") == ""

def test_devtools_dump():
    h = """<html><body><div class="c"><p>hi</p></div></body></html>"""
    t = Tab(viewport_w=300).load(h, is_url=False)
    dump = t.devtools()
    assert "<div c>" in dump and "<p >" in dump and "nodes" in dump

def test_download_data_uri(tmp_path=None):
    h = "<html><body>x</body></html>"
    t = Tab(viewport_w=300).load(h, is_url=False)
    out = t.download("data:text/plain;base64,aGVsbG8=", "/tmp/t-dl.txt")
    assert open(out).read() == "hello"

def test_hit_test_span_link():
    from entrybrowser.window import _hit_test
    h = """<html><body><p><a href="https://example.com" id="lnk">A link</a></p></body></html>"""
    t = Tab(viewport_w=500).load(h, is_url=False)
    hit = _hit_test(t.root_box, 40, 36)
    assert hit is not None and hit[1] == "span" and hit[2].tag == "a"

def test_hit_test_button():
    from entrybrowser.window import _hit_test
    h = """<html><body><button class="bt">Press</button></body></html>"""
    t = Tab(viewport_w=500).load(h, is_url=False)
    btn = next(b for b in _walk_box(t.root_box) if b.node.tag == "button")
    hit = _hit_test(t.root_box, btn.x + btn.w/2, btn.y + btn.h/2)
    assert hit is not None and hit[1] == "box" and hit[2].node.tag == "button"

def test_grid_minmax():
    h = """<html><head><style>.g { display: grid; width: 400px;
    grid-template-columns: minmax(100px, 1fr) 100px; }</style></head>
    <body><div class="g"><div>A</div><div>B</div></div></body></html>"""
    t = Tab(viewport_w=600).load(h, is_url=False)
    g = next(b for b in t.root_box.children if b.node and b.node.tag == "div")
    kids = g.children
    assert kids[0].w >= 100 and abs((kids[0].w + kids[1].w) - 400) < 4
