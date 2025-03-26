import frappe

def after_upsert(doc, method = None):
    print(doc.doctype)
    #if(doc.docstatus != 1):
        #return;
    sql = f"""
        select sum(value_difference) total from `tabStock Entry` where opr_no='{doc.opr_no}' and docstatus = 1
        and stock_entry_type = 'Material Issue'
    """
    items = frappe.db.sql(sql, as_dict=1)
    total =  0 if len(items) == 0 else items[0].total
    frappe.db.set_value("Order Processing Request", doc.opr_no, "consumption_value", total)
    return doc