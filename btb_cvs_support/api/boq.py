import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional
import os
from .btb_quotation import *
from .btb_constraint import *
from ..document.generator import *

subCategoryMap: Dict[str, str] = {}

class ProductInfo:
    def __init__(self, descr="", val=0, u=""):
        self.value = round(val,2) if val > 0 else "-"
        self.description = descr
        self.uom = u
        self.itemCode = None
        self.formula = None  

class ProductNode:
    def __init__(self):
        self.productName: Optional[str] = None
        self.subCategory: Optional[str] = None
        self.pageBreak: bool = False
        self.items: List[ProductInfo] = []

@frappe.whitelist()
def provide( quote_name: str) -> Dict[str, ProductNode]:
    output = {
        "ci": populate_cart_detail(quote_name),
        "qt": get_quote_details(quote_name)
    }
    file_path = "../apps/btb_cvs_support/btb_cvs_support/document/templates/boq.docx"
    print("output : ",output)
    # generate("templates/quotation.docx", json.loads(json.dumps(output)), format="pdf")
    generate(file_path, output, format="pdf",doc_type="Quotation",doc_name=quote_name,file_name="BOQ_"+quote_name+".pdf")

def get_quote_details( quote_name: str) -> Dict:
    sql = f""" select customer_name,project,name  from `tabQuotation` tqi where name ='{quote_name}'
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items[0]

def populate_cart_detail( quote_name: str) -> Dict[str, ProductNode]:
    # print(f'BOQ quoteId - {quote_name}')

    output: Dict[str, ProductNode] = {}
    models = populate_product_map(populate_cart_item_model(quote_name))
    product_family_map = populate_product_family_map()
    sno = 1

    for sub_cat in models:
        # print(f'BOQ subCat - {sub_cat}')
        product_code = subCategoryMap.get(sub_cat)
        details = []
        if product_code not in product_family_map:
            continue
            
        for pi in product_family_map[product_code]:
            # print("details pi : ",pi)
            pinfo = ProductInfo(pi['description'], Decimal('0'), pi['uom']).__dict__
            pinfo["formula"] = pi['formula']
            pinfo["itemCode"] = pi['itemCode']
            details.append(pinfo)
        # print("details : ",details)
        if sub_cat not in output:
            node = ProductNode().__dict__
            node["productName"] = str(models[sub_cat][0]['cartProductName']["value"])
            node["subCategory"] = str(models[sub_cat][0]['subcategory']["value"])
            node["pageBreak"] = len(models) != sno
            sno += 1
            output[sub_cat] = node

        for pi in details:
            val = exec_formula(pi["formula"], models[sub_cat])
            if val and val > 0:
                pinfo = ProductInfo(pi['description'], val, pi['uom']).__dict__
                # pinfo["value"] = val
                pinfo["itemCode"] = pi['itemCode']
                output[sub_cat]["items"].append(pinfo)

    return output

def populate_product_map( models: List[Dict[str, 'Feature']]):
    output = {}
    keys = {}

    for model in models:
        product_code = get_key(model, 'cartProductCode')
        sub_category = get_key(model, 'subcategory')
        if sub_category not in keys:
            prefix = get_prefix(str(len(keys)))
            keys[sub_category] = prefix + sub_category
            subCategoryMap[keys[sub_category]] = product_code
            output[keys[sub_category]] = []

        output[keys[sub_category]].append(model)
    return output

def populate_product_family_map() -> Dict[str, 'ProductInfo']:
    base_path = os.path.dirname(__file__)
    file_path = os.path.join(base_path, 'boq_format.JSON')
    with open(file_path, 'r') as f:
        setting_json = json.load(f)
    return json.loads(json.dumps(setting_json))

def get_prefix( val: str):
    return val.zfill(6)

def get_key( features: Dict[str, 'Feature'], key: str):
    keys = key.split(',')
    return '-'.join(str(features[k]["value"]) for k in keys if k in features)
