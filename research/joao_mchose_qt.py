#!/usr/bin/env python3

import sys
import ctypes
import ctypes.util
import subprocess
import re
import signal
import time
import threading
from PyQt6.QtCore import (
    Qt,
    QThread,
    pyqtSignal,
    QRectF,
    QPointF,
    QSize,
    QVariantAnimation,
    QEasingCurve,
)
from PyQt6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QFont,
    QBrush,
    QPainterPath,
    QPixmap,
    QIcon,
)
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QPushButton,
    QFrame,
    QGraphicsOpacityEffect,
)

# Enable Ctrl+C to terminate application cleanly
signal.signal(signal.SIGINT, signal.SIG_DFL)

# Bluetooth support
try:
    import dbus

    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False


# Theme colors
class Theme:
    BG = QColor("#0b0e14")
    SURFACE_1 = QColor("#131720")
    SURFACE_2 = QColor("#1a1f2b")
    SURFACE_3 = QColor("#222838")
    BORDER = QColor("#1e2433")

    ACCENT_BLUE = QColor("#60a5fa")
    ACCENT_INDIGO = QColor("#818cf8")
    ACCENT_GREEN = QColor("#34d399")
    ACCENT_GOLD = QColor("#fbbf24")
    ACCENT_RED = QColor("#f87171")
    ACCENT_ORANGE = QColor("#fb923c")

    TEXT_PRIMARY = QColor("#f1f5f9")
    TEXT_SECONDARY = QColor("#94a3b8")
    TEXT_MUTED = QColor("#475569")
    TEXT_DIM = QColor("#334155")


# Backend Services
class HIDService:
    def __init__(self):
        self.hid = None
        self._lock = threading.Lock()
        self._init_hid()

    def _init_hid(self):
        for lib in (
            "libhidapi-hidraw.so.0",
            "libhidapi-hidraw.so",
            "/usr/lib/x86_64-linux-gnu/libhidapi-hidraw.so.0",
        ):
            try:
                self.hid = ctypes.CDLL(lib)
                break
            except Exception:
                continue

        if not self.hid:
            try:
                lib_name = ctypes.util.find_library("hidapi-hidraw")
                if lib_name:
                    self.hid = ctypes.CDLL(lib_name)
            except Exception:
                pass

        if not self.hid:
            return

        try:
            self.hid.hid_open.argtypes = [
                ctypes.c_ushort,
                ctypes.c_ushort,
                ctypes.c_wchar_p,
            ]
            self.hid.hid_open.restype = ctypes.c_void_p
            self.hid.hid_write.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_size_t,
            ]
            self.hid.hid_write.restype = ctypes.c_int
            self.hid.hid_read_timeout.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_size_t,
                ctypes.c_int,
            ]
            self.hid.hid_read_timeout.restype = ctypes.c_int
            self.hid.hid_send_feature_report.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_size_t,
            ]
            self.hid.hid_send_feature_report.restype = ctypes.c_int
            self.hid.hid_get_feature_report.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_size_t,
            ]
            self.hid.hid_get_feature_report.restype = ctypes.c_int
            self.hid.hid_close.argtypes = [ctypes.c_void_p]
            self.hid.hid_close.restype = None
            self.hid.hid_exit.argtypes = []
            self.hid.hid_exit.restype = ctypes.c_int
        except Exception:
            self.hid = None

    def query_status(self, current_eq_mode=0):
        if not self.hid:
            return False, 0, 0, 0
        with self._lock:
            handle = self.hid.hid_open(0x291D, 0x385D, None)
            if not handle:
                return False, 0, 0, 0
            battery = status_code = eq_mode = 0
            ok_bat = ok_eq = False
            try:
                buf = bytearray(64)
                buf[0], buf[1], buf[2] = 0x55, 0x65, 0x01
                c_buf = (ctypes.c_char * 64).from_buffer(buf)
                if self.hid.hid_write(handle, c_buf, 64) > 0:
                    rbuf = bytearray(64)
                    c_r = (ctypes.c_char * 64).from_buffer(rbuf)
                    if self.hid.hid_read_timeout(handle, c_r, 64, 500) > 0:
                        d = list(rbuf)
                        if d[0] == 0x55 and d[1] == 0x65:
                            battery, status_code = d[2], d[3]
                            ok_bat = True
                buf2 = bytearray(64)
                buf2[0], buf2[1] = 0x55, 0x11
                c2 = (ctypes.c_char * 64).from_buffer(buf2)
                if self.hid.hid_write(handle, c2, 64) > 0:
                    r2 = bytearray(64)
                    c_r2 = (ctypes.c_char * 64).from_buffer(r2)
                    if self.hid.hid_read_timeout(handle, c_r2, 64, 500) > 0:
                        d2 = list(r2)
                        if d2[0] == 0x55 and d2[1] == 0x11:
                            eq_mode = d2[2]
                            ok_eq = True
            except Exception:
                pass
            finally:
                self.hid.hid_close(handle)
            if ok_bat:
                return True, battery, status_code, eq_mode if ok_eq else current_eq_mode
            return False, 0, 0, 0

    def send_eq_command(self, mode):
        if not self.hid:
            return False, mode
        with self._lock:
            handle = self.hid.hid_open(0x291D, 0x385D, None)
            if not handle:
                return False, mode
            new_mode = mode
            try:
                buf = bytearray(64)
                buf[0], buf[1], buf[2], buf[3] = 0x55, 0x21, 0x01, mode
                c = (ctypes.c_char * 64).from_buffer(buf)
                if self.hid.hid_write(handle, c, 64) <= 0:
                    return False, mode
                time.sleep(0.05)
                q = bytearray(64)
                q[0], q[1] = 0x55, 0x11
                cq = (ctypes.c_char * 64).from_buffer(q)
                self.hid.hid_write(handle, cq, 64)
                rb = bytearray(64)
                cr = (ctypes.c_char * 64).from_buffer(rb)
                if self.hid.hid_read_timeout(handle, cr, 64, 300) > 2:
                    if rb[0] == 0x55 and rb[1] == 0x11:
                        new_mode = int(rb[2])
                return True, new_mode
            except Exception:
                return False, mode
            finally:
                self.hid.hid_close(handle)

    def get_firmware(self):
        if not self.hid:
            return "", ""
        with self._lock:
            handle = self.hid.hid_open(0x291D, 0x385D, None)
            if not handle:
                return "", ""
            fw_dongle = fw_headset = ""
            try:
                buf = bytearray(64)
                buf[0], buf[1], buf[2] = 0xAA, 0x01, 0x00
                c = (ctypes.c_char * 64).from_buffer(buf)
                if self.hid.hid_send_feature_report(handle, c, 64) <= 0:
                    return "", ""
                for delay in (0.3, 0.5, 0.9):
                    time.sleep(delay)
                    rb = bytearray(64)
                    rb[0] = 0xAA
                    c_r = (ctypes.c_char * 64).from_buffer(rb)
                    if self.hid.hid_get_feature_report(handle, c_r, 64) > 0:
                        d = list(rb)
                        if d[0] == 0xAA:
                            if len(d) >= 10:
                                fw_dongle = f"{d[8]:02d}{d[9]:02d}"
                            if len(d) >= 12:
                                fw_headset = f"{d[10]:02d}{d[11]:02d}"
                            break
            except Exception:
                pass
            finally:
                self.hid.hid_close(handle)
            return fw_dongle, fw_headset


