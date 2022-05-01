from builtin import lt, lte, gt, gte, ne, eq
from builtin import add, sub, mul, div
from builtin import LogicError
from lang import Literal, Declare, Unary, Binary, Get, Call



# Helper functions

def expectTypeElseError(exprtype, expected):
    if exprtype != expected:
        raise LogicError(f"Expected {expected}", exprtype)

def resolveExprs(frame, exprs):
    for expr in exprs:
        expr.accept(frame, resolve)

def verifyStmts(frame, stmts):
    for stmt in stmts:
        stmt.accept(frame, verify)

def verifyOutput(frame, stmt):
    resolveExprs(frame, stmt.exprs)

def verifyInput(frame, stmt):
    name = stmt.name
    if name not in frame:
        raise LogicError(
            f'Name not declared',
            stmt.name,
        )

def get(frame, expr):
    """Evaluate a Get expr to retrieve value from frame"""
    if expr.name not in frame:
        raise LogicError("Undeclared", expr.name)
    if frame[expr.name] is None:
        raise LogicError("No value assigned", expr.name)
    return frame[expr.name]

def value(frame, expr):
    """Return the value of a Literal"""
    return expr.value

def resolveLiteral(frame, literal):
    return literal.type

def resolveDeclare(frame, expr):
    """Declare variable in frame"""
    if expr.name in frame:
        raise LogicError("Already declared", expr.name)
    frame[expr.name] = {'type': expr.type, 'value': None}
    return expr.type

def resolveUnary(frame, expr):
    righttype = expr.right.accept(frame, resolve)
    if expr.oper is sub:
        expectTypeElseError(righttype, 'INTEGER')
        return 'INTEGER'
    else:
        raise ValueError("Unexpected oper {expr.oper}")

def resolveBinary(frame, expr):
    lefttype = expr.left.accept(frame, resolve)
    righttype = expr.right.accept(frame, resolve)
    if expr.oper in (gt, gte, lt, lte, ne, eq):
        expectTypeElseError(lefttype, 'INTEGER')
        expectTypeElseError(righttype, 'INTEGER')
        return 'BOOLEAN'
    if expr.oper in (add, sub, mul, div):
        # TODO: Handle REAL type
        expectTypeElseError(lefttype, 'INTEGER')
        expectTypeElseError(righttype, 'INTEGER')
        return 'INTEGER'

def resolveGet(frame, expr):
    """Insert frame into Get expr"""
    assert isinstance(expr, Get), "Not a Get Expr"
    expr.frame = frame
    return frame[expr.name]['type']

def resolveCall(frame, expr):
    # Insert frame
    calltype = expr.callable.accept(frame, resolveGet)
    callable = expr.callable.accept(frame, get)['value']
    expectTypeElseError(calltype, 'procedure')
    numArgs, numParams = len(expr.args), len(callable['params'])
    if numArgs != numParams:
        raise LogicError(
            f"Expected {numParams} args, got {numArgs}",
            None,
        )
    # Type-check arguments
    for arg, param in zip(expr.args, callable['params']):
        # param is a slot from either local or frame
        argtype = arg.accept(frame, resolve)
        expectTypeElseError(argtype, param['type'])



def resolve(frame, expr):
    if isinstance(expr, Literal):
        return expr.accept(frame, resolveLiteral)
    if isinstance(expr, Declare):
        return expr.accept(frame, resolveDeclare)
    elif isinstance(expr, Unary):
        return expr.accept(frame, resolveUnary)
    elif isinstance(expr, Binary):
        return expr.accept(frame, resolveBinary)
    elif isinstance(expr, Get):
        return expr.accept(frame, resolveGet)
    elif isinstance(expr, Call):
        return expr.accept(frame, resolveCall)
        
def verifyAssign(frame, stmt):
    exprtype = stmt.expr.accept(frame, resolve)
    expectTypeElseError(exprtype, frame[stmt.name]['type'])

def verifyCase(frame, stmt):
    stmt.cond.accept(frame, resolve)
    verifyStmts(frame, stmt.stmts.values())
    if stmt.fallback:
        stmt.fallback.accept(frame, verify)

def verifyIf(frame, stmt):
    stmt.cond.accept(frame, resolve)
    expectTypeElseError(stmt.cond, 'BOOLEAN')
    verifyStmts(frame, stmt.stmts[True])
    if stmt.fallback:
        verifyStmts(frame, stmt.fallback)

