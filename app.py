"""Simple break timer: one React webview window, no hidden windows."""
import logging
import threading
import time
from pathlib import Path

import webview


class Timer:
    def __init__(self):
        self.minutes = 25
        self.deadline = None
        self.remaining = 0
        self.phase = 'idle'
        self.previewing = False
        self.overlay_open = False
        self.window = None
        self.lock = threading.Lock()
        self.stopped = threading.Event()

    def status(self):
        with self.lock:
            remaining = (max(0, self.deadline - time.monotonic())
                         if self.phase == 'running' else
                         self.remaining if self.phase == 'paused' else 0)
            return {'phase': self.phase, 'minutes': self.minutes,
                    'remaining': remaining, 'previewing': self.previewing}

    def _show_break(self):
        # A single already-visible window avoids pywebview's hidden-window issue.
        self.window.on_top = True
        self.window.restore()             # Unminimize if necessary.
        self.window.toggle_fullscreen()   # Enter fullscreen (the window starts non-fullscreen).

    def _close_break(self):
        self.window.toggle_fullscreen()   # Restore the original window size.
        self.window.on_top = False

    def start(self, minutes=25):
        minutes = int(minutes)
        if not 1 <= minutes <= 240:
            raise ValueError('Choose an interval from 1 to 240 minutes')
        with self.lock:
            self.minutes = minutes
            self.deadline = time.monotonic() + 60 * minutes
            self.phase = 'running'
        return self.status()

    def pause(self):
        with self.lock:
            if self.phase == 'running':
                self.remaining = max(0, self.deadline - time.monotonic())
                self.phase = 'paused'
        return self.status()

    def resume(self):
        with self.lock:
            if self.phase == 'paused':
                self.deadline = time.monotonic() + self.remaining
                self.phase = 'running'
        return self.status()

    def reset(self):
        with self.lock:
            self.phase = 'idle'
            self.deadline = None
            self.previewing = False
            was_open = self.overlay_open
            self.overlay_open = False
        if was_open:
            self._close_break()
        return self.status()

    def preview(self):
        with self.lock:
            if self.phase == 'break':
                return self.status_unlocked()
            if self.overlay_open:
                return self.status_unlocked()
            self.previewing = True
            self.overlay_open = True
        try:
            self._show_break()
        except Exception:
            with self.lock:
                self.previewing = False
                self.overlay_open = False
            raise
        return self.status()

    def status_unlocked(self):
        """Only call with self.lock held."""
        remaining = (max(0, self.deadline - time.monotonic())
                     if self.phase == 'running' else
                     self.remaining if self.phase == 'paused' else 0)
        return {'phase': self.phase, 'minutes': self.minutes,
                'remaining': remaining, 'previewing': self.previewing}

    def finish(self, action='done'):
        with self.lock:
            if self.phase == 'break':
                if action == 'snooze':
                    self.deadline = time.monotonic() + 5 * 60
                    self.phase = 'running'
                elif action == 'next':
                    self.deadline = time.monotonic() + self.minutes * 60
                    self.phase = 'running'
                else:
                    self.deadline = None
                    self.phase = 'idle'
            self.previewing = False
            was_open = self.overlay_open
            self.overlay_open = False
        if was_open:
            self._close_break()
        return self.status()

    def tick(self):
        """Check whether the timer expired. Called by a lightweight worker."""
        with self.lock:
            if self.phase != 'running' or time.monotonic() < self.deadline:
                return
            self.phase = 'break'
            self.previewing = False
            need_show = not self.overlay_open
            self.overlay_open = True
        if need_show:
            try:
                self._show_break()
            except Exception:
                logging.exception('Could not bring break reminder to the front')

    def watch(self):
        while not self.stopped.wait(0.25):
            self.tick()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    timer = Timer()
    page = (Path(__file__).parent / 'index.html').resolve().as_uri()
    timer.window = webview.create_window(
        'Break Reminder', page, js_api=timer, width=480, height=650,
        min_size=(420, 580), background_color='#111827')
    timer.window.events.closed += lambda: timer.stopped.set()
    webview.start(timer.watch, gui='gtk')
