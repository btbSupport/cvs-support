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
    files = {
        "file": open(template_path, "rb")
    }
    response = requests.post(url, data = data, files = files)
    file_name =  kwargs.get("file_name", "output.pdf")
    file_url = '/private/files/'+file_name
    file_path = frappe.utils.get_bench_path()+'/sites/'+frappe.utils.get_site_base_path()[2:]+file_url
    with open(file_path, "wb") as f:
        f.write(response.content)

    file_doc = frappe.new_doc("File")
    file_doc.file_name = file_name
    file_doc.folder = "Home"
    file_doc.is_private = 1
    file_doc.file_url = file_url
    if("doc_type" in kwargs.keys()):
        file_doc.attached_to_doctype = kwargs.get("doc_type", ""),
        file_doc.attached_to_name =  kwargs.get("doc_name", "")
    file_doc.save()
    
    
if(__name__ == "__main__"):
    generate("templates/quotation.docx", {"quote": {"name": "Test"}}, format="pdf")