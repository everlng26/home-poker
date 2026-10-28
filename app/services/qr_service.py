from __future__ import annotations

from io import BytesIO

import qrcode
from qrcode.image.svg import SvgPathImage


def qr_svg(url: str) -> bytes:
    """Создаёт QR-код локально, без передачи адреса в интернет."""
    code = qrcode.QRCode(version=None, box_size=10, border=3, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(url)
    code.make(fit=True)
    image = code.make_image(image_factory=SvgPathImage)
    buffer = BytesIO()
    image.save(buffer)
    return buffer.getvalue()

