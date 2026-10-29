import requests
import json
import os
import re
import frappe
from decimal import Decimal


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
ONEDOC_TIMEOUT = 60  # seconds

def fetch_document(url: str, data: dict, template_path: str, output_format: str) -> bytes:
    """Renders the template through OneDoc. Waits at most ONEDOC_TIMEOUT, retries once
    when the connection drops, and refuses anything that isn't the requested document,
    so an error page is never saved as the PDF. A timeout isn't retried: two would
    outlast the web worker's own timeout."""
    for attempt in (1, 2):
        try:
            with open(template_path, "rb") as template:
                response = requests.post(url, data = data, files = {"file": template}, timeout = ONEDOC_TIMEOUT)
            break
        except requests.Timeout:
            frappe.log_error(title="OneDoc timed out")
            frappe.throw(frappe._("The document service took too long to respond. Please try again in a moment."))
        except requests.ConnectionError:
            if(attempt == 2):
                frappe.log_error(title="OneDoc unavailable")
                frappe.throw(frappe._("The document service is unavailable. Please try again in a moment."))
    is_pdf = response.content[:5] == b"%PDF-"
    if(response.status_code != 200 or (output_format == "pdf" and not is_pdf)):
        frappe.log_error(title="OneDoc returned an error",
                         message=f"HTTP {response.status_code}\n{response.content[:2000]!r}")
        frappe.throw(frappe._("The document service could not create the document. Please try again in a moment."))
    return response.content

def generate(template_path:str, datasource: dict, **kwargs):
    url = "https://onesign.digital/onedoc/convert"
    # url = "https://docs.onedoc.ca/onedoc/convert"
    data = {
        "dataSource": json.dumps(datasource,default=decimal_serializer),
        "outputFormat": kwargs.get("format", ""),
        "settings":json.dumps(
            {
                "addDigitalSignature":kwargs.get("addDigitalSignature", False)
                })
    }
    content = fetch_document(url, data, template_path, kwargs.get("format", ""))
    file_name =  kwargs.get("file_name", "output.pdf")
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
    
    
if(__name__ == "__main__"):
    generate("templates/quotation.docx", {"quote": {"name": "Test"}}, format="pdf")