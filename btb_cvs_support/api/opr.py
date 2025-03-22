import frappe
#DEV API Key = dd017c3d9d14afe:2aba5089f049917

@frappe.whitelist()
def get_mapped_opr(source_name, target_doc = None):
    print("Incoming source", source_name)
    target_doc = frappe.model.mapper.get_mapped_doc("Sales Order", source_name, {
        "Sales Order":{
        "doctype": "Order Processing Request",
            "field_map": {

            }
        }
    }, target_doc)
    return target_doc

@frappe.whitelist()
def get_mapped_delivery_note(source_name, target_doc = None):
    print("Incoming source", source_name)
    target_doc = frappe.model.mapper.get_mapped_doc("Order Processing Request", source_name, {
        "Order Processing Request":{
            "doctype": "Delivery Note"
        }
    }, target_doc)
    sql = f"""
        select sales_order, customer_name, customer_reference, payment_term from `tabOrder Processing Request` where name = '{source_name}'
    """
    items = frappe.db.sql(sql, as_dict=1)
    target_doc.sales_order_no = items[0].get("sales_order")
    target_doc.customer =  items[0].get("customer_name")
    target_doc.customer_name =  items[0].get("customer_name")
    target_doc.job_reference = items[0].get("customer_reference")
    target_doc.payment_terms = items[0].get("payment_term")
    return target_doc

@frappe.whitelist()
def get_mapped_stock_consumption(source_name, target_doc = None):
    print("Incoming source", source_name)
    target_doc = frappe.model.mapper.get_mapped_doc("Order Processing Request", source_name, {
        "Order Processing Request":{
            "doctype": "Stock Entry"
        }
    }, target_doc)
    sql = f"""
        select sales_order, customer_name from `tabOrder Processing Request` where name = '{source_name}'
    """
    items = frappe.db.sql(sql, as_dict=1)
    target_doc.sales_order = items[0].get("sales_order")
    target_doc.customer_name =  items[0].get("customer_name")
    return target_doc

@frappe.whitelist()
def get_pending_quantities(sales_order_number: str, opr_name: str):
    items = get_items(sales_order_number)
    ordered_items = get_ordered_items(sales_order_number, opr_name)
    output = []
    for item in items:
        detail = item["so_detail"]
        ordered_qty = 0
        if(detail in ordered_items):
            ordered_qty = ordered_items[detail] 
        #if(item["qty"] == ordered_qty):
        #    continue
        output.append({"so_detail": detail, "description": item["description"], "item_code": item["item_code"], "uom": item["uom"],
                       "rate": item["rate"], "quantity": item["qty"] - ordered_qty,
                       "custom_manufactured_item": item["custom_manufactured_item"]})
    return output

@frappe.whitelist()
def get_delivery_note_summary(opr_name: str):
    sql = f"""
        select dn.name, dn.posting_date, dn.job_number, dn.total_sqm, dn.total_qty
        from `tabDelivery Note` dn
        where dn.opr_no = '{opr_name}'
    """
    items = frappe.db.sql(sql, as_dict=1)
    count = 1
    for item in items: 
        item["idx"] = count
        count += 1
    return frappe.frappe.render_template("btb_cvs_support/api/delivery_note_summary.html", {"items": items})

@frappe.whitelist()
def get_stock_consumption_summary(opr_name: str):
    sql = f"""
        select se.name, se.posting_date, se.job_number, se.total_amount 
        from  `tabStock Entry` se 
        where se.opr_no = '{opr_name}'
    """
    items = frappe.db.sql(sql, as_dict=1)
    count = 1
    for item in items: 
        item["idx"] = count
        count += 1
    return frappe.frappe.render_template("btb_cvs_support/api/stock_consumption_summary.html", {"items": items})


def get_items(sales_order_number: str):
    sql = f"""
        select soi.name so_detail, soi.description, soi.item_code, soi.rate, soi.uom, qty,
            i.custom_manufactured_item
        from `tabSales Order Item` soi
        join `tabItem` i on soi.item_code = i.item_code
        where soi.parent = '{sales_order_number}'
        order by soi.idx
    """
    return frappe.db.sql(sql, as_dict=1)

def get_ordered_items(sales_order_number: str, opr_name: str):
    sql = f"""
        Select qt.so_detail, sum(qt.quantity) qty
        from `tabQuantities Table` qt
        join `tabOrder Processing Request` opr on qt.parent = opr.name
        where opr.sales_order = '{sales_order_number}'
        and opr.name != '{opr_name}'
        and opr.workflow_state != 'Completed' and opr.docstatus != 2
        group by qt.so_detail
        
        union all
        
        select acc.so_detail, sum(acc.quantity)
        from `tabAccessories` acc
        join `tabOrder Processing Request` opr on acc.parent = opr.name
        where opr.sales_order = '{sales_order_number}'
        and opr.name != '{opr_name}'
        and opr.workflow_state != 'Completed' and opr.docstatus != 2
        group by acc.so_detail
    """
    items = frappe.db.sql(sql, as_dict=1)
    output = {}
    delivered_items = get_delivered_items(sales_order_number)
    for item in items:
        qty = item["qty"]
        if(item["so_detail"] in delivered_items):
            qty -= delivered_items[item["so_detail"]]
        output[item["so_detail"]] = qty
    
    #loop through delivery item which does not exist in OPR (All OPR are cancelled or completed) and add to output 
    for key in delivered_items:
        if(key not in output):
            output[key] = delivered_items[key]
    return output

def get_delivered_items(sales_order_number: str):
    #Account delivered quantity only for completed or cancelled opr
    sql = f"""
        select dni.so_detail, sum(dni.qty) as qty
        from `tabDelivery Note Item` dni
        join `tabDelivery Note` dn on dni.parent = dn.name
        join `tabOrder Processing Request` opr on dn.opr_no = opr.name
        where dn.sales_order_no = '{sales_order_number}'
        and (opr.workflow_state = 'Completed' or opr.docstatus = 2)
        group by dni.so_detail
    """
    items = frappe.db.sql(sql, as_dict=1)
    output = {}
    for item in items:
        output[item["so_detail"]] = item["qty"]
    return output



