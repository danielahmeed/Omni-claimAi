import io
import unittest

from PIL import Image

from omniclaim import imaging
from omniclaim.config import BASE_DIR


def jpeg_bytes(color=(200, 30, 30), size=(400, 300), exif=None, pattern=True) -> bytes:
    img = Image.new("RGB", size, color)
    if pattern:  # Give the image structure so the perceptual hash is meaningful.
        for x in range(0, size[0], 40):
            for y in range(0, size[1], 30):
                img.paste((x % 255, y % 255, (x + y) % 255), (x, y, x + 20, y + 15))
    out = io.BytesIO()
    if exif is not None:
        img.save(out, "JPEG", quality=90, exif=exif)
    else:
        img.save(out, "JPEG", quality=90)
    return out.getvalue()


def exif_block(make="Google", model="Pixel 8", taken="2026:10:14 09:30:00", software="", gps=None):
    exif = Image.Exif()
    exif[271], exif[272] = make, model
    if software:
        exif[305] = software
    exif.get_ifd(0x8769)[36867] = taken
    if gps:
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd.update(gps)
    return exif


class ImagingTest(unittest.TestCase):
    def test_metadata_is_read(self):
        data = jpeg_bytes(exif=exif_block(software="Adobe Photoshop 25.0"))
        processed = imaging.process_photo(data)
        meta = processed.metadata
        self.assertTrue(meta["hasExif"])
        self.assertEqual(meta["cameraMake"], "Google")
        self.assertEqual(meta["cameraModel"], "Pixel 8")
        self.assertEqual(meta["capturedAt"], "2026-10-14T09:30:00")
        self.assertEqual(meta["editedWith"], "Adobe Photoshop 25.0")

    def test_gps_is_decoded(self):
        gps = {1: "N", 2: (37.0, 48.0, 30.0), 3: "W", 4: (122.0, 16.0, 12.0)}
        meta = imaging.process_photo(jpeg_bytes(exif=exif_block(gps=gps))).metadata
        self.assertAlmostEqual(meta["gps"]["lat"], 37.808333, places=4)
        self.assertAlmostEqual(meta["gps"]["lon"], -122.27, places=2)

    def test_no_exif(self):
        meta = imaging.process_photo(jpeg_bytes()).metadata
        self.assertFalse(meta["hasExif"])
        self.assertIsNone(meta["capturedAt"])

    def test_output_is_clean_jpeg(self):
        processed = imaging.process_photo(jpeg_bytes(exif=exif_block(), size=(3000, 2000)))
        self.assertLessEqual(max(processed.width, processed.height), imaging.PHOTO_MAX_SIDE)
        stored = Image.open(io.BytesIO(processed.jpeg))
        self.assertEqual(stored.format, "JPEG")
        self.assertEqual(len(stored.getexif()), 0, "metadata must be stripped from stored copies")

    def test_hash_survives_resize_and_recompression(self):
        original = jpeg_bytes(size=(1200, 900))
        img = Image.open(io.BytesIO(original)).resize((600, 450))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=60)
        a = imaging.process_photo(original).dhash
        b = imaging.process_photo(out.getvalue()).dhash
        self.assertLessEqual(imaging.hamming_distance(a, b), 6)

    def test_different_photos_have_distant_hashes(self):
        a = imaging.process_photo(jpeg_bytes(color=(200, 30, 30))).dhash
        b = imaging.process_photo(jpeg_bytes(color=(10, 10, 10), pattern=False)).dhash
        c = imaging.process_photo((BASE_DIR / "samples/photos/wheel-arch-scrape.jpg").read_bytes()).dhash
        d = imaging.process_photo((BASE_DIR / "samples/photos/water-damaged-ceiling.jpg").read_bytes()).dhash
        self.assertGreater(imaging.hamming_distance(c, d), 6)
        self.assertNotEqual(a, b)

    def test_png_with_transparency(self):
        img = Image.new("RGBA", (200, 200), (255, 0, 0, 0))
        out = io.BytesIO()
        img.save(out, "PNG")
        processed = imaging.process_photo(out.getvalue())
        self.assertEqual(Image.open(io.BytesIO(processed.jpeg)).mode, "RGB")

    def test_rejects_non_images(self):
        with self.assertRaises(imaging.InvalidUpload):
            imaging.process_photo(b"%PDF-1.7 not an image")
        with self.assertRaises(imaging.InvalidUpload):
            imaging.process_photo(b"")
        out = io.BytesIO()
        Image.new("RGB", (64, 64)).save(out, "GIF")
        with self.assertRaises(imaging.InvalidUpload):
            imaging.process_photo(out.getvalue())

    def test_rejects_tiny_images(self):
        out = io.BytesIO()
        Image.new("RGB", (10, 10)).save(out, "PNG")
        with self.assertRaises(imaging.InvalidUpload):
            imaging.process_photo(out.getvalue())

    def test_pdf_detection(self):
        self.assertTrue(imaging.is_pdf(b"%PDF-1.4\n..."))
        self.assertFalse(imaging.is_pdf(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
