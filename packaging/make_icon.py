"""Genera el icono de la aplicación (assets/optiwin.png y .ico). Ejecutar con: python packaging/make_icon.py"""

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

OUT = Path(__file__).resolve().parent.parent / "src" / "optiwin" / "assets"


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size
    grad = QLinearGradient(0, 0, s, s)
    grad.setColorAt(0, QColor("#0f9d8a"))
    grad.setColorAt(1, QColor("#1565c0"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92), s * 0.22, s * 0.22)
    p.fillPath(path, QBrush(grad))
    bolt = QPolygonF([
        QPointF(s * 0.56, s * 0.12), QPointF(s * 0.27, s * 0.55), QPointF(s * 0.46, s * 0.55),
        QPointF(s * 0.40, s * 0.88), QPointF(s * 0.73, s * 0.42), QPointF(s * 0.53, s * 0.42),
    ])
    p.setPen(QPen(QColor(255, 255, 255, 0)))
    p.setBrush(QColor("#ffffff"))
    p.drawPolygon(bolt)
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication([])
    OUT.mkdir(parents=True, exist_ok=True)
    draw(256).save(str(OUT / "optiwin.png"))
    draw(256).save(str(OUT / "optiwin.ico"))
    print("Icono generado en", OUT)
