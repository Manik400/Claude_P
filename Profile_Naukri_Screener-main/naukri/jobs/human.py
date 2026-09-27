"""Mouse and keyboard the way a hand does it.

Playwright's click() teleports the pointer onto the element and fill() drops
a whole value into a box in one event - two things no person does, and two
things a site's bot check can see. Everything here goes through the real
mouse and keyboard instead:

    click(page, locator)     scroll it into view, move the pointer there along
                             a curved path with uneven speed, settle, press,
                             release
    type_into(page, locator, text)
                             click the box, then type key by key with uneven
                             gaps (a long text - a cover letter - is pasted
                             after the first line, as a person would)
    hover(page, locator)     just the move (before a <select> or a file box)
    pause(page, lo, hi)      a moment between fields
    wander(page)             a small scroll, the way one looks over a page

The pointer's last position is kept per page, so each move starts where the
last one ended. Every step is a real mouse event on the page.
"""
from __future__ import annotations

import math
import random

_POS: dict = {}          # id(page) -> (x, y)


def _pos(page) -> tuple[float, float]:
    return _POS.get(id(page)) or (random.uniform(300, 700), random.uniform(200, 500))


def move(page, x: float, y: float) -> None:
    """Move the pointer to (x, y) along a slightly curved path, slower near the end."""
    sx, sy = _pos(page)
    dist = math.hypot(x - sx, y - sy)
    if dist < 2:
        return
    steps = max(10, min(45, int(dist / 18)))
    # two control points off the straight line: a curve, not a ruler
    bend = min(120.0, dist * 0.25)
    c1 = (sx + (x - sx) * 0.3 + random.uniform(-bend, bend), sy + (y - sy) * 0.3 + random.uniform(-bend, bend))
    c2 = (sx + (x - sx) * 0.7 + random.uniform(-bend, bend), sy + (y - sy) * 0.7 + random.uniform(-bend, bend))
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)                       # ease in, ease out
        u = 1 - t
        px = u ** 3 * sx + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * x
        py = u ** 3 * sy + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * y
        if i < steps:
            px += random.uniform(-1.5, 1.5)
            py += random.uniform(-1.5, 1.5)
        try:
            page.mouse.move(px, py)
        except Exception:
            return
        page.wait_for_timeout(random.uniform(5, 18) * (1.6 if i > steps * 0.8 else 1))
    _POS[id(page)] = (x, y)


def _target(page, locator):
    """(x, y) inside the element, off-centre like a real click. None when it has no box."""
    try:
        locator.scroll_into_view_if_needed(timeout=4000)
        page.wait_for_timeout(random.uniform(120, 350))
        box = locator.bounding_box(timeout=2000)
    except Exception:
        box = None
    if not box or box["width"] < 1 or box["height"] < 1:
        return None
    return (box["x"] + box["width"] * random.uniform(0.3, 0.7),
            box["y"] + box["height"] * random.uniform(0.32, 0.68))


def hover(page, locator) -> bool:
    at = _target(page, locator)
    if at is None:
        return False
    move(page, *at)
    page.wait_for_timeout(random.uniform(60, 200))
    return True


def click(page, locator, timeout: int = 6000) -> None:
    """A person's click: move there, settle, press, release. Falls back to Playwright's
    own click when the element has no box (a hidden file input, an ARIA widget)."""
    at = _target(page, locator)
    if at is None:
        locator.click(timeout=timeout)
        return
    move(page, *at)
    page.wait_for_timeout(random.uniform(80, 260))
    try:
        page.mouse.down()
        page.wait_for_timeout(random.uniform(45, 130))
        page.mouse.up()
    except Exception:
        locator.click(timeout=timeout)
    page.wait_for_timeout(random.uniform(150, 450))


def type_into(page, locator, text: str, timeout: int = 5000) -> None:
    """Click the box, then type. Short values key by key; a long text is typed for its
    first line and pasted for the rest (nobody types a cover letter into a form)."""
    click(page, locator, timeout=timeout)
    text = str(text)
    if len(text) <= 80:
        page.keyboard.type(text, delay=random.uniform(45, 110))
        if random.random() < 0.15:           # a glance back at what was typed
            page.wait_for_timeout(random.uniform(200, 500))
        return
    head, tail = text[:40], text[40:]
    page.keyboard.type(head, delay=random.uniform(40, 90))
    page.wait_for_timeout(random.uniform(150, 400))
    try:
        page.keyboard.insert_text(tail)
    except Exception:
        locator.fill(text, timeout=timeout)


def pause(page, lo: float = 350, hi: float = 1100) -> None:
    page.wait_for_timeout(random.uniform(lo, hi))


def wander(page) -> None:
    """A small scroll and a pointer drift, the way one looks a page over before acting."""
    try:
        page.mouse.wheel(0, random.uniform(120, 420))
        page.wait_for_timeout(random.uniform(300, 800))
        x, y = _pos(page)
        move(page, x + random.uniform(-160, 160), y + random.uniform(-90, 90))
    except Exception:
        pass