class AudioService:
    def __init__(self):
        self._preferred_cmd_sink = None
        self._preferred_cmd_source = None
        self._detect_preferred_commands()

    def _detect_preferred_commands(self):
        for cmd in (
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            ["amixer", "sget", "Master"],
        ):
            try:
                subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
                self._preferred_cmd_sink = cmd[0]
                break
            except Exception:
                continue

        for cmd in (
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
            ["amixer", "sget", "Capture"],
        ):
            try:
                subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
                self._preferred_cmd_source = cmd[0]
                break
            except Exception:
                continue

    def get_sys_vol(self, sink=True):
        cmd_type = self._preferred_cmd_sink if sink else self._preferred_cmd_source
        if not cmd_type:
            return 50

        if cmd_type == "wpctl":
            target = "@DEFAULT_AUDIO_SINK@" if sink else "@DEFAULT_AUDIO_SOURCE@"
            cmd = ["wpctl", "get-volume", target]
        else:
            cmd = ["amixer", "sget", "Master" if sink else "Capture"]

        try:
            out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
            m = re.search(r"Volume:\s*([0-9.]+)", out)
            if m:
                return int(float(m.group(1)) * 100)
            m = re.search(r"(\d+)%", out)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return 50

    def set_sys_vol(self, value, sink=True):
        cmd_type = self._preferred_cmd_sink if sink else self._preferred_cmd_source
        if not cmd_type:
            return

        if cmd_type == "wpctl":
            target = "@DEFAULT_AUDIO_SINK@" if sink else "@DEFAULT_AUDIO_SOURCE@"
            vol_val = max(0.0, min(1.0, value / 100.0))
            cmd = ["wpctl", "set-volume", target, f"{vol_val:.2f}"]
        else:
            cmd = ["amixer", "sset", "Master" if sink else "Capture", f"{value}%"]

        try:
            subprocess.run(
                cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

    def set_sys_mic_mute(self, state):
        cmd_type = self._preferred_cmd_source
        if not cmd_type:
            return

        if cmd_type == "wpctl":
            val = "1" if state else "0"
            cmd = ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", val]
        else:
            cmd = ["amixer", "sset", "Capture", "mute" if state else "unmute"]

        try:
            subprocess.run(
                cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

    def get_mic_status(self, current_mic_vol=50):
        cmd_type = self._preferred_cmd_source
        if not cmd_type:
            return False, current_mic_vol

        muted = False
        vol = current_mic_vol

        if cmd_type == "wpctl":
            try:
                out = subprocess.check_output(
                    ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                if "[MUTED]" in out:
                    muted = True
                m = re.search(r"Volume:\s*([0-9.]+)", out)
                if m:
                    vol = int(float(m.group(1)) * 100)
            except Exception:
                pass
        else:
            try:
                out = subprocess.check_output(
                    ["amixer", "sget", "Capture"], text=True, stderr=subprocess.DEVNULL
                )
                if "[off]" in out:
                    muted = True
                m = re.search(r"(\d+)%", out)
                if m:
                    vol = int(m.group(1))
            except Exception:
                pass

        return muted, vol


class BluetoothService:
    def query_bluetooth(self):
        if not HAS_DBUS:
            return False, 0
        try:
            bus = dbus.SystemBus()
            manager = dbus.Interface(
                bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager"
            )
            objects = manager.GetManagedObjects()

            for path, interfaces in objects.items():
                if "org.bluez.Device1" in interfaces:
                    dev = interfaces["org.bluez.Device1"]
                    name = str(dev.get("Name", ""))
                    connected = bool(dev.get("Connected", False))
                    if ("MCHOSE" in name or "V9" in name) and connected:
                        bat = 0
                        if "org.bluez.Battery1" in interfaces:
                            bat = int(
                                interfaces["org.bluez.Battery1"].get("Percentage", 0)
                            )
                        return True, bat
        except Exception:
            pass
        return False, 0


# Worker Thread for Async HID & Bluetooth Polling
class PollWorker(QThread):
    status_signal = pyqtSignal(bool, int, int, int, object, object)

    def __init__(self, hid_service, bluetooth_service, parent=None):
        super().__init__(parent)
        self.hid_service = hid_service
        self.bluetooth_service = bluetooth_service
        self.running = True
        self.eq_mode = 0
        self.connected = False
        self.fw_dongle = ""
        self.fw_headset = ""
        self._fw_counter = 0

    def run(self):
        while self.running:
            ok, bat, sc, eq = self.hid_service.query_status(self.eq_mode)
            fd = fh = None
            if ok:
                was_off = not self.connected
                self._fw_counter += 1
                if (was_off and not self.fw_dongle) or self._fw_counter >= 60:
                    self._fw_counter = 0
                    fd, fh = self.hid_service.get_firmware()
            else:
                ok_bt, bat_bt = self.bluetooth_service.query_bluetooth()
                if ok_bt:
                    bat = bat_bt
                    sc = 0x02
                    eq = self.eq_mode
                else:
                    bat = sc = eq = 0

            self.status_signal.emit(ok, bat, sc, eq, fd, fh)
            self.msleep(2000)


# Worker Thread for Async Audio Volume Polling
class AudioWorker(QThread):
    audio_signal = pyqtSignal(int, bool, int)

    def __init__(self, audio_service, parent=None):
        super().__init__(parent)
        self.audio_service = audio_service
        self.running = True
        self.mic_level = 50

    def run(self):
        while self.running:
            vol = self.audio_service.get_sys_vol(sink=True)
            muted, mic_vol = self.audio_service.get_mic_status(self.mic_level)
            self.audio_signal.emit(vol, muted, mic_vol)
            self.msleep(250)


# Battery Ring Custom Painter Widget with 60FPS Smooth Interpolation & Outer Glow
class BatteryGaugeWidget(QWidget):
    def __init__(self, parent=None, size=190):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.percentage = 0.0
        self.target_pct = 0.0
        self.ring_color = QColor("#34d399")
        self.anim = None

    @staticmethod
    def _lerp_rgb(c1, c2, t):
        return (
            c1[0] + (c2[0] - c1[0]) * t,
            c1[1] + (c2[1] - c1[1]) * t,
            c1[2] + (c2[2] - c1[2]) * t,
        )

    def _battery_color(self, pct):
        pct = max(0, min(100, int(pct)))
        green = (52, 211, 153)
        yellow = (251, 191, 36)
        red = (248, 113, 113)
        if pct >= 50:
            t = (100 - pct) / 50.0
            r, g, b = self._lerp_rgb(green, yellow, t)
        else:
            t = (50 - pct) / 50.0
            r, g, b = self._lerp_rgb(yellow, red, t)
        return QColor(int(round(r)), int(round(g)), int(round(b)))

    def set_battery(self, pct, connected=True):
        target = float(pct) if connected else 0.0

        if not connected or pct == 0:
            self.ring_color = QColor(Theme.ACCENT_RED)
        else:
            self.ring_color = self._battery_color(pct)

        if self.target_pct == target and self.percentage == target:
            return

        self.target_pct = target

        if self.anim and self.anim.state() == QVariantAnimation.State.Running:
            self.anim.stop()

        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(float(self.percentage))
        self.anim.setEndValue(float(self.target_pct))
        self.anim.setDuration(650)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _on_val(val):
            self.percentage = float(val)
            self.update()

        self.anim.valueChanged.connect(_on_val)
        self.anim.start()

    def paintEvent(self, event):
        import math

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        s = self.width()
        cx = cy = s / 2.0
        pad = 14
        r = (s - 2 * pad) / 2.0
        w = max(6, int(r * 0.14))
        r_center = r - w / 2.0
        outer_rect = QRectF(pad, pad, s - 2 * pad, s - 2 * pad)

        # Glow effect
        if self.percentage > 0:
            glow_color = QColor(self.ring_color)
            glow_color.setAlpha(40)
            pen_glow = QPen(glow_color, w + 8)
            pen_glow.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen_glow)
            start_angle = 90 * 16
            span_angle = int(-self.percentage * 3.6 * 16)
            painter.drawArc(outer_rect, start_angle, span_angle)

        # Background track (full ellipse)
        pen_track = QPen(Theme.BORDER, w)
        pen_track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_track)
        painter.drawEllipse(outer_rect)

        # Active arc with round caps
        if self.percentage > 0:
            pen_active = QPen(self.ring_color, w)
            pen_active.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen_active)
            start_angle = 90 * 16
            span_angle = int(-self.percentage * 3.6 * 16)
            painter.drawArc(outer_rect, start_angle, span_angle)

        # Center dark fill
        inner_r = r - w - 8
        if inner_r > 0:
            painter.setBrush(QBrush(QColor("#0d1017")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(cx, cy), inner_r, inner_r)

        # Percentage text (absolute coords, matching gui.py: cx, cy - 4)
        font_size = max(22, int(r * 0.48))
        font_pct = QFont("Sans", font_size, QFont.Weight.Bold)
        painter.setFont(font_pct)
        painter.setPen(Theme.TEXT_PRIMARY)
        pct_text = f"{int(round(self.percentage))}%"
        fm = painter.fontMetrics()
        pct_w = fm.horizontalAdvance(pct_text)
        pct_y = cy - 4
        painter.drawText(
            QPointF(cx - pct_w / 2.0, pct_y + fm.ascent() / 2.0 - fm.descent() / 2.0),
            pct_text,
        )

        # "BATERIA" label below (absolute coords, matching gui.py: cx, cy + font_size * 0.55)
        label_size = max(8, int(r * 0.16))
        font_sub = QFont("Sans", label_size)
        painter.setFont(font_sub)
        painter.setPen(Theme.TEXT_MUTED)
        bat_text = "BATERIA"
        fm2 = painter.fontMetrics()
        bat_w = fm2.horizontalAdvance(bat_text)
        bat_y = cy + font_size * 0.55 + 6
        painter.drawText(
            QPointF(cx - bat_w / 2.0, bat_y + fm2.ascent() / 2.0 - fm2.descent() / 2.0),
            bat_text,
        )


# Custom Vector Painter Speaker / Volume Mute Button Widget (34x34 Pill Container)
class SpeakerButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.is_muted = False

    def set_muted(self, muted):
        self.is_muted = muted
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0, 0, self.width(), self.height())
        bg_color = Theme.SURFACE_3 if self.underMouse() else Theme.SURFACE_2
        border_color = Theme.ACCENT_RED if self.is_muted else Theme.ACCENT_BLUE
        icon_color = Theme.ACCENT_RED if self.is_muted else Theme.ACCENT_BLUE

        # Circle pill container with inset margin so border NEVER clips
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(border_color, 1.5))
        painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), 15.5, 15.5)

        # Speaker Vector Icon
        painter.setPen(
            QPen(
                icon_color,
                1.6,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )

        cx, cy = self.width() / 2, self.height() / 2

        # Speaker Cone (centered with generous margin)
        path = QPainterPath()
        path.moveTo(cx - 7.5, cy - 3.5)
        path.lineTo(cx - 7.5, cy + 3.5)
        path.lineTo(cx - 3.5, cy + 3.5)
        path.lineTo(cx + 1.0, cy + 7.0)
        path.lineTo(cx + 1.0, cy - 7.0)
        path.lineTo(cx - 3.5, cy - 3.5)
        path.closeSubpath()
        painter.fillPath(path, QBrush(icon_color))
        painter.drawPath(path)

        if self.is_muted:
            # Red Mute diagonal slash line if muted
            painter.setPen(
                QPen(
                    Theme.ACCENT_RED,
                    2.2,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawLine(QPointF(cx - 7, cy + 7), QPointF(cx + 7, cy - 7))
        else:
            # Sound Waves
            arc1 = QRectF(cx - 1.0, cy - 4.0, 7.5, 8.0)
            painter.drawArc(arc1, -45 * 16, 90 * 16)
            arc2 = QRectF(cx + 1.5, cy - 6.5, 10.5, 13.0)
            painter.drawArc(arc2, -45 * 16, 90 * 16)


# Custom Vector Painter Mic Mute Button Widget
class MicButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.is_muted = False

    def set_muted(self, muted):
        self.is_muted = muted
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0, 0, self.width(), self.height())
        bg_color = Theme.SURFACE_3 if self.underMouse() else Theme.SURFACE_2
        border_color = Theme.ACCENT_RED if self.is_muted else Theme.ACCENT_GREEN
        icon_color = Theme.ACCENT_RED if self.is_muted else Theme.ACCENT_GREEN

        # Circle pill container with inset margin so border NEVER clips
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(border_color, 1.5))
        painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), 15.5, 15.5)

        # Vector Microphone Icon
        painter.setPen(
            QPen(
                icon_color,
                1.8,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )

        cx, cy = self.width() / 2, self.height() / 2

        # Mic Capsule
        cap_w, cap_h = 6.0, 10.0
        painter.drawRoundedRect(
            QRectF(cx - cap_w / 2, cy - 7.5, cap_w, cap_h), 3.0, 3.0
        )

        # Mic Stand Arc
        arc_rect = QRectF(cx - 6.5, cy - 4.5, 13, 11)
        painter.drawArc(arc_rect, 0, -180 * 16)

        # Base stem
        painter.drawLine(QPointF(cx, cy + 6.5), QPointF(cx, cy + 9.5))
        painter.drawLine(QPointF(cx - 4.0, cy + 9.5), QPointF(cx + 4.0, cy + 9.5))

        # Mute diagonal slash line if muted
        if self.is_muted:
            painter.setPen(
                QPen(
                    Theme.ACCENT_RED,
                    2.2,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawLine(QPointF(cx - 7, cy + 7), QPointF(cx + 7, cy - 7))


# Equalizer Header Vector Icon Widget (34x34 Pill Container matching Speaker/Mic)
class EqualizerIconWidget(QWidget):
    def __init__(self, color=Theme.ACCENT_GOLD, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.color = color

    def set_color(self, color):
        if self.color != color:
            self.color = color
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0, 0, self.width(), self.height())
        bg_color = Theme.SURFACE_3 if self.underMouse() else Theme.SURFACE_2

        # Circle pill container with inset margin so border NEVER clips
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(self.color, 1.5))
        painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), 15.5, 15.5)

        # Equalizer Lines & Knobs
        painter.setPen(
            QPen(
                self.color,
                1.8,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        cx, cy = self.width() / 2, self.height() / 2

        # 3 Vertical EQ Bars
        for x_off in (-6, 0, 6):
            painter.drawLine(QPointF(cx + x_off, cy - 6), QPointF(cx + x_off, cy + 6))

        # Slider Knobs
        painter.setBrush(QBrush(self.color))
        painter.drawEllipse(QPointF(cx - 6, cy + 2), 2.2, 2.2)
        painter.drawEllipse(QPointF(cx, cy - 3), 2.2, 2.2)
        painter.drawEllipse(QPointF(cx + 6, cy + 1), 2.2, 2.2)


def make_gamepad_icon(color):
    pix = QPixmap(18, 18)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawRoundedRect(QRectF(1, 4, 16, 10), 4, 4)
    painter.drawLine(QPointF(4, 9), QPointF(8, 9))
    painter.drawLine(QPointF(6, 7), QPointF(6, 11))
    painter.setBrush(QBrush(color))
    painter.drawEllipse(QPointF(12, 7), 1.2, 1.2)
    painter.drawEllipse(QPointF(14, 9), 1.2, 1.2)
    painter.drawEllipse(QPointF(12, 11), 1.2, 1.2)
    painter.end()
    return QIcon(pix)


def make_target_icon(color):
    pix = QPixmap(18, 18)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 1.5))
    cx, cy = 9, 9
    painter.drawEllipse(QPointF(cx, cy), 6, 6)
    painter.drawEllipse(QPointF(cx, cy), 1.5, 1.5)
    painter.drawLine(QPointF(cx, cy - 8), QPointF(cx, cy - 5))
    painter.drawLine(QPointF(cx, cy + 5), QPointF(cx, cy + 8))
    painter.drawLine(QPointF(cx - 8, cy), QPointF(cx - 5, cy))
    painter.drawLine(QPointF(cx + 5, cy), QPointF(cx + 8, cy))
    painter.end()
    return QIcon(pix)


