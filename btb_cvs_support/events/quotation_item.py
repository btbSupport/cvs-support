import frappe
from ..api.site_info import *
@frappe.whitelist()
def before_upsert(doc, method = None):
    if(get_config('allow_cpq')==None or get_config('allow_cpq') == 0 or doc.custom_cart_item == None): return
#     sql = f"""
#  SELECT ci.item_code,ci.stock_uom,tbci.title,tbci.idx
# from tabBtbCartItem tbci  
# join `tabItem` ci on tbci.name = '{doc.custom_cart_item}' and ci.name = tbci.item
#     """
   
    # if(doc.custom_configurable == 1):
    sql = f"""
        select cartItem.*,GROUP_CONCAT(CASE WHEN field = 'modelItem' THEN item_code END) AS model_item_code,
            GROUP_CONCAT(CASE WHEN field = 'modelItem' THEN stock_uom END) AS model_stock_uom,
            GROUP_CONCAT(CASE WHEN field = 'tagRef' THEN cifValue END) AS tagRef,
            GROUP_CONCAT(CASE WHEN field = 'notes' THEN cifValue END) AS notes ,
            GROUP_CONCAT(CASE WHEN field = 'notesInput' THEN cifValue END) AS notesInput from  
                (SELECT ci.item_code ciItemCode,ci.stock_uom ciStockUom,tbci.title ciTitle,tbci.idx ciIdx,tbci.name ciName,tbci.custom_configurable
                from tabBtbCartItem tbci  
                join `tabItem` ci on tbci.name = '{doc.custom_cart_item}' and ci.name = tbci.item) 
            cartItem
             left join  (select i.item_code,i.stock_uom,tbf.field,tbcif.value cifValue,tbfti.value,tbcif.parent from tabBtbCartItemFeature tbcif  
                join tabBtbFeature tbf  on  tbcif.parent  = '{doc.custom_cart_item}' and tbf.name = tbcif.feature  and tbf.field in('modelItem','tagRef','notes','notesInput')
                left join tabBtbFeatureTypeItem tbfti on  tbfti.name = tbcif.value
                left join `tabItem` i on i.name = tbfti.`object`) 
            config 
            on cartItem.ciName = config.parent
        """
    # sql = f"""
    #         select a.title,a.idx,a.ciItemCode,
    # GROUP_CONCAT(CASE WHEN field = 'modelItem' THEN item_code END) AS item_code,
    # GROUP_CONCAT(CASE WHEN field = 'modelItem' THEN stock_uom END) AS stock_uom,
    # GROUP_CONCAT(CASE WHEN field = 'tagRef' THEN cifValue END) AS tagRef,
    # GROUP_CONCAT(CASE WHEN field = 'notes' THEN cifValue END) AS notes ,
    # GROUP_CONCAT(CASE WHEN field = 'notesInput' THEN cifValue END) AS notesInput
    # from (
    # SELECT i.item_code,i.stock_uom,tbci.title,tbf.field,tbcif.value cifValue,tbfti.value,tbci.idx,ci.item_code ciItemCode
    # from tabBtbCartItem tbci 
    # join tabBtbCartItemFeature tbcif on tbci.name = '{doc.custom_cart_item}' and tbcif.parent  = tbci.name
    # join tabBtbFeature tbf  on tbf.name = tbcif.feature  and tbf.field in('modelItem','tagRef','notes','notesInput')
    # left join tabBtbFeatureTypeItem tbfti on  tbfti.name = tbcif.value
    # left join `tabItem` i on i.name = tbfti.`object`
    # left join `tabItem` ci on ci.name = tbci.item) a 
    #     """
    print("calling quote line item sync sql",sql)

    items = frappe.db.sql(sql, as_dict=1)
    if len(items) > 0 :
        item = items[0]
        print("items inside qli ",items)
        if(item.ciIdx == None): return
        doc.idx = item.ciIdx
        doc.description = item.ciTitle
        if(item.custom_configurable == 1):
            if(item.model_item_code):doc.item_code = item.model_item_code
            if(item.model_stock_uom):doc.uom = item.model_stock_uom
            if('tagRef' in item) : doc.tag_ref = item.tagRef
            if('ciItemCode' in item):
                if(item.ciItemCode == 'ULRD' or item.ciItemCode == 'SIL' or item.ciItemCode == 'VCDA'): 
                    if('notesInput' in item) : doc.notes = item.notesInput
                elif('notes' in item) : doc.notes = item.notes
        else :
            if(item.ciItemCode):doc.item_code = item.ciItemCode
            if(item.ciStockUom):doc.uom = item.ciStockUom
        
def on_trash(doc, method = None):
    print("calling quote line item delete ",doc)