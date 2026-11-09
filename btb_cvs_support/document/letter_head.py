"""Put a Quotation's selected Letter Head into the Quotation Format template.

quotation_format_letterhead.docx carries the common body plus two placeholder
pictures: the default header (media/letterhead_header.png) and the default
footer (media/letterhead_footer.png). `build_template` copies that template and
swaps both pictures for the Letter Head, so OneDoc receives a .docx whose header
and footer already look like the print view's.

Each side of the Letter Head is resolved independently, mirroring the doctype:

    source = "Image" with a raster file attached -> that file, at the
        width/height/align set on the Letter Head
    otherwise -> the `content` / `footer` HTML, rendered with Jinja against the
        document (exactly as frappe.www.printview does) and photographed with
        wkhtmltoimage at the template's content width

A side that resolves to nothing is shrunk to a 1px blank.
"""

import io
import os
import re
import subprocess
import tempfile
import zipfile
from urllib.parse import unquote

import frappe
from PIL import Image, ImageChops

TEMPLATE = os.path.join(os.path.dirname(__file__), "templates", "quotation_format_letterhead.docx")

HEADER_MEDIA = "word/media/letterhead_header.png"
FOOTER_MEDIA = "word/media/letterhead_footer.png"
HEADER_PART = "word/header2.xml"
FOOTER_PART = "word/footer2.xml"

EMU_PER_PX = 9525  # 914400 EMU per inch / 96 px per inch
CONTENT_WIDTH_EMU = 7021195  # Letter page less the template's side margins
CONTENT_WIDTH_PX = round(CONTENT_WIDTH_EMU / EMU_PER_PX)  # 737
HTML_ZOOM = 2  # render HTML at 2x so the picture stays sharp in print

ALIGN = {"left": "left", "center": "center", "right": "right"}


def build_template(letter_head: str, doc) -> str:
    """Write a copy of the letter head template for `doc` and return its path.

    The caller owns the file and must delete it.
    """
    lh = frappe.get_doc("Letter Head", letter_head)
    header = _resolve(lh, doc, "header")
    footer = _resolve(lh, doc, "footer")

    with zipfile.ZipFile(TEMPLATE) as src:
        parts = {name: src.read(name) for name in src.namelist()}

    parts[HEADER_MEDIA] = header["png"]
    parts[FOOTER_MEDIA] = footer["png"]
    parts[HEADER_PART] = _place(parts[HEADER_PART], header)
    parts[FOOTER_PART] = _place(parts[FOOTER_PART], footer)

    fd, path = tempfile.mkstemp(prefix="quotation_lh_", suffix=".docx")
    os.close(fd)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("[Content_Types].xml", parts.pop("[Content_Types].xml"))
        for name, data in parts.items():
            out.writestr(name, data)
    return path


def _resolve(lh, doc, side: str) -> dict:
    if side == "header":
        source, image, html = lh.source, lh.image, lh.content
        width, height, align = lh.image_width, lh.image_height, lh.align
    else:
        source, image, html = lh.footer_source, lh.footer_image, lh.footer
        width, height, align = lh.footer_image_width, lh.footer_image_height, lh.footer_align

    if source == "Image" and image:
        img = _open_file(image)
        if img is not None:
            return _from_image(img, width, height, align)

    if html and html.strip():
        img = _render_html(frappe.render_template(html, {"doc": doc.as_dict()}))
        if img is not None:
            # Rendered at the full content width, so alignment is already in the picture.
            return _sized(img, CONTENT_WIDTH_EMU, "left")

    return _blank()


def _from_image(img: Image.Image, width, height, align) -> dict:
    """Size an attached picture the way LetterHead.set_image_as_html does.

    Only the larger of image_width/image_height is applied and the other follows
    the aspect ratio; with neither set the picture spans the content width.
    """
    w, h = img.size
    width, height = float(width or 0), float(height or 0)
    if width and width > height:
        cx = width * EMU_PER_PX
    elif height:
        cx = height * EMU_PER_PX * w / h
    else:
        cx = CONTENT_WIDTH_EMU
    return _sized(img, min(cx, CONTENT_WIDTH_EMU), align)


