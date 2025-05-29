from typing import List, Dict, Optional

class btb_constraint:
    def __init__(self):
        pass

    def execFormula(self, f, features: List[Dict[str, 'Feature']]) -> float:
        output = None
        for ft in features:
            result = self.execFilter(f.filter, ft)
            if result:
                aggregated_value = self.execAggregate([f.aggregate], ft)
                output = self.getAggregateValue(f.aggregate.logic, output, aggregated_value)
        return output or 0

    def execAggregate(self, ags: List['Aggregate'], features: Dict[str, 'Feature']) -> float:
        output = None
        result = True
        for a in ags:
            if a.filter:
                result = self.execFilter(a.filter, features)
            if result:
                if a.aggregate:
                    output = self.execAggregate([a.aggregate], features)
                if a.fields:
                    output = self.getAggregateValue(a.logic, output, self.execFields(a.logic, a.fields, features))
        return output or 0

    def execFields(self, logic: str, fields: List[str], features: Dict[str, 'Feature']) -> float:
        output = 0
        for field in fields:
            value = self.getDecimalValue(features, field)
            output = self.getAggregateValue(logic, output, value)
        return output

    def getAggregateValue(self, logic: str, output: Optional[float], val: Optional[float]) -> float:
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

    def execFilter(self, f: 'Filter', features: Dict[str, 'Feature']) -> bool:
        if f is None:
            return True
        output = None
        for condition in f.conditions:
            result = self.execCondition(condition, features)
            if output is None:
                output = result
            elif f.logic == 'or':
                output = output or result
            elif f.logic == 'not':
                output = not result
            elif f.logic == 'and':
                output = output and result
        if f.filter:
            output = output and self.execFilter(f.filter, features)
        return output or False

    def execCondition(self, c: 'Condition', features: Dict[str, 'Feature']) -> bool:
        result_value = self.getValue(features, c.field)
        operator = c.operator
        value = c.value
        if operator == 'lt':
            return result_value < value
        elif operator == 'gt':
            return result_value > value
        elif operator == 'neq':
            return result_value != value
        elif operator == 'eq':
            return result_value == value
        return False

    def getDecimalValue(self, features: Dict[str, 'Feature'], key: str) -> float:
        if key in features:
            return float(features[key].value)
        return 0

    def getValue(self, features: Dict[str, 'Feature'], key: str) -> str:
        if key in features:
            return str(features[key].value)
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
