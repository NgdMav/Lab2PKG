from PIL import Image
from typing import Tuple, Dict, Any, Optional

def infer_color_depth(img: Image.Image) -> int:
    """Попытаться вывести глубину цвета в битах (total bits per pixel)."""
    mode = img.mode
    if mode == "1":
        return 1
    if mode in ("L", "P"):
        return 8
    if mode == "RGB":
        return 24
    if mode == "RGBA":
        return 32
    if mode == "CMYK":
        return 32
    try:
        bands = len(img.getbands())
        return bands * 8
    except Exception:
        return 0

def get_dpi(img: Image.Image) -> Tuple[Optional[float], Optional[float]]:
    """Возвращаем (dpi_x, dpi_y) или (None, None)."""
    info = img.info
    dpi = info.get("dpi")
    if isinstance(dpi, tuple) and len(dpi) == 2:
        return dpi[0], dpi[1]
    try:
        if hasattr(img, "tag_v2"):
            tag = img.tag_v2
            x = tag.get(282)  # XResolution
            y = tag.get(283)  # YResolution
            unit = tag.get(296)  # ResolutionUnit
            if x and y:
                def rational_to_float(v):
                    try:
                        return float(v)
                    except Exception:
                        try:
                            return v[0] / v[1]
                        except Exception:
                            return None
                xd = rational_to_float(x)
                yd = rational_to_float(y)
                if unit == 3:
                    if xd: xd = xd * 2.54
                    if yd: yd = yd * 2.54
                return xd, yd
    except Exception:
        pass
    return None, None

def get_compression_info(img: Image.Image) -> Optional[str]:
    """Попытаться прочитать способ сжатия, если доступно."""
    info = img.info
    if img.format == "PNG":
        return info.get("compression", "deflate/zlib")
    if img.format == "JPEG":
        if info.get("progression") or info.get("progressive"):
            return "JPEG (progressive)"
        return "JPEG (baseline)"
    if img.format == "TIFF":
        try:
            if hasattr(img, "tag_v2"):
                tag = img.tag_v2
                comp = tag.get(259)  # Compression tag
                if comp is not None:
                    # comp is rational/int; common values: 1=none, 5=LZW, 6=JPEG, 8=Deflate
                    mapping = {1: "None", 5: "LZW", 6: "JPEG", 7: "JPEG (Old-style)", 8: "Deflate"}
                    return mapping.get(int(comp), f"TIFF Compression code {comp}")
        except Exception:
            pass
        return info.get("compression", None)
    if img.format == "GIF":
        # GIF uses LZW
        return "LZW (GIF)"
    if img.format == "PCX":
        # PCX may have run-length encoding
        return info.get("compression", "RLE/PCX")
    if img.format == "BMP":
        # BMP compression stored in info if present
        return info.get("compression", "BMP (usually none)")
    return info.get("compression", None)

def get_additional_info(img: Image.Image) -> Dict[str, Any]:
    """Возвращаем дополнительные полезные поля"""
    res = {}
    try:
        exif = {}
        raw_exif = {}
        try:
            raw_exif = img.getexif() or {}
        except Exception:
            raw_exif = {}
        if raw_exif:
            for k, v in raw_exif.items():
                exif[str(k)] = str(v)
            res["exif_keys_count"] = len(exif)
            res["exif_sample"] = dict(list(exif.items())[:5])
    except Exception:
        pass

    # JPEG quantization tables
    try:
        if img.format == "JPEG" and hasattr(img, "quantization") and img.quantization:
            res["jpeg_quant_tables"] = {k: (len(v) if v else 0) for k, v in img.quantization.items()}
    except Exception:
        pass

    # GIF palette size (if palette mode)
    try:
        if img.format == "GIF":
            if img.mode == "P":
                pal = img.getpalette()
                if pal:
                    res["gif_palette_colors"] = int(len(pal) / 3)
                else:
                    res["gif_palette_colors"] = None
            # number of frames
            try:
                res["gif_frames"] = getattr(img, "n_frames", 1)
            except Exception:
                res["gif_frames"] = 1
    except Exception:
        pass

    return res

def inspect_image(path: str) -> Dict[str, Any]:
    """Основная функция: открыть файл и собрать метаданные."""
    out = {"path": path, "filename": path.split("/")[-1]}
    try:
        with Image.open(path) as img:
            out["format"] = img.format
            out["width"], out["height"] = img.size
            dpi_x, dpi_y = get_dpi(img)
            out["dpi_x"] = dpi_x
            out["dpi_y"] = dpi_y
            out["depth"] = infer_color_depth(img)
            out["mode"] = img.mode
            out["compression"] = get_compression_info(img)
            out["additional"] = get_additional_info(img)
    except Exception as e:
        out["error"] = str(e)
    return out
