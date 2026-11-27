"""
Motion for the app, in the spirit of Apple's fluid interfaces:

  • springs, not fixed curves — critically damped (no bounce), because nothing here is
    flicked; bounce is only for gestures that carry momentum
  • interruptible — a new animation starts from where the old one is on screen right now
    (its presentation value), never from its target, so nothing jumps
  • spatially consistent — a page slides in from the side of the tab you picked
  • only on purpose — on things you did (a tab, the dates, a view), never on the
    background sync every minute
  • Reduce Motion (macOS Accessibility) turns it off

Charts grow in (see charts._Chart) when they're made inside `entrance()`.
"""

import math
import subprocess
import sys
from contextlib import contextmanager

from PyQt5.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QParallelAnimationGroup, \
    QSequentialAnimationGroup, QVariantAnimation, QAbstractAnimation
from PyQt5.QtWidgets import QGraphicsOpacityEffect


def _reduce_motion():
    if sys.platform != "darwin":
        return False
    try:
        r = subprocess.run(["defaults", "read", "com.apple.universalaccess", "reduceMotion"],
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip() == "1"
    except Exception:
        return False

REDUCED = _reduce_motion()


# ── springs ───────────────────────────────────────────────────────────────────
# Apple describes a spring by its damping ratio (1 = no overshoot) and response (how
# quickly it gets there). Qt animations run for a duration, so the spring is sampled
# over the time it takes to settle and handed to Qt as an easing curve.

def _spring(damping):
    omega = 9.0                                    # settles (to ~0.1%) by the end of the duration
    if damping >= 1:
        f = lambda x: 1 - (1 + omega * x) * math.exp(-omega * x)
    else:
        wd = omega * math.sqrt(1 - damping * damping)
        f = lambda x: 1 - math.exp(-damping * omega * x) * (
            math.cos(wd * x) + damping * omega / wd * math.sin(wd * x))
    end = f(1.0)
    return lambda x: f(x) / end

_curves = {}

def spring(damping=1.0):
    """A QEasingCurve following a spring with this damping ratio."""
    if damping not in _curves:
        fn = _spring(damping)
        curve = QEasingCurve()
        curve.setCustomType(fn)
        _curves[damping] = (curve, fn)                 # keep the function alive
    return QEasingCurve(_curves[damping][0])

def duration(response=0.35):
    """Milliseconds for a spring with this response (seconds) to settle."""
    return int(response * 1000 * 1.7)


# ── entrance: charts and cards made now grow / rise in ────────────────────────

_ENTRANCE = [False]
_made = [0]

@contextmanager
def entrance(on=True):
    """Widgets made inside this block animate in when first shown."""
    before = _ENTRANCE[0]
    _ENTRANCE[0] = bool(on) and not REDUCED
    _made[0] = 0
    try:
        yield
    finally:
        _ENTRANCE[0] = before

def entering():
    return _ENTRANCE[0]

def next_delay(step=45, cap=360):
    """A small stagger for each thing made in this entrance, so they arrive in reading order."""
    d = min(_made[0] * step, cap)
    _made[0] += 1
    return d


def grow(widget, setter, delay=0, response=0.5):
    """Animate setter(t) from 0 to 1 (e.g. a donut sweeping round). Returns the animation."""
    anim = QVariantAnimation(widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(duration(response))
    anim.setEasingCurve(spring(1.0))
    anim.valueChanged.connect(lambda v: setter(float(v)))
    if delay:
        seq = QSequentialAnimationGroup(widget)
        seq.addPause(delay)
        seq.addAnimation(anim)
        seq.start(QAbstractAnimation.DeleteWhenStopped)
        return seq
    anim.start(QAbstractAnimation.DeleteWhenStopped)
    return anim


# ── arriving: fade + slide, interruptible ─────────────────────────────────────

_running = {}          # widget → (group, effect)

def arrive(widget, dx=0, dy=0, delay=0, response=0.38, relayout=True, fade=True):
    """Fade the widget in while it slides by (dx, dy) to where it is now. If it's already
    arriving, the new motion starts from where it is on screen (its current opacity and
    position), so a quick change of mind never jumps."""
    if REDUCED:
        return
    end = widget.pos()
    old = _running.pop(widget, None)
    if old:
        group, effect, end = old
        start_opacity = effect.opacity() if effect else 1.0
        start_pos = widget.pos()                   # presentation value, mid-flight
        try:
            group.stop()
        except RuntimeError:
            pass
    else:
        effect = None
        if fade:
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        start_opacity = 0.0
        start_pos = end + QPoint(dx, dy)
    if effect:
        effect.setOpacity(start_opacity)
    widget.move(start_pos)

    group = QParallelAnimationGroup(widget)
    if effect:
        f = QPropertyAnimation(effect, b"opacity", group)
        f.setStartValue(start_opacity)
        f.setEndValue(1.0)
        f.setDuration(duration(response * 0.8))
        f.setEasingCurve(QEasingCurve(QEasingCurve.OutCubic))
        group.addAnimation(f)
    move = QPropertyAnimation(widget, b"pos", group)
    move.setStartValue(start_pos)
    move.setEndValue(end)
    move.setDuration(duration(response))
    move.setEasingCurve(spring(1.0))
    group.addAnimation(move)

    def done():
        _running.pop(widget, None)
        try:
            if effect:
                widget.setGraphicsEffect(None)     # effects cost a repaint pass; drop it once settled
            parent = widget.parentWidget()
            if relayout and parent is not None and parent.layout() is not None:
                parent.layout().invalidate()       # the layout has the last word on where it sits
        except RuntimeError:                       # the widget was deleted meanwhile
            pass
    group.finished.connect(done)
    _running[widget] = (group, effect, end)
    if delay:
        seq = QSequentialAnimationGroup(widget)
        seq.addPause(delay)
        seq.addAnimation(group)
        seq.start(QAbstractAnimation.DeleteWhenStopped)
    else:
        group.start(QAbstractAnimation.DeleteWhenStopped)


def settle_all():
    """Stop every arrival now, at its end (e.g. before a page is rebuilt)."""
    for widget, (group, effect, end) in list(_running.items()):
        try:
            group.stop()
            if effect:
                effect.setOpacity(1.0)
                widget.setGraphicsEffect(None)
            widget.move(end)
        except RuntimeError:
            pass
    _running.clear()


# ── pages: the old one fades away as the new one slides in ────────────────────

_overlay = [None]

def switch_page(container, old_page, new_page, dx):
    """A tab change: a snapshot of the old page fades out on top while the new page slides
    in by dx. (Fading a picture is clean and cheap; fading a whole live page smears.)"""
    if REDUCED or old_page is None or new_page is None:
        return
    from PyQt5.QtWidgets import QLabel
    if _overlay[0] is not None:                      # a quick change of mind: drop the old picture
        try:
            _overlay[0].deleteLater()
        except RuntimeError:
            pass
        _overlay[0] = None
    pic = old_page.grab()
    shot = QLabel(container)
    shot.setPixmap(pic)
    shot.setGeometry(new_page.geometry())
    shot.setAttribute(0x29)                           # Qt.WA_TransparentForMouseEvents
    effect = QGraphicsOpacityEffect(shot)
    shot.setGraphicsEffect(effect)
    shot.show()
    shot.raise_()
    _overlay[0] = shot
    out = QPropertyAnimation(effect, b"opacity", shot)
    out.setStartValue(1.0)
    out.setEndValue(0.0)
    out.setDuration(duration(0.22))
    out.setEasingCurve(QEasingCurve(QEasingCurve.OutCubic))

    def gone():
        if _overlay[0] is shot:
            _overlay[0] = None
        shot.deleteLater()
    out.finished.connect(gone)
    out.start(QAbstractAnimation.DeleteWhenStopped)
    arrive(new_page, dx=dx, fade=False)
