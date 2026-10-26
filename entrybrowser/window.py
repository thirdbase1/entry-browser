"""entrybrowser.window — interactive window mode (tkinter GUI shell).

Loads a URL/file into a Tab, renders to PNG, shows it in a scrollable window.
Clicks map pixel coords -> nearest clickable element (a/button/[onclick]/input)
and re-render. Address bar + Back/Forward/Reload + status bar.
"""
from __future__ import annotations


def _hit_test(root_box, x: float, y: float):
    """Return (kind, target) for the topmost clickable thing at (x, y).
    kind: 'box' (target=Box) or 'span' (target=Node). None if nothing clickable."""
    best = None  # (priority, kind, target)

    def clickable_node(nd):
        return nd is not None and (
            nd.tag in ("a", "button", "input", "select", "textarea", "label")
            or nd.attrs.get("onclick"))

    def walk(b):
        nonlocal best
        nd = b.node
        if clickable_node(nd) and b.x <= x < b.x + b.w and b.y <= y < b.y + b.h:
            score = (0, b.w * b.h)  # widget boxes win over spans (smaller area first)
            if best is None or score < best[0]:
                best = (score, "box", b)
        for sp in getattr(b, "spans", None) or []:
            # span: (text, tx, baseline, font_path, size, color, underline, sup, node)
            if len(sp) >= 9 and clickable_node(sp[8]):
                size = sp[4]
                tx, baseline = sp[1], sp[2]
                from PIL import ImageFont
                try:
                    font = ImageFont.truetype(sp[3], int(round(size)))
                    w = font.getlength(sp[0])
                except Exception:
                    w = len(sp[0]) * size * 0.6
                if tx <= x < tx + w and baseline - size <= y <= baseline + size * 0.3:
                    score = (0, w * size)
                    if best is None or score < best[0]:
                        best = (score, "span", sp[8])
        for c in b.children:
            walk(c)

    walk(root_box)
    return best


def _selector_for(box) -> str | None:
    """Build a CSS selector-ish string Tab.click can resolve for a box."""
    nd = box.node
    if nd is None:
        return None
    if nd.attrs.get("id"):
        return "#" + nd.attrs["id"]
    cls = (nd.attrs.get("class") or "").split()
    if cls:
        return "." + cls[0]
    return nd.tag


def run(url: str, width: int = 1100, height: int = 800):
    """Open url (or file path) in an interactive window. Blocks until closed."""
    import tkinter as tk
    from PIL import Image, ImageTk
    from . import Tab

    root = tk.Tk()
    root.title("Entry Browser")
    state = {"tab": None, "photo": None}

    bar = tk.Frame(root, bg="#2b2b2b")
    bar.pack(fill=tk.X)
    back_btn = tk.Button(bar, text="◀", width=3, command=lambda: nav("back"))
    back_btn.pack(side=tk.LEFT, padx=2, pady=3)
    fwd_btn = tk.Button(bar, text="▶", width=3, command=lambda: nav("forward"))
    fwd_btn.pack(side=tk.LEFT, padx=2)
    reload_btn = tk.Button(bar, text="⟳", width=3, command=lambda: nav("reload"))
    reload_btn.pack(side=tk.LEFT, padx=2)
    urlvar = tk.StringVar(value=url)
    url_entry = tk.Entry(bar, textvariable=urlvar, width=90)
    url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6, pady=3)
    url_entry.bind("<Return>", lambda e: nav(urlvar.get()))
    go_btn = tk.Button(bar, text="Go", command=lambda: nav(urlvar.get()))
    go_btn.pack(side=tk.LEFT, padx=2)
    status = tk.Label(root, text="Ready", anchor="w", bg="#1e1e1e", fg="#cccccc")
    canvas = tk.Canvas(root, width=width, height=height, bg="white", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)
    status.pack(fill=tk.X)

    def load(target: str):
        t = Tab(viewport_w=width)
        if target.startswith("http://") or target.startswith("https://"):
            t.goto(target)
        else:
            import os
            if os.path.exists(target):
                t.load(open(target).read(), is_url=False)
            else:
                status.config(text=f"Not found: {target}")
                return
        state["tab"] = t
        draw()
        status.config(text=f"{t.url or target}  ·  {t.stats().get('nodes', '?')} nodes  ·  "
                           f"{t.stats().get('load_ms', '?')} ms")

    def draw():
        t = state["tab"]
        if t is None:
            return
        from .render import content_height
        png = t.render_png("/tmp/eb-window.png", height=max(height, content_height(t.root_box)))
        img = Image.open(png).crop((0, 0, width, height))
        state["photo"] = ImageTk.PhotoImage(img)
        canvas.delete("all")
        canvas.create_image(0, 0, image=state["photo"], anchor="nw")

    def nav(target: str):
        t = state["tab"]
        if target == "back":
            if t: t.back(); status.config(text=t.url); draw()
        elif target == "forward":
            if t: t.forward(); status.config(text=t.url); draw()
        elif target == "reload":
            if t and t.url: load(t.url)
        elif target:
            load(target)

    def on_click(e):
        t = state["tab"]
        if t is None:
            return
        hit = _hit_test(t.root_box, e.x, e.y)
        if hit is None:
            return
        _, kind, target = hit
        nd = target.node if kind == "box" else target
        if nd.tag == "a":
            href = nd.attrs.get("href") or ""
            if href:
                from urllib.parse import urljoin
                nav(urljoin(t.url or "", href))
                return
        sel = _selector_for(target) if kind == "box" else (
            "#" + nd.attrs["id"] if nd.attrs.get("id") else nd.tag)
        status.config(text=f"clicked {sel}")
        if sel:
            t.click(sel)
            draw()

    canvas.bind("<Button-1>", on_click)
    root.after(50, lambda: load(url))
    root.mainloop()
