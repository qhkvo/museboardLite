"""Create deterministic, locally generated test fixtures (no external image rights)."""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

destination = Path(__file__).resolve().parents[1] / "output/fixtures"
destination.mkdir(parents=True, exist_ok=True)
for name, size in [("landscape", (640, 360)), ("portrait", (301, 503))]:
    image = Image.new("RGB", size, "#a9d9ee")
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.ellipse((w * .7, h * .1, w * .9, h * .3), fill="#ffdb64")
    draw.polygon([(0,h),(w*.3,h*.3),(w*.6,h),(w*.8,h*.5),(w,h)], fill="#527b49")
    image.save(destination / f"{name}.png")
    if name == "landscape":
        image.save(destination / "landscape-copy.png")
        image.transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(destination / "landscape-flipped.jpg")
Image.fromarray(np.random.default_rng(42).integers(0, 256, (350, 481, 3), dtype=np.uint8)).save(destination / "noise.png")
Image.new("RGB", (1, 1), "red").save(destination / "tiny.png")
Image.new("L", (280, 400), 100).save(destination / "grayscale.png")
Image.new("RGBA", (250, 300), (70, 120, 180, 100)).save(destination / "alpha.png")
oriented = Image.open(destination / "landscape.png")
exif = Image.Exif()
exif[274] = 6
oriented.save(destination / "oriented.jpg", exif=exif)
(destination / "invalid.png").write_text("This is not a PNG")
print(destination)
