import frappe


def after_upsert(doc, method = None):
    if(doc.doctype == "Version"):
        if(doc.ref_doctype == "Delivery Note"):
            doc = frappe.get_doc(doc.ref_doctype, doc.docname)
        else:
            return
    sql = f"""
        select sum(net_total) net_total, sum(total_sqm1) total_sqm, sum(total_pcs1) total_pcs from `tabDelivery Note` where opr_no='{doc.opr_no}'
        and docstatus = 1
    """
    print("Calling update")
    item = frappe.db.sql(sql, as_dict=1)[0]
    print(doc.opr_no, item.net_total, item.total_sqm)
    frappe.db.set_value('Order Processing Request', doc.opr_no, {
        "invoiced_value": item.net_total,
        "total_sqm_delivered": item.total_sqm,
        "total_nos_delivered": item.total_pcs
    })
    return doc