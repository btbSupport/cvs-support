import requests
import json
import os
import re
import sys
import frappe
from decimal import Decimal

from .converter import convert_docx_content_to_pdf, is_pdf


def delete_existing_attachment(doc_type: str, doc_name: str, file_name: str):
    """Remove the previously generated `file_name` attachment from a document.

    generate() always asks for the same file name for a given source document,
    but Frappe appends the tail of the content hash when that name is already
    taken on disk, so what is stored is `<stem><hash><ext>` and never matches
    the requested name exactly. Allow that hex tail - and nothing else - so a
    document named like a prefix of another cannot be swept up.
    """
    if(not doc_type or not doc_name or not file_name): return
    stem, ext = os.path.splitext(file_name)
    pattern = re.compile("^%s[0-9a-f]*%s$" % (re.escape(stem), re.escape(ext)))
    existing = frappe.get_all("File",
        filters={"attached_to_doctype": doc_type, "attached_to_name": doc_name},
        fields=["name", "file_name"])
    for f in existing:
        if(pattern.match(f.get("file_name") or "")):
            frappe.delete_doc("File", f.get("name"), force=1, ignore_permissions=True)


def decimal_serializer(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError('Type not serializable + '+obj)

ONEDOC_URL = "https://onesign.digital/onedoc/convert"
# ONEDOC_URL = "https://docs.onedoc.ca/onedoc/convert"
ONEDOC_TIMEOUT = 60  # seconds

def _payload(datasource: dict, output_format: str, **kwargs) -> dict:
    return {
        "dataSource": json.dumps(datasource,default=decimal_serializer),
        "outputFormat": output_format,
        "settings":json.dumps(
            {
                "addDigitalSignature":kwargs.get("addDigitalSignature", False)
                })
    }

def _post(data: dict, template_path: str, timeout=ONEDOC_TIMEOUT) -> requests.Response:
    """POST the template to OneDoc, retrying once when the connection drops.
    Raises requests exceptions; a timeout isn't retried."""
    for attempt in (1, 2):
        try:
            with open(template_path, "rb") as template:
                return requests.post(ONEDOC_URL, data = data, files = {"file": template}, timeout = timeout)
        except requests.ConnectionError:
            if(attempt == 2): raise

def fetch_document(url: str, data: dict, template_path: str, output_format: str) -> bytes:
    """Renders the template through OneDoc. Waits at most ONEDOC_TIMEOUT, retries once
    when the connection drops, and refuses anything that isn't the requested document,
    so an error page is never saved as the PDF. A timeout isn't retried: two would
    outlast the web worker's own timeout."""
    try:
        response = _post(data, template_path)
    except requests.Timeout:
        frappe.log_error(title="OneDoc timed out")
        frappe.throw(frappe._("The document service took too long to respond. Please try again in a moment."))
    except requests.ConnectionError:
        frappe.log_error(title="OneDoc unavailable")
        frappe.throw(frappe._("The document service is unavailable. Please try again in a moment."))
    if(response.status_code != 200 or (output_format == "pdf" and not is_pdf(response.content))):
        frappe.log_error(title="OneDoc returned an error",
                         message=f"HTTP {response.status_code}\n{response.content[:2000]!r}")
        frappe.throw(frappe._("The document service could not create the document. Please try again in a moment."))
    return response.content

# Frappe (16.55+) checks every PDF for JavaScript before saving it (File.check_content
# -> pdf_contains_js), walking the PDF object graph recursively. The quotation templates
# carry an outline level on their line paragraphs, so the PDF has one bookmark per line,
# and bookmarks are a linked list (/Next -> /Next ...): one stack frame each. A 930-line
# quotation is ~955 deep, just under Python's default 1000; anything larger failed with
# "PdfReadError: RecursionError('maximum recursion depth exceeded')" (QTN-26-4108).
# Raised for the whole process and never lowered again: restoring it while another
# thread of the same worker is mid-scan would break that thread's save instead.
PDF_SCAN_RECURSION_LIMIT = 20000

def _allow_deep_pdf_scan():
    if(sys.getrecursionlimit() < PDF_SCAN_RECURSION_LIMIT):
        sys.setrecursionlimit(PDF_SCAN_RECURSION_LIMIT)

def _save(content: bytes, **kwargs) -> str:
    file_name =  kwargs.get("file_name", "output.pdf")
    if(file_name.lower().endswith(".pdf")): _allow_deep_pdf_scan()
    # Replace the previous copy only now that the new one is in hand, so a failed render
    # leaves it in place (ADR-0001 amendment, 2026-10-29). Done before writing: the old
    # File row must not take the newly written file with it.
    if(kwargs.get("replace_existing") and "doc_type" in kwargs.keys()):
        delete_existing_attachment(kwargs.get("doc_type"), kwargs.get("doc_name"), file_name)
    file_url = '/private/files/'+file_name
    file_path = frappe.utils.get_bench_path()+'/sites/'+frappe.utils.get_site_base_path()[2:]+file_url
    with open(file_path, "wb") as f:
        f.write(content)

    file_doc = frappe.new_doc("File")
    file_doc.file_name = file_name
    file_doc.folder = "Home"
    file_doc.is_private = 1
    file_doc.file_url = file_url
    if("doc_type" in kwargs.keys()):
        file_doc.attached_to_doctype = kwargs.get("doc_type", "")
        file_doc.attached_to_name =  kwargs.get("doc_name", "")
    file_doc.save()
    # the stored url carries Frappe's content-hash suffix, so callers must use this one
    return file_doc.file_url

def generate(template_path:str, datasource: dict, **kwargs):
    output_format = kwargs.get("format", "")
    content = fetch_document(ONEDOC_URL, _payload(datasource, output_format, **kwargs), template_path, output_format)
    return _save(content, **kwargs)

# ---------------------------------------------------------------------------
# OneDoc PDF with a background LibreOffice fallback.
#
# Same idea as icon_support's v15 ADR-0130, moved off the web request. OneDoc
# abandons its own PDF conversion at about 60s, which large quotations (thousands
# of cart lines) reach. The request still tries OneDoc's PDF first, so normal
# documents open straight away exactly as before. When that fails, a job on the
# long queue asks OneDoc for the filled "original" .docx - which skips OneDoc's
# PDF step - converts it here with LibreOffice (converter.py), attaches it, and
# notifies the user (realtime alert + Notification Log).
#
# Endpoints hand over a *builder*: a function, by dotted path, that returns the
# render spec for a document. The job calls it again instead of receiving the
# datasource, so nothing multi-MB goes through Redis and the Letter Head temp
# template is built and removed by whoever uses it. A builder returns
#
#     {"template": path, "datasource": {...}, "kwargs": {...generate kwargs...},
#      "cleanup": temp path or None, "row_count": int, "response": {...}}
#
# or anything without "template" (None, {"status": "Nothing to generate"}),
# which is returned to the caller unchanged.
# ---------------------------------------------------------------------------

# Seconds, per step, inside the background job: OneDoc's "original" render and the
# LibreOffice conversion each get this long. Not measured on 2,900 rows yet - tune
# from the "OneDoc PDF fallback" Error Logs.
FALLBACK_TIMEOUT = 300
# RQ job timeout: the rebuild plus both steps above, with headroom.
FALLBACK_JOB_TIMEOUT = 900
DOCUMENT_READY_EVENT = "btb_document_ready"


def fallback_job_id(doc_type: str, doc_name: str, file_name: str) -> str:
    # One job per document *and* output: a Quotation's BOQ and Quotation Format are separate.
    return "onedoc-fallback::%s::%s::%s" % (doc_type, doc_name, file_name)


def generate_or_queue(builder: str, builder_kwargs: dict, doc_type: str, doc_name: str,
                      file_name: str, label: str):
    """Render a document through OneDoc as a PDF; if OneDoc can't, queue the local fallback.

    Returns the builder's "response" plus either {"status": "Success", "file_url": ...}
    or {"status": "Queued", "message": ...}.
    """
    from frappe.utils.background_jobs import is_job_enqueued

    job_id = fallback_job_id(doc_type, doc_name, file_name)
    if(is_job_enqueued(job_id)):
        # A large document is already being made: don't spend another 60s on OneDoc.
        return {"status": "Queued", "message": _queued_message(label, doc_name, already=True)}

    spec = frappe.get_attr(builder)(**builder_kwargs)
    if(not spec or "template" not in spec): return spec
    response = dict(spec.get("response") or {})
    kwargs = dict(spec["kwargs"], format="pdf")

    try:
        try:
            result = _post(_payload(spec["datasource"], "pdf", **kwargs), spec["template"])
            if(result.status_code == 200 and is_pdf(result.content)):
                response.update(status="Success", file_url=_save(result.content, **kwargs))
                return response
            reason = "OneDoc returned HTTP %s, not a PDF (%d bytes): %r" % (
                result.status_code, len(result.content or b""), result.content[:200])
        except requests.RequestException as e:
            reason = "OneDoc request failed: %s" % e
    finally:
        _cleanup(spec)

    frappe.log_error(
        title="OneDoc PDF fallback",
        message="document: %s %s\nfile: %s\nrows: %s\ntemplate: %s\nreason: %s\nqueued as: %s" % (
            doc_type, doc_name, file_name, spec.get("row_count"), spec["template"], reason, job_id),
        reference_doctype=doc_type, reference_name=doc_name)
    frappe.enqueue("btb_cvs_support.document.generator.run_fallback",
                   queue="long", timeout=FALLBACK_JOB_TIMEOUT,
                   job_id=job_id, deduplicate=True,
                   builder=builder, builder_kwargs=builder_kwargs,
                   doc_type=doc_type, doc_name=doc_name, file_name=file_name, label=label)
    response.update(status="Queued", message=_queued_message(label, doc_name))
    return response


def run_fallback(builder: str, builder_kwargs: dict, doc_type: str, doc_name: str,
                 file_name: str, label: str):
    """Background job: rebuild the document, fill it at OneDoc as .docx, convert it here.

    Runs as the user who clicked (frappe.enqueue carries the session user), who is
    the one notified either way. A non-PDF is never stored, and a failure leaves the
    previous attachment in place (ADR-0001 amendment).
    """
    user = frappe.session.user
    spec = None
    try:
        spec = frappe.get_attr(builder)(**builder_kwargs)
        if(not spec or "template" not in spec):
            raise Exception("Nothing to generate when the job ran")
        kwargs = dict(spec["kwargs"], format="pdf")
        result = _post(_payload(spec["datasource"], "original", **kwargs), spec["template"],
                       timeout=FALLBACK_TIMEOUT)
        if(result.status_code != 200):
            raise Exception("OneDoc returned HTTP %s for the original: %r" % (
                result.status_code, result.content[:200]))
        pdf = convert_docx_content_to_pdf(result.content, file_name=file_name, timeout=FALLBACK_TIMEOUT)
        file_url = _save(pdf, **kwargs)
    except Exception as e:
        frappe.db.rollback()
        frappe.local.message_log = []
        frappe.log_error(
            title="OneDoc PDF fallback failed",
            message="document: %s %s\nfile: %s\nrows: %s\nfailure: %s" % (
                doc_type, doc_name, file_name, spec and spec.get("row_count"),
                frappe.utils.strip_html(str(e)) or e.__class__.__name__),
            reference_doctype=doc_type, reference_name=doc_name)
        _notify(user, doc_type, doc_name, label, None)
        frappe.db.commit()
        return
    finally:
        if(spec): _cleanup(spec)
    _notify(user, doc_type, doc_name, label, file_url)


def _queued_message(label: str, doc_name: str, already: bool = False) -> str:
    if(already):
        return frappe._("{0} for {1} is already being prepared. You will be notified when it is attached.").format(label, doc_name)
    return frappe._("{0} for {1} is large and is being prepared in the background. You will be notified when it is attached.").format(label, doc_name)


def _notify(user: str, doc_type: str, doc_name: str, label: str, file_url):
    """Bell entry (kept even if the user has closed the form) + realtime alert."""
    if(file_url):
        title = frappe._("{0} for {1} is ready").format(label, doc_name)
    else:
        title = frappe._("{0} for {1} could not be generated. Please try again or contact support.").format(label, doc_name)
    log = frappe.new_doc("Notification Log")
    log.update({"for_user": user, "type": "Alert", "title": title,
                "document_type": doc_type, "document_name": doc_name})
    if(file_url): log.link = file_url
    log.insert(ignore_permissions=True)
    frappe.publish_realtime(DOCUMENT_READY_EVENT, user=user, after_commit=True, message={
        "doctype": doc_type, "name": doc_name, "label": label,
        "file_url": file_url, "title": title})


def _cleanup(spec: dict):
    path = spec.get("cleanup")
    if(path and os.path.exists(path)): os.remove(path)


if(__name__ == "__main__"):
    generate("templates/quotation.docx", {"quote": {"name": "Test"}}, format="pdf")