def make_music_icon(color):
    pix = QPixmap(18, 18)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(QBrush(color))
    painter.drawEllipse(QPointF(4, 13), 2.5, 2.0)
    painter.drawEllipse(QPointF(12, 11), 2.5, 2.0)
    painter.drawLine(QPointF(6.5, 13), QPointF(6.5, 5))
    painter.drawLine(QPointF(14.5, 11), QPointF(14.5, 3))
    painter.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(6.5, 5), QPointF(14.5, 3))
    painter.end()
    return QIcon(pix)


# Custom Vector Painter Connection Icon Widget (34x34 Pill Container)
class ConnectionIconWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.mode = None  # None, "2.4G", or "Bluetooth"
        self.is_connected = False

    def set_connection(self, connected, mode):
        self.is_connected = connected
        self.mode = mode
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0, 0, self.width(), self.height())
        bg_color = Theme.SURFACE_2
        if not self.is_connected:
            color = Theme.ACCENT_RED
        elif self.mode == "Bluetooth":
            color = Theme.ACCENT_BLUE
        else:
            color = Theme.ACCENT_GREEN

        # Circle pill container with inset margin so border NEVER clips
        painter.setBrush(QBrush(bg_color))
        painter.setPen(QPen(color, 1.5))
        painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), 15.5, 15.5)

        painter.setPen(
            QPen(
                color,
                1.8,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )

        cx, cy = self.width() / 2, self.height() / 2

        if not self.is_connected:
            # Disconnected Red Offline Circle & Slash
            painter.drawEllipse(QPointF(cx, cy), 5, 5)
            painter.setPen(
                QPen(
                    Theme.ACCENT_RED,
                    2.2,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawLine(QPointF(cx - 7, cy + 7), QPointF(cx + 7, cy - 7))

        elif self.mode == "Bluetooth":
            # Vector Bluetooth Rune Emblem (Iconic & Perfectly Symmetric)
            path = QPainterPath()
            path.moveTo(cx - 4.0, cy - 4.0)
            path.lineTo(cx + 3.0, cy + 3.0)
            path.lineTo(cx - 0.5, cy + 7.5)
            path.lineTo(cx - 0.5, cy - 7.5)
            path.lineTo(cx + 3.0, cy - 3.0)
            path.lineTo(cx - 4.0, cy + 4.0)
            painter.drawPath(path)

        else:  # 2.4G Wireless Dongle / Wi-Fi Signal Icon
            # Central Dot at bottom
            painter.setBrush(QBrush(color))
            painter.drawEllipse(QPointF(cx, cy + 6.0), 1.8, 1.8)

            # 3 Upward Curved Arcs (45 to 135 degrees = 90 deg span top arc)
            painter.drawArc(QRectF(cx - 4.5, cy + 1.5, 9.0, 9.0), 45 * 16, 90 * 16)
            painter.drawArc(QRectF(cx - 7.5, cy - 1.5, 15.0, 15.0), 45 * 16, 90 * 16)
            painter.drawArc(QRectF(cx - 10.5, cy - 4.5, 21.0, 21.0), 45 * 16, 90 * 16)


# Main Application Window
class MChoseMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MCHOSE V9 PRO")
        self.setMinimumWidth(400)

        # Services
        self.hid_service = HIDService()
        self.audio_service = AudioService()
        self.bluetooth_service = BluetoothService()

        # State
        self.battery_level = 0
        self.status_code = 0
        self.connected = False
        self.connection_mode = None
        self.fw_dongle = ""
        self.fw_headset = ""
        self.eq_mode = 0
        self.volume_level = 50
        self.vol_muted = False
        self.mic_level = 50
        self.mic_muted = False

        self._vol_anim = None
        self._mic_anim = None
        self._ignore_mic_slider_event = False
        self._ignore_vol_slider_event = False

        self._init_ui()
        self._apply_stylesheet()

        # Start Background Workers
        self.poll_worker = PollWorker(self.hid_service, self.bluetooth_service)
        self.poll_worker.status_signal.connect(self._on_poll_done)
        self.poll_worker.start()

        self.audio_worker = AudioWorker(self.audio_service)
        self.audio_worker.audio_signal.connect(self._on_audio_done)
        self.audio_worker.start()

        # Initial sizing (without setFixedHeight so Hyprland tiles it normally)
        self.adjustSize()
        self.resize(440, self.sizeHint().height())

    def _init_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        # Header Card
        header_frame = QFrame()
        header_frame.setObjectName("Card")
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(2)

        lbl_subtitle = QLabel("MCHOSE")
        lbl_subtitle.setStyleSheet(
            "color: #475569; font-weight: bold; font-size: 12px;"
        )
        header_layout.addWidget(lbl_subtitle)

        lbl_title = QLabel("V9 PRO CONTROLLER")
        lbl_title.setStyleSheet("color: #f1f5f9; font-weight: bold; font-size: 22px;")
        header_layout.addWidget(lbl_title)

        self.lbl_fw = QLabel("Buscando firmware...")
        self.lbl_fw.setStyleSheet("color: #475569; font-size: 11px;")
        header_layout.addWidget(self.lbl_fw)

        layout.addWidget(header_frame)

        # Battery Gauge Card
        bat_card = QFrame()
        bat_card.setObjectName("Card")
        bat_layout = QVBoxLayout(bat_card)
        bat_layout.setContentsMargins(12, 10, 12, 10)
        bat_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.gauge = BatteryGaugeWidget(size=160)
        bat_layout.addWidget(self.gauge, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(bat_card)

        # Connection Card
        conn_card = QFrame()
        conn_card.setObjectName("Card")
        conn_layout = QHBoxLayout(conn_card)
        conn_layout.setContentsMargins(12, 8, 12, 8)

        conn_left = QHBoxLayout()
        conn_left.setSpacing(10)

        self.conn_icon = ConnectionIconWidget()
        self.lbl_conn = QLabel("Desconectado")
        self.lbl_conn.setStyleSheet(
            "color: #f1f5f9; font-weight: bold; font-size: 14px;"
        )

        conn_left.addWidget(self.conn_icon)
        conn_left.addWidget(self.lbl_conn)

        conn_layout.addLayout(conn_left)
        conn_layout.addStretch()

        layout.addWidget(conn_card)

        # Volume Control Card
        vol_card = QFrame()
        vol_card.setObjectName("Card")
        vol_layout = QVBoxLayout(vol_card)
        vol_layout.setContentsMargins(12, 8, 12, 10)
        vol_layout.setSpacing(6)

        vol_header = QHBoxLayout()
        vol_left = QHBoxLayout()
        vol_left.setSpacing(10)

        self.btn_vol_mute = SpeakerButton()
        self.btn_vol_mute.clicked.connect(self._toggle_vol_mute)
        lbl_vol_title = QLabel("Volume")
        lbl_vol_title.setStyleSheet(
            "color: #f1f5f9; font-weight: bold; font-size: 14px;"
        )

        vol_left.addWidget(self.btn_vol_mute)
        vol_left.addWidget(lbl_vol_title)

        self.lbl_vol_val = QLabel("50%")
        self.lbl_vol_val.setStyleSheet(
            "color: #60a5fa; font-weight: bold; font-size: 14px;"
        )

        vol_header.addLayout(vol_left)
        vol_header.addStretch()
        vol_header.addWidget(self.lbl_vol_val)
        vol_layout.addLayout(vol_header)

        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(50)
        self.vol_slider.valueChanged.connect(self._on_vol_slider_changed)
        vol_layout.addWidget(self.vol_slider)

        layout.addWidget(vol_card)

        # Mic Control Card
        mic_card = QFrame()
        mic_card.setObjectName("Card")
        mic_layout = QVBoxLayout(mic_card)
        mic_layout.setContentsMargins(12, 8, 12, 10)
        mic_layout.setSpacing(6)

        mic_header = QHBoxLayout()
        mic_left = QHBoxLayout()
        mic_left.setSpacing(10)

        self.btn_mic_mute = MicButton()
        self.btn_mic_mute.clicked.connect(self._toggle_mic_mute)

        lbl_mic_title = QLabel("Microfone")
        lbl_mic_title.setStyleSheet(
            "color: #f1f5f9; font-weight: bold; font-size: 14px;"
        )

        mic_left.addWidget(self.btn_mic_mute)
        mic_left.addWidget(lbl_mic_title)

        self.lbl_mic_val = QLabel("50%")
        self.lbl_mic_val.setStyleSheet(
            "color: #34d399; font-weight: bold; font-size: 14px;"
        )

        mic_header.addLayout(mic_left)
        mic_header.addStretch()
        mic_header.addWidget(self.lbl_mic_val)
        mic_layout.addLayout(mic_header)

        self.mic_slider = QSlider(Qt.Orientation.Horizontal)
        self.mic_slider.setObjectName("MicSlider")
        self.mic_slider.setRange(0, 100)
        self.mic_slider.setValue(50)
        self.mic_slider.valueChanged.connect(self._on_mic_slider_changed)
        mic_layout.addWidget(self.mic_slider)

        layout.addWidget(mic_card)

        # Equalizer Card
        eq_card = QFrame()
        eq_card.setObjectName("Card")
        self.eq_opacity = QGraphicsOpacityEffect(eq_card)
        eq_card.setGraphicsEffect(self.eq_opacity)

        eq_layout = QVBoxLayout(eq_card)
        eq_layout.setContentsMargins(12, 8, 12, 10)
        eq_layout.setSpacing(6)

        eq_header = QHBoxLayout()
        eq_left = QHBoxLayout()
        eq_left.setSpacing(10)

        eq_icon_widget = EqualizerIconWidget(Theme.ACCENT_GOLD)
        lbl_eq_title = QLabel("Equalizador")
        lbl_eq_title.setStyleSheet(
            "color: #fbbf24; font-weight: bold; font-size: 14px;"
        )

        self.lbl_eq_hint = QLabel("")
        self.lbl_eq_hint.setStyleSheet(
            "color: #94a3b8; font-size: 11px; font-weight: bold;"
        )

        eq_left.addWidget(eq_icon_widget)
        eq_left.addWidget(lbl_eq_title)
        eq_header.addLayout(eq_left)
        eq_header.addStretch()
        eq_header.addWidget(self.lbl_eq_hint)
        eq_layout.addLayout(eq_header)

        eq_btn_layout = QHBoxLayout()
        self.eq_buttons = []
        self._eq_icon_fns = [make_gamepad_icon, make_target_icon, make_music_icon]

        for i, text in enumerate(["Jogo 1", "Jogo 2", "Música"]):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setIconSize(QSize(18, 18))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, mode=i: self._set_eq(mode))
            eq_btn_layout.addWidget(btn)
            self.eq_buttons.append(btn)

        eq_layout.addLayout(eq_btn_layout)
        layout.addWidget(eq_card)

    def _apply_stylesheet(self):
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #0b0e14;
            }
            QFrame#Card {
                background-color: #131720;
                border: 1px solid #1e2433;
                border-radius: 16px;
                padding: 4px;
            }
            QLabel#StatusBadge {
                background-color: #222838;
                color: #f87171;
                border-radius: 14px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 11px;
            }
            QSlider:horizontal {
                min-height: 24px;
                max-height: 24px;
                padding: 2px 0px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #1a1f2b;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #60a5fa;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #60a5fa;
                width: 18px;
                height: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: #93c5fd;
            }
            QSlider#MicSlider::sub-page:horizontal {
                background: #34d399;
                border-radius: 3px;
            }
            QSlider#MicSlider::handle:horizontal {
                background: #34d399;
                width: 18px;
                height: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }
            QSlider#MicSlider::handle:horizontal:hover {
                background: #6ee7b7;
            }
            QPushButton {
                background-color: #1a1f2b;
                color: #94a3b8;
                border: 1px solid #1e2433;
                border-radius: 10px;
                padding: 8px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #222838;
                color: #f1f5f9;
            }
            QPushButton:checked {
                background-color: #fbbf24;
                color: #0b0e14;
                border: none;
            }
        """
        )

    def _on_poll_done(self, ok, bat, sc, eq, fd, fh):
        if ok:
            self.connected = True
            self.connection_mode = "2.4G"
            self.battery_level = bat
            self.status_code = sc
            self.eq_mode = self.poll_worker.eq_mode
            if fd:
                self.fw_dongle = fd
            if fh:
                self.fw_headset = fh
        else:
            if bat > 0 or sc == 0x02:
                self.connected = True
                self.connection_mode = "Bluetooth"
                self.battery_level = bat
                self.status_code = sc
            else:
                self.connected = False
                self.connection_mode = None

        if self.fw_dongle and self.fw_headset:
            self.lbl_fw.setText(
                f"FW Dongle: {self.fw_dongle}  •  FW Headset: {self.fw_headset}"
            )

        self._update_ui_state()

    def _on_audio_done(self, vol, muted, mic_vol):
        if not self.vol_slider.isSliderDown():
            if vol == 0:
                self.vol_muted = True
            else:
                self.vol_muted = False
                self.volume_level = vol
            self._update_vol_visuals()

        if not self.mic_slider.isSliderDown():
            self.mic_muted = muted
            if mic_vol > 0:
                self.mic_level = mic_vol
            self._update_mic_visuals()

    def _animate_vol_slider(self, target):
        if self.vol_slider.isSliderDown():
            return

        current = self.vol_slider.value()
        if abs(current - target) <= 1:
            self._ignore_vol_slider_event = True
            self.vol_slider.setValue(target)
            self._ignore_vol_slider_event = False
            self.lbl_vol_val.setText(f"{target}%")
            return

        if self._vol_anim and self._vol_anim.state() == QVariantAnimation.State.Running:
            self._vol_anim.stop()

        self._vol_anim = QVariantAnimation(self)
        self._vol_anim.setStartValue(current)
        self._vol_anim.setEndValue(target)
        self._vol_anim.setDuration(250)
        self._vol_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _on_val(v):
            val = int(round(v))
            self._ignore_vol_slider_event = True
            self.vol_slider.setValue(val)
            self._ignore_vol_slider_event = False
            self.lbl_vol_val.setText(f"{val}%")

        self._vol_anim.valueChanged.connect(_on_val)
        self._vol_anim.start()

    def _update_ui_state(self):
        self.gauge.set_battery(self.battery_level, self.connected)
        self.conn_icon.set_connection(self.connected, self.connection_mode)

        if self.connected:
            self.lbl_conn.setText(f"Conectado ({self.connection_mode})")
        else:
            self.lbl_conn.setText("Desconectado")

        eq_enabled = (self.connected and self.connection_mode == "2.4G")
        self.eq_opacity.setOpacity(1.0 if eq_enabled else 0.45)

        if not eq_enabled and self.connected and self.connection_mode == "Bluetooth":
            self.lbl_eq_hint.setText("somente 2.4G")
        else:
            self.lbl_eq_hint.setText("")

        for i, btn in enumerate(self.eq_buttons):
            btn.setEnabled(eq_enabled)
            is_active = i == self.eq_mode
            btn.setChecked(is_active)
            icon_color = QColor("#0b0e14") if is_active else Theme.TEXT_SECONDARY
            btn.setIcon(self._eq_icon_fns[i](icon_color))

        self._update_vol_visuals()
        self._update_mic_visuals()

    def _update_vol_visuals(self):
        is_muted = self.vol_muted or (self.volume_level == 0)
        color = "#f87171" if is_muted else "#60a5fa"

        self.btn_vol_mute.set_muted(is_muted)

        val_text = "0%" if is_muted else f"{self.volume_level}%"
        self.lbl_vol_val.setText(val_text)
        self.lbl_vol_val.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 14px;"
        )

        slider_val = 0 if is_muted else self.volume_level
        if not self.vol_slider.isSliderDown():
            self._ignore_vol_slider_event = True
            self.vol_slider.setValue(slider_val)
            self._ignore_vol_slider_event = False

    def _update_mic_visuals(self):
        is_muted = self.mic_muted or (self.mic_level == 0)
        color = "#f87171" if is_muted else "#34d399"

        self.btn_mic_mute.set_muted(is_muted)

        val_text = "0%" if is_muted else f"{self.mic_level}%"
        self.lbl_mic_val.setText(val_text)
        self.lbl_mic_val.setStyleSheet(
            f"color: {color}; font-weight: bold; font-size: 14px;"
        )

        slider_val = 0 if is_muted else self.mic_level
        if not self.mic_slider.isSliderDown():
            self._ignore_mic_slider_event = True
            self.mic_slider.setValue(slider_val)
            self._ignore_mic_slider_event = False

    def _on_vol_slider_changed(self, value):
        if self._ignore_vol_slider_event:
            return
        v = int(value)
        if v > 0:
            self.volume_level = v
            if self.vol_muted:
                self.vol_muted = False
        else:
            if not self.vol_muted:
                self.vol_muted = True

        self._update_vol_visuals()
        self.audio_service.set_sys_vol(v, sink=True)

    def _toggle_vol_mute(self):
        self.vol_muted = not self.vol_muted
        if self.vol_muted:
            if self.volume_level == 0:
                self.volume_level = 50
            self.audio_service.set_sys_vol(0, sink=True)
        else:
            if self.volume_level == 0:
                self.volume_level = 50
            self.audio_service.set_sys_vol(self.volume_level, sink=True)

        self._update_vol_visuals()

    def _on_mic_slider_changed(self, value):
        if self._ignore_mic_slider_event:
            return

        v = int(value)
        if v > 0:
            self.mic_level = v
            if self.mic_muted:
                self.mic_muted = False
                self.audio_service.set_sys_mic_mute(False)
        else:
            if not self.mic_muted:
                self.mic_muted = True
                self.audio_service.set_sys_mic_mute(True)

        self._update_mic_visuals()
        self.audio_service.set_sys_vol(v, sink=False)

    def _toggle_mic_mute(self):
        self.mic_muted = not self.mic_muted
        if self.mic_muted:
            if self.mic_level == 0:
                self.mic_level = 50
        else:
            if self.mic_level == 0:
                self.mic_level = 50

        self._update_mic_visuals()
        self.audio_service.set_sys_mic_mute(self.mic_muted)
        if not self.mic_muted:
            self.audio_service.set_sys_vol(self.mic_level, sink=False)

    def _set_eq(self, mode):
        if not (self.connected and self.connection_mode == "2.4G"):
            return

        self.eq_mode = mode
        self.poll_worker.eq_mode = mode
        self._update_ui_state()

        def _async_send():
            ok, new_mode = self.hid_service.send_eq_command(mode)
            if ok:
                self.poll_worker.eq_mode = new_mode

        threading.Thread(target=_async_send, daemon=True).start()

    def closeEvent(self, event):
        self.poll_worker.running = False
        self.audio_worker.running = False
        self.poll_worker.wait(500)
        self.audio_worker.wait(500)
        event.accept()


def main():
    import os

    os.environ.pop("QT_STYLE_OVERRIDE", None)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MChoseMainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
