import frappe
from ..api.site_info import *
@frappe.whitelist()
def before_upsert(doc, method = None):
    print('get_config allow_cpq before save quote item',get_config('allow_cpq') )
    if(get_config('allow_cpq')==None or get_config('allow_cpq') == 0): return
    print("calling quote line item sync ",doc)
    print("calling quote line item sync doc.custom_cart_item ",doc.custom_cart_item)

    sql = f"""
         select i.item_code,i.description,i.stock_uom,tbci.title from tabBtbCartItemFeature tbcif 
        join tabBtbFeature tbf  on tbf.name = tbcif.feature  and tbf.field ='modelItem'
        join tabBtbFeatureTypeItem tbfti on tbcif.value = tbfti.name
        join `tabItem` i on tbfti.`object`  = i.name
        join tabBtbCartItem tbci on tbci.name  = '{doc.custom_cart_item}'
        where tbcif.parent  = '{doc.custom_cart_item}'
    """
    print("calling quote line item sync sql",sql)

    items = frappe.db.sql(sql, as_dict=1)
    if len(items) > 0 :
        print("items inside qli ",items)
        doc.item_code = items[0].item_code
        doc.description = items[0].title
        doc.uom = items[0].stock_uom
        
def on_trash(doc, method = None):
    print("calling quote line item delete ",doc)