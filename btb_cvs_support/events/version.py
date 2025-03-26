import frappe
from . import delivery_note
from . import stock_entry


def after_upsert(doc, method = None):
    if(doc.ref_doctype == "Delivery Note"):
        doc = frappe.get_doc(doc.ref_doctype, doc.docname)
        delivery_note.after_upsert(doc)
        return
    if(doc.ref_doctype == "Stock Entry"):
        doc = frappe.get_doc(doc.ref_doctype, doc.docname)
        stock_entry.after_upsert(doc)
        return

    
    
