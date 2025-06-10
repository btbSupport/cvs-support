from typing import List, Dict, Optional



def exec_formula( f, features: List[Dict[str, 'Feature']]) -> float:
    output = None
    for ft in features:
        if(f == None): continue
        result = True
        if("filter" in f.keys()) : result = exec_filter(f["filter"], ft)
        if result:
            aggregated_value = exec_aggregate([f["aggregate"]], ft)
            output = get_aggregate_value(f["aggregate"]["logic"], output, aggregated_value)
    return output or 0

def exec_aggregate( ags: List['Aggregate'], features: Dict[str, 'Feature']) -> float:
    output = None
    result = True
    for a in ags:
        if "filter" in a.keys():
            result = exec_filter(a["filter"], features)
        if result:
            if "aggregate" in a.keys():
                output = exec_aggregate(a["aggregate"], features)
            if "fields" in a.keys():
                output = get_aggregate_value(a["logic"], output, exec_fields(a["logic"], a["fields"], features))
    return output or 0

def exec_fields( logic: str, fields: List[str], features: Dict[str, 'Feature']) -> float:
    output = None
    for field in fields:
        value = get_decimal_value(features, field)
        output = get_aggregate_value(logic, output, value)
        print('field : ',field)
        print('output : ',output)
    return output

def get_aggregate_value( logic: str, output: Optional[float], val: Optional[float]) -> float:
    print('logic : ',logic)
    print('output : ',output)
    print('val : ',val)
    if output is None:
        return val if val is not None else 0
    if val is None:
        return output
   
    if logic == 'SUM':
        return output + val
    elif logic == 'MINUS':
        return output - val
    elif logic == 'MUL':
        return output * val
    elif logic == 'DIV':
        return output / val if val != 0 else 0
    return 0

def exec_filter( f: 'Filter' = None, features: Dict[str, 'Feature']=None) -> bool:
    if f is None:
        return True
    output = None
    for condition in f["conditions"]:
        result = exec_condition(condition, features)
        if output is None:
            output = result
        elif f["logic"] == 'or':
            output = output or result
        elif f["logic"] == 'not':
            output = not result
        elif f["logic"] == 'and':
            output = output and result
    if "filter" in f.keys():
        output = output and exec_filter(f["filter"], features)
    return output or False

def exec_condition( c: 'Condition', features: Dict[str, 'Feature']) -> bool:
    result_value = get_value(features, c["field"])
    operator = c["operator"]
    value = c["value"]
    if operator == 'lt':
        return result_value < value
    elif operator == 'gt':
        return result_value > value
    elif operator == 'neq':
        return result_value != value
    elif operator == 'eq':
        return result_value == value
    return False

def get_decimal_value( features: Dict[str, 'Feature'], key: str) -> float:
    print("key : ",key)
    # print("features : ",features)
    if key in features:
        return float(features[key]["value"])
    return 0

def get_value( features: Dict[str, 'Feature'], key: str) -> str:
    if key in features:
        return str(features[key]["value"])
    return key

# Inner classes
class Formula:
    def __init__(self):
        self.filter = None
        self.aggregate = None

class Filter:
    def __init__(self):
        self.filter: Optional['Filter'] = None
        self.logic: str = ''
        self.conditions: List['Condition'] = []

class Condition:
    def __init__(self):
        self.field: str = ''
        self.operator: str = ''
        self.value: str = ''

class Aggregate:
    def __init__(self):
        self.aggregate: List['Aggregate'] = []
        self.filter: Optional['Filter'] = None
        self.logic: str = ''
        self.fields: List[str] = []

# Define the Feature class as needed
class Feature:
    def __init__(self):
        self.label: str = ''
        self.value: str = ''
