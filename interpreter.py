from builtin import RuntimeError



def evaluate(expr):
    # Evaluating tokens
    if 'type' in expr:
        if expr['type'] == 'name':
            return expr['word']
        return expr['value']
    # Evaluating exprs
    left = evaluate(expr['left'])
    right = evaluate(expr['right'])
    oper = expr['oper']['value']
    return oper(left, right)

def execute(frame, stmt):
    if stmt['rule'] == 'output':
        for expr in stmt['exprs']:
            print(str(evaluate(expr)), end='')
        print('')  # Add \n
    if stmt['rule'] == 'declare':
        name = evaluate(stmt['name'])
        type_ = evaluate(stmt['type'])
        frame[name] = type_
    if stmt['rule'] == 'assign':
        name = evaluate(stmt['name'])
        value = evaluate(stmt['expr'])
        frame[name] = value

def interpret(statements):
    frame = {}
    for stmt in statements:
        try:
            execute(frame, stmt)
        except RuntimeError:
            print()
            break
    return frame