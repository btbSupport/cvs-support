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
    target_doc.custom_sales_order = items[0].get("sales_order")
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
    target_doc.custom_sales_order = items[0].get("sales_order")
    target_doc.customer_name =  items[0].get("customer_name")
    return target_doc

@frappe.whitelist()
def get_sales_order_details(sales_order_number: str):
    sql = f"""
        select  so.conversion_rate, so.additional_discount_percentage 
        from `tabSales Order` so where so.name = '{sales_order_number}'
    """
    return frappe.db.sql(sql, as_dict = 1)[0]

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
    items = get_delivery_note_data(opr_name)
    count = 1
    for item in items: 
        item["idx"] = count
        count += 1
    show_amount = "Accounts User" in frappe.get_roles()
    return frappe.frappe.render_template("btb_cvs_support/api/delivery_note_summary.html", {"items": items, "show_amount": show_amount})

@frappe.whitelist()
def get_delivery_note_data(opr_name: str):
    sql = f"""
        select dn.name, dn.posting_date, dn.job_number, dn.sales_order_no, dn.custom_total_sqm, dn.custom_total_pcs, dn.net_total
        from `tabDelivery Note` dn
        where dn.custom_opr = '{opr_name}' and dn.docstatus = 1
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items;

@frappe.whitelist()
def get_stock_consumption_summary(opr_name: str):
    items = get_stock_consumption_data(opr_name)
    count = 1
    total = 0
    for item in items: 
        item["idx"] = count
        count += 1
        total += item["value_difference"]
    show_amount = "Accounts User" in frappe.get_roles()
    return frappe.frappe.render_template("btb_cvs_support/api/stock_consumption_summary.html", {"items": items, "total_consumption": total, "show_amount": show_amount})

@frappe.whitelist()
def get_stock_consumption_data(opr_name: str):
    sql = f"""
        select se.name, se.posting_date, se.job_number, se.value_difference 
        from  `tabStock Entry` se 
        where se.custom_opr = '{opr_name}' and se.stock_entry_type = 'Material Issue'
        and se.docstatus = 1
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items;
 

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
            qty += delivered_items[item["so_detail"]]
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
        join `tabOrder Processing Request` opr on dn.custom_opr = opr.name
        where dn.custom_sales_order = '{sales_order_number}'
        and (opr.workflow_state = 'Completed' or opr.docstatus = 2)
        and dn.docstatus = 1
        group by dni.so_detail
    """
    items = frappe.db.sql(sql, as_dict=1)
    output = {}
    for item in items:
        output[item["so_detail"]] = item["qty"]
    return output


def update_opr(opr_name):
    if not opr_name:
        return
    #opr
    opr_doc = frappe.get_doc("Order Processing Request", opr_name)

    #Delivery
    delivery_data = get_delivery_data(opr_name)
    invoiced_value = delivery_data.get("net_total") or 0
    total_sqm_delivered = delivery_data.get("custom_total_sqm") or 0
    total_nos_delivered = delivery_data.get("custom_total_pcs") or 0

    approx_value = opr_doc.approx_value_ or 0
    adjustment = opr_doc.adjustment or 0
    remaining_value = approx_value + adjustment - invoiced_value

    #Stock Consumption
    stock_data = get_stock_consumption(opr_name)
    consumption_value = stock_data.get("total") or 0
    
    net_value = invoiced_value + consumption_value
    material_percent = 0
    if invoiced_value > 0:
        material_percent = - (consumption_value / invoiced_value) * 100

    #Quantity Table
    quantities = get_quantities(opr_name)
    total_straight_sqm = quantities.get("total_straight_sqm") or 0
    total_fittings_sqm = quantities.get("total_fittings_sqm") or 0
    total_straight_nos = quantities.get("total_straight_nos") or 0
    total_fittings_nos = quantities.get("total_fittings_nos") or 0
    
    total_sqm = total_straight_sqm + total_fittings_sqm
    remaining_sqm_delivery = total_sqm - total_sqm_delivered
    total_no = total_straight_nos + total_fittings_nos
    remaining_nos_delivery = total_no - total_nos_delivered

    #Production Schedule
    production = get_production(opr_name)
    total_sqm_produced = production.get("total_sqm_produced") or 0
    total_nos_produced = production.get("total_nos_produced") or 0

    remaining_nos_production = total_no - total_nos_produced
    remaining_sqm_production = total_sqm - total_sqm_produced
    remaining_produced_sqm_to_delivered = total_sqm_produced - total_sqm_delivered
    remaining_produced_no_to_delivered = total_nos_produced - total_nos_delivered

    frappe.db.set_value("Order Processing Request", opr_name, {
        "invoiced_value": invoiced_value,
        "total_sqm_delivered": total_sqm_delivered,
        "total_nos_delivered": total_nos_delivered,
        "consumption_value": consumption_value,
        "net_value": net_value,
        "total_straight_sqm": total_straight_sqm,
        "total_fittings_sqm": total_fittings_sqm,
        "total_sqm": total_sqm,
        "remaining_sqm_delivery": remaining_sqm_delivery,
        "total_sqm_produced": total_sqm_produced,
        "remaining_sqm_production": remaining_sqm_production,
        "remaining_produced_sqm_to_delivered": remaining_produced_sqm_to_delivered,
        "total_straight_nos": total_straight_nos,
        "total_fittings_nos": total_fittings_nos,
        "total_no": total_no,
        "remaining_nos_delivery": remaining_nos_delivery,
        "total_nos_produced": total_nos_produced,
        "remaining_nos_production": remaining_nos_production,
        "remaining_produced_no_to_delivered": remaining_produced_no_to_delivered,
        "material_percent": material_percent,
        "remaining_value": remaining_value,
    })

def get_delivery_data(opr_name):
    return frappe.db.sql("""
        SELECT 
            SUM(base_net_total) AS net_total, 
            SUM(custom_total_sqm) AS custom_total_sqm, 
            SUM(custom_total_pcs) AS custom_total_pcs
        FROM `tabDelivery Note`
        WHERE custom_opr = %s AND docstatus = 1
    """, opr_name, as_dict=True)[0]

def get_stock_consumption(opr_name):
     return frappe.db.sql("""
        SELECT SUM(value_difference) AS total
        FROM `tabStock Entry`
        WHERE custom_opr = %s AND docstatus = 1
          AND stock_entry_type = 'Material Issue'
    """, opr_name, as_dict=True)[0]

def get_quantities(opr_name):
    return frappe.db.sql("""
        SELECT 
            SUM(straight_sqm) AS total_straight_sqm,
            SUM(fitting_sqm) AS total_fittings_sqm,
            SUM(straight_no) AS total_straight_nos,
            SUM(fitting_no)  AS total_fittings_nos
        FROM `tabQuantities Table`
        WHERE parent = %s
    """, opr_name, as_dict=True)[0]

def get_production(opr_name):
    return frappe.db.sql("""
        SELECT 
            SUM(sqm) AS total_sqm_produced,
            SUM(nos) AS total_nos_produced
        FROM `tabProduction Schedule`
        WHERE parent = %s
    """, opr_name, as_dict=True)[0]

