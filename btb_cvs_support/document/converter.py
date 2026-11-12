"""Convert a finished .docx to PDF locally, with LibreOffice.

Ported from icon_support (v15, ADR-0130) for the OneDoc fallback in
`generator.run_fallback` (a background job): when OneDoc cannot render a large
document as a PDF, it still fills the template and returns the .docx
("original"), and the PDF is made here instead.

Requires LibreOffice on the bench host - it runs in the long-queue worker::

    apt-get install libreoffice-writer fonts-crosextra-carlito \\
                    fonts-crosextra-caladea fonts-liberation

The font packages are metric-compatible stand-ins for Calibri, Cambria and
Arial/Times; without them LibreOffice substitutes fonts of a different width and
the quotation reflows.

Self-contained on purpose: nothing is imported from `generator`, so there is no
import cycle between the two modules.
"""

import os
import shutil
import subprocess
import tempfile

import frappe
from frappe import _

SOFFICE_BINARIES = ("soffice", "libreoffice")

# Seconds. Sized to kill a LibreOffice that has hung, not to wait on a slow one.
# The background fallback passes its own, longer limit (generator.FALLBACK_TIMEOUT).
SOFFICE_TIMEOUT = 90


def is_pdf(content) -> bool:
    return bool(content) and bytes(content[:5]) == b"%PDF-"


def convert_docx_content_to_pdf(content: bytes, file_name: str = None, timeout: int = SOFFICE_TIMEOUT) -> bytes:
    """Convert .docx bytes (e.g. what OneDoc returned for format="original") to PDF bytes.

    `file_name` is only used in error messages. Raises (frappe.throw) when the
    content is not a Word document, LibreOffice is missing or times out, or no
    PDF comes out.
    """
    label = file_name or "document.docx"
    if isinstance(content, (bytearray, memoryview)):
        content = bytes(content)

    # A .docx is a zip. LibreOffice imports anything else as plain text, exits 0
    # and returns a valid PDF of garbage, e.g. a OneDoc error page.
    if not isinstance(content, bytes) or content[:2] != b"PK":
        frappe.throw(_("{0} is not a valid Word document.").format(label))

    tmp = tempfile.mkdtemp(prefix="docx2pdf-")
    try:
        source = os.path.join(tmp, "input.docx")
        with open(source, "wb") as f:
            f.write(content)
        return _soffice_convert(source, tmp, label, timeout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _soffice_convert(source: str, tmp: str, label: str, timeout: int = SOFFICE_TIMEOUT) -> bytes:
    soffice = _soffice_binary()
    # Everything stays in `tmp`. The private profile (-env:UserInstallation)
    # matters: workers sharing ~/.config/libreoffice lock each other out, and the
    # loser exits 0 having converted nothing.
    command = [
        soffice,
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--nodefault",
        "-env:UserInstallation=file://" + os.path.join(tmp, "profile"),
        "--convert-to", "pdf:writer_pdf_Export",
        "--outdir", tmp,
        source,
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout,
                                # the worker user's home is not guaranteed writable
                                env=dict(os.environ, HOME=tmp))
    except subprocess.TimeoutExpired:
        frappe.throw(_("Converting {0} to PDF timed out after {1} seconds.")
                     .format(label, timeout))

    output = os.path.join(tmp, os.path.splitext(os.path.basename(source))[0] + ".pdf")
    if not os.path.isfile(output):
        # soffice reports a refused conversion on stdout and still exits 0
        frappe.log_error(
            title="docx to PDF conversion failed",
            message="document: %s\ncommand: %s\nreturncode: %s\nstdout: %s\nstderr: %s" % (
                label, " ".join(command), result.returncode,
                result.stdout.decode(errors="replace"),
                result.stderr.decode(errors="replace")),
            defer_insert=True)
        frappe.throw(_("Could not convert {0} to PDF.").format(label))

    with open(output, "rb") as f:
        content = f.read()
    if not is_pdf(content):
        frappe.throw(_("Could not convert {0} to PDF.").format(label))
    return content


def _soffice_binary() -> str:
    # An install that isn't on PATH, e.g. the official LibreOffice .deb in
    # /opt/libreoffice25.2: `bench set-config -g soffice_path /opt/libreoffice25.2/program/soffice`
    configured = frappe.conf.get("soffice_path")
    if configured and os.access(configured, os.X_OK):
        return configured
    for name in SOFFICE_BINARIES:
        path = shutil.which(name)
        if path:
            return path
    frappe.throw(_("LibreOffice is not installed on this server, so the document "
                   "cannot be converted to PDF. Install it with: "
                   "apt-get install libreoffice-writer"))
