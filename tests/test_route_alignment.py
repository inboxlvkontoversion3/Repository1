from __future__ import annotations

from playwright.sync_api import Page, sync_playwright


HTML_BAD = """
<html>
  <body style="font: 16px sans-serif; margin: 30px;">
    <div class="row">
      <span class="pos">9.</span>
      <span class="label">Stopp 9</span>
      <span class="date">28.09.2026</span>
      <span class="qty">600l</span>
      <span class="rest">12345 Musterstadt | Hauptstraße 1</span>
    </div>
    <div class="row">
      <span class="pos">10.</span>
      <span class="label">Stopp 10</span>
      <span class="date">25.09.2026</span>
      <span class="qty">30l</span>
      <span class="rest">54321 Beispielstadt | Nebenstraße 2</span>
    </div>
    <div class="row">
      <span class="pos">11.</span>
      <span class="label">Stopp 11</span>
      <span class="date">28.09.2026</span>
      <span class="qty">40l</span>
      <span class="rest">67890 Zielort | Parkstraße 3</span>
    </div>
  </body>
</html>
"""

HTML_GOOD = """
<html>
  <body style="font: 16px sans-serif; margin: 30px;">
    <style>
      .rows { display: flex; flex-direction: column; gap: 0.1rem; }
      .row {
        display: grid;
        grid-template-columns: 2.5rem 9rem 0.8rem 9rem 0.8rem 5.4rem 0.8rem minmax(0, 1fr);
        align-items: center;
        column-gap: 0.35rem;
        white-space: nowrap;
        line-height: 1.5;
      }
      .row .pos, .row .label, .row .date, .row .qty, .row .rest { overflow: hidden; text-overflow: ellipsis; }
      .row .pos { font-weight: 700; }
      .row .label { font-weight: 700; }
      .row .sep { color: #666; }
    </style>
    <div class="rows">
      <div class="row">
        <span class="pos">9.</span>
        <span class="label">Stopp 9</span><span class="sep">|</span>
        <span class="date">28.09.2026</span><span class="sep">|</span>
        <span class="qty">600l</span><span class="sep">|</span>
        <span class="rest">12345 Musterstadt | Hauptstraße 1</span>
      </div>
      <div class="row">
        <span class="pos">10.</span>
        <span class="label">Stopp 10</span><span class="sep">|</span>
        <span class="date">25.09.2026</span><span class="sep">|</span>
        <span class="qty">30l</span><span class="sep">|</span>
        <span class="rest">54321 Beispielstadt | Nebenstraße 2</span>
      </div>
      <div class="row">
        <span class="pos">11.</span>
        <span class="label">Stopp 11</span><span class="sep">|</span>
        <span class="date">28.09.2026</span><span class="sep">|</span>
        <span class="qty">40l</span><span class="sep">|</span>
        <span class="rest">67890 Zielort | Parkstraße 3</span>
      </div>
    </div>
  </body>
</html>
"""


def _measure_positions(page: Page, html: str) -> dict[str, list[float]]:
    page.set_content(html)
    page.wait_for_timeout(200)
    return page.evaluate("""
        () => {
          const rows = Array.from(document.querySelectorAll('.row'));
          return rows.map((row) => {
            const date = row.querySelector('.date');
            const qty = row.querySelector('.qty');
            const pos = row.querySelector('.pos');
            return {
              dateX: date.getBoundingClientRect().x,
              qtyX: qty.getBoundingClientRect().x,
              posX: pos.getBoundingClientRect().x,
            };
          });
        }
    """)


def test_bad_layout_has_drifting_columns() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 800})
        bad = _measure_positions(page, HTML_BAD)
        browser.close()

    date_xs = [item["dateX"] for item in bad]
    qty_xs = [item["qtyX"] for item in bad]
    assert max(date_xs) - min(date_xs) > 10
    assert max(qty_xs) - min(qty_xs) > 10


def test_fixed_grid_keeps_columns_aligned() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 800})
        good = _measure_positions(page, HTML_GOOD)
        browser.close()

    date_xs = [item["dateX"] for item in good]
    qty_xs = [item["qtyX"] for item in good]
    assert max(date_xs) - min(date_xs) < 1.5
    assert max(qty_xs) - min(qty_xs) < 1.5
