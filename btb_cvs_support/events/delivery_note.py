import frappe
from ..api.opr import update_opr


def after_upsert(doc, method = None):
    print('Delivery Note Test')
    if(doc.doctype == "Version"):
        if(doc.ref_doctype == "Delivery Note"):
            doc = frappe.get_doc(doc.ref_doctype, doc.docname)
        else:
            return
    if doc.custom_opr:
        update_opr(doc.custom_opr)

    # def after_upsert(doc, method = None):
    # if(doc.doctype == "Version"):
    #     if(doc.ref_doctype == "Delivery Note"):
    #         doc = frappe.get_doc(doc.ref_doctype, doc.docname)
    #     else:
    #         return
    # sql = f"""
    #     select sum(base_net_total) net_total, sum(custom_total_sqm) custom_total_sqm, sum(custom_total_pcs) custom_total_pcs from `tabDelivery Note` where custom_opr='{doc.custom_opr}'
    #     and docstatus = 1
    # """
    # print("Calling update")
    # item = frappe.db.sql(sql, as_dict=1)[0]
    # net_total = item.net_total or 0
    # total_sqm = item.custom_total_sqm or 0
    # total_pcs = item.custom_total_pcs or 0
    # frappe.db.set_value('Order Processing Request', doc.custom_opr, {
    #     "invoiced_value": net_total,
    #     "total_sqm_delivered": total_sqm,
    #     "total_nos_delivered": total_pcs
    # })
    # return doc


