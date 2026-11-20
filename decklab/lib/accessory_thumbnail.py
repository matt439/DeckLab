"""Make small, oriented previews of stored accessory photos."""
from collections import OrderedDict
from io import BytesIO
from threading import BoundedSemaphore, Lock

from decklab.lib import accessory_fetch


EDGE = 256
FORMATS = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP"}
MAX_THUMBNAILS = 64
_cache = OrderedDict()
_cache_lock = Lock()
_slots = BoundedSemaphore(2)   # full-size PNG and WebP decoding can use substantial memory


def make(data, ext, digest):
    """Cache previews by the checked source bytes' full digest. The caller checks access."""
    with _cache_lock:
        preview = _cache.get(digest)
        if preview is not None:
            _cache.move_to_end(digest)
            return preview
    preview = _encode(data, ext)
    if preview is not None:
        with _cache_lock:
            _cache[digest] = preview
            _cache.move_to_end(digest)
            if len(_cache) > MAX_THUMBNAILS:
                _cache.popitem(last=False)
    return preview


def _encode(data, ext):
    """Resize the displayed image, keeping its proportions and dropping photo metadata."""
    from PIL import Image, ImageOps

    size = accessory_fetch.dimensions(data, ext)
    if len(data) > accessory_fetch.MAX_IMAGE or size is None or max(size) > accessory_fetch.MAX_SIDE:
        return None
    try:
        with _slots, Image.open(BytesIO(data), formats=[FORMATS[ext]]) as source:
            source.thumbnail((EDGE, EDGE), Image.Resampling.LANCZOS)
            ImageOps.exif_transpose(source, in_place=True)
            mode = "RGBA" if source.has_transparency_data else "RGB"
            with source.convert(mode) as image, BytesIO() as output:
                image.save(output, format="WEBP", quality=80)
                return output.getvalue()
    except (Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        return None
