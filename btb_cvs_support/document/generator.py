import requests
import json
import frappe
from decimal import Decimal


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