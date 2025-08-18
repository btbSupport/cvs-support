import frappe
from ..api.site_info import *
@frappe.whitelist()
def before_upsert(doc, method = None):
    if(get_config('allow_cpq')==None or get_config('allow_cpq') == 0): return
    sql = f"""
          select a.title,a.idx,a.ciItemCode,
 GROUP_CONCAT(CASE WHEN field = 'modelItem' THEN item_code END) AS item_code,
 GROUP_CONCAT(CASE WHEN field = 'modelItem' THEN stock_uom END) AS stock_uom,
 GROUP_CONCAT(CASE WHEN field = 'tagRef' THEN cifValue END) AS tagRef,
 GROUP_CONCAT(CASE WHEN field = 'notes' THEN cifValue END) AS notes ,
 GROUP_CONCAT(CASE WHEN field = 'notesInput' THEN cifValue END) AS notesInput
 from (
 SELECT i.item_code,i.stock_uom,tbci.title,tbf.field,tbcif.value cifValue,tbfti.value,tbci.idx,ci.item_code ciItemCode
from tabBtbCartItem tbci 
 join tabBtbCartItemFeature tbcif on tbci.name = '{doc.custom_cart_item}' and tbcif.parent  = tbci.name
 join tabBtbFeature tbf  on tbf.name = tbcif.feature  and tbf.field in('modelItem','tagRef','notes','notesInput')
 left join tabBtbFeatureTypeItem tbfti on  tbfti.name = tbcif.value
 left join `tabItem` i on i.name = tbfti.`object`
 left join `tabItem` ci on ci.name = tbci.item) a 
    """
    print("calling quote line item sync sql",sql)

    items = frappe.db.sql(sql, as_dict=1)
    if len(items) > 0 :
        item = items[0]
        print("items inside qli ",items)
        doc.idx = item.idx
        doc.description = item.title
        if(item.item_code):doc.item_code = item.item_code
        if(item.stock_uom):doc.uom = item.stock_uom
        doc.tag_ref = item.tagRef
        if(item.ciItemCode == 'ULRD' or item.ciItemCode == 'SIL' or item.ciItemCode == 'VCDA'): 
            if('notesInput' in item) : doc.notes = item.notesInput
        elif('notes' in item) : doc.notes = item.notes
        
def on_trash(doc, method = None):
    print("calling quote line item delete ",doc)