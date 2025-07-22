import frappe
from . import onecpq_quote
def before_save(doc, method = None):
    print('doc : ',doc)
    print('method : ',method)
    if(doc.reference_doctype == "Quotation"):
        quoteDoc = frappe.get_doc(doc.reference_doctype, doc.reference_name)
        if(quoteDoc.custom_customizable ==1) : onecpq_quote.lock_cart(doc.reference_name,doc.workflow_state)
        return