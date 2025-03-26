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
    net_total = 0
    total_sqm = 0
    total_pcs = 0
    items = frappe.db.sql(sql, as_dict=1)
    if(len(items) > 0):
        net_total = items[0].net_total
        total_sqm = items[0].total_sqm
        total_pcs = items[0].total_pcs
    frappe.db.set_value('Order Processing Request', doc.opr_no, {
        "invoiced_value": net_total,
        "total_sqm_delivered": total_sqm,
        "total_nos_delivered": total_pcs
    })
    return doc