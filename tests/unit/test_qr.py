from app.services.qr_service import qr_svg


def test_qr_is_generated_locally_as_svg() -> None:
    image = qr_svg("http://192.168.1.10:8000/admin/3")

    assert image.startswith(b"<?xml")
    assert b"<svg" in image
