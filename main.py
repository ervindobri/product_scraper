"""
Electronics Price Finder
Searches Hungarian and EU electronics stores in parallel and shows results in a sortable table.
"""

import threading
import webbrowser
import tkinter as tk
from tkinter import ttk

from scrapers import (SCRAPERS, SCRAPER_REGIONS, create_session,
                      extract_numeric_price, score_relevance, convert_eur_price)

# ---------------------------------------------------------------------------
# Colours & sizing constants
# ---------------------------------------------------------------------------
BG       = "#f0f2f5"
BG_CARD  = "#ffffff"
ACCENT   = "#1a73e8"
ACCENT_H = "#1557b0"
TEXT     = "#202124"
MUTED    = "#5f6368"
SUCCESS  = "#1e8e3e"
WARNING  = "#f29900"
DANGER   = "#d93025"
ROW_ALT  = "#f8f9fa"

FONT_FAMILY = "Segoe UI"

_REGION_OPTIONS = [
    "All stores",
    "Hungary (HU)",
    "Germany (DE)",
    "Italy (IT)",
    "International (EU)",
]


def _filter_scrapers(region_label: str) -> list:
    if region_label == "Hungary (HU)":
        return [(n, r, f) for n, r, f in SCRAPERS if r == "hu"]
    if region_label == "Germany (DE)":
        return [(n, r, f) for n, r, f in SCRAPERS if r == "de"]
    if region_label == "Italy (IT)":
        return [(n, r, f) for n, r, f in SCRAPERS if r == "it"]
    if region_label == "International (EU)":
        return [(n, r, f) for n, r, f in SCRAPERS if r != "hu"]
    return list(SCRAPERS)  # "All stores"


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Electronics Price Finder")
        self.geometry("1280x840")
        self.minsize(900, 660)
        self.configure(bg=BG)

        self._session = create_session()
        self._all_results: list[dict] = []
        self._pending = 0
        self._lock = threading.Lock()
        self._current_query = ""
        self._cache: dict[str, set[str]] = {}
        self._prev_urls: set[str] = set()
        self._cache_key = ""

        self._build_styles()
        self._build_ui()

    # ------------------------------------------------------------------
    # Style setup
    # ------------------------------------------------------------------
    def _build_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")

        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=BG_CARD, relief="flat")

        s.configure("TLabel", background=BG, foreground=TEXT,
                    font=(FONT_FAMILY, 10))
        s.configure("Title.TLabel", font=(FONT_FAMILY, 17, "bold"),
                    foreground=ACCENT, background=BG)
        s.configure("Sub.TLabel", font=(FONT_FAMILY, 9),
                    foreground=MUTED, background=BG)
        s.configure("Count.TLabel", font=(FONT_FAMILY, 10, "bold"),
                    foreground=ACCENT, background=BG)
        s.configure("Hint.TLabel", font=(FONT_FAMILY, 9, "italic"),
                    foreground=MUTED, background=BG)

        s.configure("Accent.TButton",
                    font=(FONT_FAMILY, 11, "bold"),
                    background=ACCENT, foreground="white",
                    borderwidth=0, focusthickness=0, padding=(22, 10))
        s.map("Accent.TButton",
              background=[("active", ACCENT_H), ("disabled", "#aecbfa")],
              foreground=[("disabled", "white")])

        s.configure("TEntry",
                    font=(FONT_FAMILY, 13),
                    fieldbackground="white",
                    borderwidth=1, relief="solid",
                    padding=(10, 8))

        s.configure("Treeview",
                    font=(FONT_FAMILY, 10),
                    background="white", fieldbackground="white",
                    rowheight=30, borderwidth=0)
        s.configure("Treeview.Heading",
                    font=(FONT_FAMILY, 10, "bold"),
                    background="#e8eaed", foreground=TEXT,
                    relief="flat", borderwidth=0)
        s.map("Treeview",
              background=[("selected", ACCENT)],
              foreground=[("selected", "white")])
        s.map("Treeview.Heading",
              background=[("active", "#d2e3fc")])

        s.configure("TScrollbar", background="#e0e0e0", troughcolor=BG,
                    borderwidth=0, arrowsize=14)

        s.configure("TRadiobutton",
                    background=BG, foreground=MUTED,
                    font=(FONT_FAMILY, 9))
        s.map("TRadiobutton",
              foreground=[("selected", ACCENT), ("active", ACCENT)])

        # Badge labels (status indicators per site)
        for key, bg_col, fg_col in [
            ("Wait",  "#e8eaed", MUTED),
            ("Load",  "#fef9c3", "#854d0e"),
            ("Done",  "#dcfce7", "#166534"),
            ("None",  "#f1f5f9", "#64748b"),
            ("Error", "#fee2e2", "#991b1b"),
            ("Skip",  "#e2e8f0", "#94a3b8"),   # not searched due to region filter
        ]:
            s.configure(f"Badge{key}.TLabel",
                        background=bg_col, foreground=fg_col,
                        font=(FONT_FAMILY, 8, "bold"),
                        padding=(7, 3), relief="flat")

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────
        hdr = ttk.Frame(self, padding=(24, 18, 24, 6))
        hdr.pack(fill="x")
        ttk.Label(hdr, text="Electronics Price Finder", style="Title.TLabel").pack(side="left")
        ttk.Label(hdr, text=f"  {len(SCRAPERS)} stores across Hungary and Europe",
                  style="Sub.TLabel").pack(side="left", pady=(6, 0))

        # ── Search bar ────────────────────────────────────────────────
        sf = ttk.Frame(self, padding=(24, 6, 24, 8))
        sf.pack(fill="x")

        self._query_var = tk.StringVar()
        self._entry = ttk.Entry(sf, textvariable=self._query_var,
                                font=(FONT_FAMILY, 13))
        self._entry.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=4)
        self._entry.insert(0, "e.g. MacBook Air M2 16GB")
        self._entry.configure(foreground=MUTED)
        self._entry.bind("<FocusIn>",  self._on_entry_focus_in)
        self._entry.bind("<FocusOut>", self._on_entry_focus_out)
        self._entry.bind("<Return>",   lambda _e: self._start_search())

        self._region_var = tk.StringVar(value="All stores")
        self._region_combo = ttk.Combobox(
            sf, textvariable=self._region_var,
            values=_REGION_OPTIONS, state="readonly", width=18,
        )
        self._region_combo.pack(side="left", padx=(0, 10), ipady=3)

        self._search_btn = ttk.Button(sf, text="Search",
                                      command=self._start_search,
                                      style="Accent.TButton")
        self._search_btn.pack(side="left")

        # ── Site-status badges ────────────────────────────────────────
        badge_frame = ttk.Frame(self, padding=(24, 2, 24, 4))
        badge_frame.pack(fill="x")

        self._badges: dict[str, ttk.Label] = {}
        hu_scrapers  = [(n, r, f) for n, r, f in SCRAPERS if r == "hu"]
        int_scrapers = [(n, r, f) for n, r, f in SCRAPERS if r != "hu"]

        # Hungarian stores — split across two rows
        hu_mid = (len(hu_scrapers) + 1) // 2
        ttk.Label(badge_frame, text="Hungary:", style="Sub.TLabel").pack(anchor="w")
        hu_row1 = ttk.Frame(badge_frame)
        hu_row1.pack(fill="x", pady=(1, 0))
        hu_row2 = ttk.Frame(badge_frame)
        hu_row2.pack(fill="x", pady=(3, 0))
        for i, (site_name, _, _) in enumerate(hu_scrapers):
            row = hu_row1 if i < hu_mid else hu_row2
            lbl = ttk.Label(row, text=f" {site_name} ", style="BadgeWait.TLabel")
            lbl.pack(side="left", padx=(0, 6))
            self._badges[site_name] = lbl

        # International stores — single row
        ttk.Label(badge_frame, text="International:", style="Sub.TLabel").pack(
            anchor="w", pady=(6, 1))
        int_row = ttk.Frame(badge_frame)
        int_row.pack(fill="x")
        for site_name, _, _ in int_scrapers:
            lbl = ttk.Label(int_row, text=f" {site_name} ", style="BadgeWait.TLabel")
            lbl.pack(side="left", padx=(0, 6))
            self._badges[site_name] = lbl

        # ── Toolbar (sort / count) ────────────────────────────────────
        tb = ttk.Frame(self, padding=(24, 4, 24, 4))
        tb.pack(fill="x")

        ttk.Label(tb, text="Sort by:", style="Sub.TLabel").pack(side="left")

        self._sort_var = tk.StringVar(value="relevance")
        for label, value in [
            ("Relevance ↓", "relevance"),
            ("Price ↑",     "price_asc"),
            ("Price ↓",     "price_desc"),
            ("Store",       "site"),
            ("Name",        "name"),
        ]:
            ttk.Radiobutton(tb, text=label, variable=self._sort_var,
                            value=value, command=self._refresh_table).pack(
                side="left", padx=5)

        self._count_var = tk.StringVar(value="")
        ttk.Label(tb, textvariable=self._count_var, style="Count.TLabel").pack(side="right")

        # ── Results table ─────────────────────────────────────────────
        tf = ttk.Frame(self, padding=(24, 0, 24, 0))
        tf.pack(fill="both", expand=True)
        tf.grid_rowconfigure(0, weight=1)
        tf.grid_columnconfigure(0, weight=1)

        cols = ("new", "site", "name", "price", "score", "url")
        self._tree = ttk.Treeview(tf, columns=cols, show="headings",
                                  selectmode="browse")

        self._tree.heading("new",   text="")
        self._tree.heading("site",  text="Store",   command=lambda: self._col_sort("site"))
        self._tree.heading("name",  text="Product", command=lambda: self._col_sort("name"))
        self._tree.heading("price", text="Price",   command=lambda: self._col_sort("price"))
        self._tree.heading("score", text="Match",   command=lambda: self._col_sort("score"))
        self._tree.heading("url",   text="URL")

        self._tree.column("new",   width=28,  minwidth=28,  stretch=False, anchor="center")
        self._tree.column("site",  width=140, minwidth=100, stretch=False)
        self._tree.column("name",  width=530, minwidth=280)
        self._tree.column("price", width=150, minwidth=110, stretch=False, anchor="e")
        self._tree.column("score", width=70,  minwidth=60,  stretch=False, anchor="center")
        self._tree.column("url",   width=0,   stretch=False)  # hidden; used for open

        self._tree.tag_configure("score_high",     background="#dcfce7")
        self._tree.tag_configure("score_mid",      background="#fef9c3")
        self._tree.tag_configure("score_low",      background="#fee2e2")
        self._tree.tag_configure("score_high_new", background="#bbf7d0", font=(FONT_FAMILY, 10, "bold"))
        self._tree.tag_configure("score_mid_new",  background="#fde68a", font=(FONT_FAMILY, 10, "bold"))
        self._tree.tag_configure("score_low_new",  background="#fca5a5", font=(FONT_FAMILY, 10, "bold"))

        vsb = ttk.Scrollbar(tf, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0,  column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self._tree.bind("<Double-1>",  self._open_url)
        self._tree.bind("<Return>",    self._open_url)

        # ── Status bar ────────────────────────────────────────────────
        sbar = ttk.Frame(self, padding=(24, 6))
        sbar.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(
            value="Enter a search query above and press Search or ↵")
        ttk.Label(sbar, textvariable=self._status_var,
                  style="Sub.TLabel").pack(side="left")
        ttk.Label(sbar, text="Double-click or ↵ to open in browser",
                  style="Hint.TLabel").pack(side="right")

    # ------------------------------------------------------------------
    # Entry placeholder behaviour
    # ------------------------------------------------------------------
    _PLACEHOLDER = "e.g. MacBook Air M2 16GB"

    def _on_entry_focus_in(self, _e):
        if self._entry.get() == self._PLACEHOLDER:
            self._entry.delete(0, "end")
            self._entry.configure(foreground=TEXT)

    def _on_entry_focus_out(self, _e):
        if not self._entry.get().strip():
            self._entry.insert(0, self._PLACEHOLDER)
            self._entry.configure(foreground=MUTED)

    # ------------------------------------------------------------------
    # Search orchestration
    # ------------------------------------------------------------------
    def _get_active_scrapers(self) -> list:
        return _filter_scrapers(self._region_var.get())

    def _start_search(self):
        query = self._query_var.get().strip()
        if not query or query == self._PLACEHOLDER:
            self._entry.focus_set()
            return

        self._current_query = query
        self._cache_key = query.lower().strip()
        self._prev_urls = self._cache.get(self._cache_key, set())

        active = self._get_active_scrapers()
        if not active:
            self._status_var.set("No stores match the selected region.")
            return

        active_names = {name for name, _, _ in active}

        # Reset state
        self._all_results.clear()
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._count_var.set("Searching…")
        self._search_btn.state(["disabled"])

        for site_name, lbl in self._badges.items():
            if site_name in active_names:
                lbl.configure(text=f" {site_name} ", style="BadgeLoad.TLabel")
            else:
                lbl.configure(text=f" {site_name} ", style="BadgeSkip.TLabel")

        self._status_var.set(
            f'Searching for "{query}" across {len(active)} stores…')
        self._pending = len(active)

        for site_name, _region, fn in active:
            threading.Thread(
                target=self._worker,
                args=(site_name, fn, query),
                daemon=True,
            ).start()

    def _worker(self, site_name: str, fn, query: str):
        try:
            results = fn(query, self._session)
            self.after(0, self._on_done, site_name, results, None)
        except Exception as exc:
            self.after(0, self._on_done, site_name, [], str(exc))

    def _on_done(self, site_name: str, results: list[dict], error: str | None):
        with self._lock:
            if error:
                self._badges[site_name].configure(
                    text=f" {site_name}: error ",
                    style="BadgeError.TLabel")
            else:
                n = len(results)
                suffix = f"{n} result{'s' if n != 1 else ''}"
                style = "BadgeDone.TLabel" if n > 0 else "BadgeNone.TLabel"
                self._badges[site_name].configure(
                    text=f" {site_name}: {suffix} ",
                    style=style)
                is_intl = SCRAPER_REGIONS.get(site_name, "hu") != "hu"
                for r in results:
                    if is_intl:
                        r["price"] = convert_eur_price(r["price"])
                    r["score"] = score_relevance(self._current_query, r["name"])
                    r["is_new"] = bool(self._prev_urls) and r.get("url", "") not in self._prev_urls
                self._all_results.extend(results)

            self._pending -= 1
            self._refresh_table()

            if self._pending == 0:
                self._cache[self._cache_key] = {r.get("url", "") for r in self._all_results}
                total = len(self._all_results)
                new_count = sum(1 for r in self._all_results if r.get("is_new"))
                count_text = f"{total} result{'s' if total != 1 else ''} found"
                if new_count:
                    count_text += f"  ·  {new_count} new"
                self._count_var.set(count_text)
                self._status_var.set(
                    f"Done — {total} result{'s' if total != 1 else ''} found.  "
                    "Double-click a row to open the product page.")
                self._search_btn.state(["!disabled"])

    # ------------------------------------------------------------------
    # Table rendering & sorting
    # ------------------------------------------------------------------
    def _refresh_table(self):
        for iid in self._tree.get_children():
            self._tree.delete(iid)

        rows = list(self._all_results)
        sort = self._sort_var.get()

        if sort == "relevance":
            rows.sort(
                key=lambda r: (r.get("is_new", False), r.get("score", 0), -extract_numeric_price(r["price"])),
                reverse=True,
            )
        elif sort == "price_asc":
            rows.sort(key=lambda r: extract_numeric_price(r["price"]))
        elif sort == "price_desc":
            rows.sort(key=lambda r: extract_numeric_price(r["price"]), reverse=True)
        elif sort == "site":
            rows.sort(key=lambda r: r["site"])
        elif sort == "name":
            rows.sort(key=lambda r: r["name"].lower())

        for r in rows:
            s = r.get("score", 0)
            is_new = r.get("is_new", False)
            if s >= 75:
                tag = "score_high_new" if is_new else "score_high"
            elif s >= 40:
                tag = "score_mid_new" if is_new else "score_mid"
            else:
                tag = "score_low_new" if is_new else "score_low"
            score_display = f"{s}%" if "score" in r else "–"
            new_dot = "●" if is_new else ""
            self._tree.insert("", "end",
                              values=(new_dot, r["site"], r["name"], r["price"], score_display, r["url"]),
                              tags=(tag,))

    def _col_sort(self, col: str):
        if col == "price":
            current = self._sort_var.get()
            self._sort_var.set("price_desc" if current == "price_asc" else "price_asc")
        elif col == "score":
            self._sort_var.set("relevance")
        else:
            self._sort_var.set(col)
        self._refresh_table()

    # ------------------------------------------------------------------
    # Open URL in browser
    # ------------------------------------------------------------------
    def _open_url(self, _event=None):
        sel = self._tree.selection()
        if sel:
            url = self._tree.item(sel[0], "values")[5]
            if url and url.startswith("http"):
                webbrowser.open(url)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app = App()
    app.mainloop()
