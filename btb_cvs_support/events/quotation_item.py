import frappe

def after_upsert(doc, method = None):
    print("calling quote line item sync ",doc)
    frappe.log(doc)
    sql = f"""
        select i.item_code,i.description,i.stock_uom from tabBtbCartItemFeature tbcif 
        join tabBtbFeature tbf  on tbf.name = tbcif.feature  and tbf.field ='modelItem'
        join tabBtbFeatureTypeItem tbfti on tbcif.value = tbfti.name
        join `tabItem` i on tbfti.`object`  = i.name
        where tbcif.parent  = '{doc.custom_cart_item}'
    """
    items = frappe.db.sql(sql, as_dict=1)
    if len(items) > 0 :
        print("items inside qli ",items)
        doc.item_code = items[0].item_code
        doc.description = items[0].description
        doc.uom = items[0].stock_uom
        frappe.log(doc)