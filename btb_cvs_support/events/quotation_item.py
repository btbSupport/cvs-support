import frappe
from ..api.site_info import *
@frappe.whitelist()
def before_upsert(doc, method = None):
    print('get_config allow_cpq before save quote item',get_config('allow_cpq') )
    if(get_config('allow_cpq')==None or get_config('allow_cpq') == 0): return
    print("calling quote line item sync ",doc)
    print("calling quote line item sync doc.custom_cart_item ",doc.custom_cart_item)

    sql = f"""
          select a.title,
 GROUP_CONCAT(CASE WHEN field = 'modelItem' THEN item_code END) AS item_code,
 GROUP_CONCAT(CASE WHEN field = 'modelItem' THEN stock_uom END) AS stock_uom,
 GROUP_CONCAT(CASE WHEN field = 'tagRef' THEN cifValue END) AS tagRef,
 GROUP_CONCAT(CASE WHEN field = 'notes' THEN cifValue END) AS notes 
 from (
 SELECT i.item_code,i.stock_uom,tbci.title,tbf.field,tbcif.value cifValue,tbfti.value
from tabBtbCartItem tbci 
 join tabBtbCartItemFeature tbcif on tbci.name = '{doc.custom_cart_item}' and tbcif.parent  = tbci.name
 join tabBtbFeature tbf  on tbf.name = tbcif.feature  and tbf.field in('modelItem','tagRef','notes')
 left join tabBtbFeatureTypeItem tbfti on  tbfti.name = tbcif.value
 left join `tabItem` i on i.name = tbfti.`object`) a 
  
    """
    print("calling quote line item sync sql",sql)

    items = frappe.db.sql(sql, as_dict=1)
    if len(items) > 0 :
        item = items[0]
        print("items inside qli ",items)
        doc.description = item.title
        if(item.item_code):doc.item_code = item.item_code
        if(item.stock_uom):doc.uom = item.stock_uom
        doc.tag_ref = item.tagRef
        doc.notes = item.notes
        
def on_trash(doc, method = None):
    print("calling quote line item delete ",doc)