def verifyLoop(frame, stmt):
    if stmt.init:
        stmt.init.accept(frame, verify)
    condtype = stmt.cond.accept(frame, resolve)
    expectTypeElseError(condtype, 'BOOLEAN')
    verifyStmts(frame, stmt.stmts)

def verifyProcedure(frame, stmt):
    # Set up local frame
    local = {}
    for i, expr in enumerate(stmt.params):
        if stmt.passby == 'BYREF':
            exprtype = expr.accept(local, resolveDeclare)
            expectTypeElseError(exprtype, frame[expr.name]['type'])
            # Reference frame vars in local
            local[expr.name] = frame[expr.name]
        else:
            local[expr.name] = {
                'type': expr.type,
                'value': None,
            }
        # params: replace Declare Expr with slot
        stmt.params[i] = local[expr.name]
    # Resolve procedure statements using local
    verifyStmts(local, stmt.stmts)
    # Declare procedure in frame
    name = stmt.name
    frame[name] = {
        'type': 'procedure',
        'value': {
            'frame': local,
            'passby': stmt.passby,
            'params': stmt.params,
            'stmts': stmt.stmts,
        }
    }

def verifyFunction(frame, stmt):
    # Set up local frame
    local = {}
    for expr in stmt.params:
        # Declare vars in local
        expr.accept(local, resolveDeclare)
    name = stmt.name
    returnType = stmt.returnType
    # Resolve procedure statements using local
    hasReturn = False
    for procstmt in stmt.stmts:
        stmtType = procstmt.accept(local, verify)
        if stmtType:
            hasReturn = True
            if stmtType != returnType:
                raise LogicError(
                    f"Expect {returnType}, got {stmtType}",
                    stmt.name,
                )
    if not hasReturn:
        raise LogicError("No RETURN in function", None)
     # Declare function in frame
    frame[name] = {
        'type': returnType,
        'value': {
            'frame': local,
            'passby': 'BYVALUE',
            'params': stmt.params,
            'stmts': stmt.stmts,
        }
    }

def verifyFile(frame, stmt):
    name = stmt.name.accept(frame, value)
    if stmt.action == 'open':
        if name in frame:
            raise LogicError("File already opened", stmt.name)
        file = {'type': stmt.mode, 'value': None}
        frame[name] = file
    elif stmt.action == 'read':
        if name not in frame:
            raise LogicError("File not open", stmt.name)
        file = frame[name]
        if file['type'] != 'READ':
            raise LogicError("File mode is {file['type']}", stmt.name)
    elif stmt.action == 'write':
        stmt.data.accept(frame, resolve)
        if name not in frame:
            raise LogicError("File not open", stmt.name)
        file = frame[name]
        if file['type'] not in ('WRITE', 'APPEND'):
            raise LogicError("File mode is {file['type']}", stmt.name)
    elif stmt.action == 'close':
        if name not in frame:
            raise LogicError("File not open", stmt.name)
        del frame[name]

def verify(frame, stmt):
    if stmt.rule == 'output':
        stmt.accept(frame, verifyOutput)
    if stmt.rule == 'input':
        stmt.accept(frame, verifyInput)
    elif stmt.rule == 'declare':
        stmt.expr.accept(frame, resolveDeclare)
    elif stmt.rule == 'assign':
        stmt.accept(frame, verifyAssign)
    elif stmt.rule == 'case':
        stmt.accept(frame, verifyCase)
    elif stmt.rule == 'if':
        stmt.accept(frame, verifyIf)
    elif stmt.rule in ('while', 'repeat', 'for'):
        stmt.accept(frame, verifyLoop)
    elif stmt.rule == 'procedure':
        stmt.accept(frame, verifyProcedure)
    elif stmt.rule == 'call':
        stmt.expr.accept(frame, resolveCall)
    elif stmt.rule == 'function':
        stmt.accept(frame, verifyFunction)
    elif stmt.rule == 'file':
        stmt.accept(frame, verifyFile)
    elif stmt.rule == 'return':
        return stmt.expr.accept(frame, resolve)

def inspect(statements):
    frame = {}
    verifyStmts(frame, statements)
    return statements, frame
