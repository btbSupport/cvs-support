import frappe
from . import onecpq_quote
from ..api.site_info import *
def before_save(doc, method = None):
    print('doc : ',doc)
    print('method : ',method)
#     if(doc.reference_doctype == "Quotation"):
#         if(get_config('allow_cpq')==None or get_config('allow_cpq') == 0): return
#         quoteDoc = frappe.get_doc(doc.reference_doctype, doc.reference_name)
#         if(quoteDoc.custom_customizable ==1) : onecpq_quote.lock_cart(doc.reference_name,doc.workflow_state)
#         return