def _sized(img: Image.Image, cx, align) -> dict:
    w, h = img.size
    cx = int(cx)
    return {
        "png": _png(img),
        "cx": cx,
        "cy": int(cx * h / w),
        "align": ALIGN.get((align or "").lower(), "left"),
    }


def _blank() -> dict:
    img = Image.new("RGBA", (1, 1), (255, 255, 255, 0))
    return {"png": _png(img), "cx": EMU_PER_PX, "cy": EMU_PER_PX, "align": "left"}


def _png(img: Image.Image) -> bytes:
    if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        img = img.convert("RGB")  # CMYK JPEGs cannot be written as PNG
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _place(xml: bytes, picture: dict) -> bytes:
    """Set the size and alignment of the single picture in a header/footer part."""
    xml = xml.decode("utf8")
    size = f'cx="{picture["cx"]}" cy="{picture["cy"]}"'
    xml = re.sub(r'<wp:extent cx="\d+" cy="\d+"/>', f"<wp:extent {size}/>", xml)
    xml = re.sub(r'<a:ext cx="\d+" cy="\d+"/>', f"<a:ext {size}/>", xml)
    xml = xml.replace('<w:jc w:val="left"/>', f'<w:jc w:val="{picture["align"]}"/>', 1)
    return xml.encode("utf8")


def _local_path(url: str) -> str | None:
    """Disk path of a site file url (/files/... or /private/files/...)."""
    url = unquote((url or "").split("?")[0])
    if url.startswith("/private/files/"):
        path = frappe.get_site_path(url.lstrip("/"))
    elif url.startswith("/files/"):
        path = frappe.get_site_path("public", url.lstrip("/"))
    else:
        return None
    path = os.path.abspath(path)
    return path if os.path.isfile(path) else None


def _open_file(url: str) -> Image.Image | None:
    path = _local_path(url)
    if not path:
        return None
    try:
        img = Image.open(path)
        img.load()
    except Exception:
        # Not a raster image (e.g. SVG) - the caller falls back to the HTML.
        return None
    return img


def _render_html(html: str) -> Image.Image | None:
    """Photograph letter head HTML at the content width, trimmed top and bottom."""

    def local_src(match):
        path = _local_path(match.group(2))
        return f"{match.group(1)}file://{path}{match.group(3)}" if path else match.group(0)

    html = re.sub(r'(src=["\'])(/[^"\']+)(["\'])', local_src, html)
    page = (
        '<html><head><meta charset="utf-8"><style>'
        "html,body{margin:0;padding:0;background:#fff;}"
        "body{font-family:Arial,Helvetica,sans-serif;font-size:12px;}"
        "img{max-width:100%;}"
        f"</style></head><body>{html}</body></html>"
    )

    with tempfile.TemporaryDirectory(prefix="quotation_lh_") as tmp:
        src, out = os.path.join(tmp, "lh.html"), os.path.join(tmp, "lh.png")
        with open(src, "w", encoding="utf8") as f:
            f.write(page)
        try:
            subprocess.run(
                [
                    "wkhtmltoimage", "--quiet", "--format", "png",
                    "--width", str(CONTENT_WIDTH_PX * HTML_ZOOM), "--zoom", str(HTML_ZOOM),
                    "--disable-smart-width", "--enable-local-file-access",
                    src, out,
                ],
                check=True, timeout=60, capture_output=True,
            )
            img = Image.open(out).convert("RGB")
        except (OSError, subprocess.SubprocessError):
            frappe.log_error(title="Quotation Format: letter head render failed")
            return None

    # Keep the full width so left/centre/right alignment survives; trim only
    # the blank rows above and below the content.
    box = ImageChops.difference(img, Image.new("RGB", img.size, (255, 255, 255))).getbbox()
    if not box:
        return None
    return img.crop((0, box[1], img.width, box[3]))
