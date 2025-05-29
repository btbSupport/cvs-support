import frappe

def after_upsert(doc, method = None):
    print("calling quote line item sync ",doc)
    # sql = f"""
    #    select description  from tabItem ti where item_code = '{doc.item_code}'
    # """
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
        # itemCode = items[0].title.split('|')[0]
        # description = items[0].title.split('|')[1]
        quoteItem = frappe.frappe.get_doc("Quotation Item", doc)
        # quoteItem.item_code = itemCode
        # quoteItem.description = description
        quoteItem.item_code = items[0].item_code
        quoteItem.description = items[0].description
        quoteItem.uom = items[0].stock_uom
        quoteItem.db_update()