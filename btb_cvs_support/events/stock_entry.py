import frappe

def after_upsert(doc, method = None):
    print(doc.doctype)
    #if(doc.docstatus != 1):
        #return;
    sql = f"""
        select sum(value_difference) total from `tabStock Entry` where custom_opr='{doc.custom_opr}' and docstatus = 1
        and stock_entry_type = 'Material Issue'
    """
    item = frappe.db.sql(sql, as_dict=1)[0]
    frappe.db.set_value("Order Processing Request", doc.custom_opr, "consumption_value", item.total or 0)
    return doc