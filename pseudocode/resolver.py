from typing import overload
from typing import Any, Optional, Union, Literal, Iterable, Iterator
from typing import Tuple
from itertools import product

from . import builtin, lang



# **********************************************************************

# Resolver helper functions

def expectTypeElseError(
    exprtype: lang.Type,
    *expected: lang.Type,
    token: lang.Token,
) -> None:
    if exprtype not in expected:
        # Stringify expected types
        typesStr = f"({', '.join(expected)})"
        raise builtin.LogicError(f"Expected {typesStr}, is {exprtype}", token)

def lookupElseError(
    frame: lang.Frame,
    name: lang.NameKey,
    errmsg: str="Undeclared",
    *,
    token: lang.Token,
) -> lang.Frame:
    if frame.has(name):
        return frame
    if isinstance(frame, lang.Frame):
        frame: Optional[lang.Frame] = frame.lookup(name)
        if frame:
            return frame
    raise builtin.LogicError(errmsg, name, token)

def rangeProduct(indexes: Iterable[tuple]) -> Iterator:
    ranges = [
        range(start, end + 1)
        for (start, end) in indexes
    ]
    return product(*ranges)

def resolveName(
    frame: lang.Frame,
    exprOrStmt: Union[lang.Expr, lang.Stmt],
    attr: Optional[str]=None,
) -> None:
    """
    Takes in an UnresolvedName, and returns a GetName with an
    appropriate frame.

    Raises
    ------
    LogicError if name is undeclared.
    """
    name: lang.Expr = getattr(exprOrStmt, attr)
    if not isinstance(name, lang.UnresolvedName):
        return
    exprFrame = frame.lookup(name)
    if exprFrame is None:
        raise builtin.LogicError("Undeclared", name.token())
    if attr:
        return lang.GetName(exprFrame, name)
    setattr(exprOrStmt, attr, lang.GetName(exprFrame, name))



class Resolver:
    """
    Resolves a list of statements with the given frame.
    """
    def __init__(
        self,
        frame: lang.Frame,
        statements: Iterable[lang.Stmt],
    ) -> None:
        self.frame = frame
        self.statements = statements

    def inspect(self) -> None:
        verifyStmts(self.frame, self.statements)


    
# Resolvers

def resolveLiteral(
    frame: lang.Frame,
    literal: lang.Literal,
) -> lang.Type:
    return literal.type

def declareByref(
    frame: lang.Frame,
    declare: lang.Declare,
) -> None:
    assert frame.outer, "Declared name in a frame with no outer"
    expectTypeElseError(
        declare.type, frame.outer.getType(declare.name),
        token=declare.token()
    )
    # Reference frame vars in local
    frame.set(declare.name, frame.outer.get(declare.name))

def declareByval(
    frame: Union[lang.Frame, lang.ObjectTemplate],
    declare: lang.Declare,
) -> None:
    if (
        isinstance(frame, lang.ObjectTemplate)
        and declare.type == 'ARRAY'
    ):
        raise builtin.LogicError(
            "ARRAY in TYPE not supported", declare.token()
        )
    frame.declare(declare.name, declare.type)
    if declare.type == 'ARRAY':
        array = lang.Array(
            typesys=frame.types,
            ranges=declare.metadata['size'],
            type=declare.metadata['type'],
        )
        frame.setValue(declare.name, array)

def resolveDeclare(
    frame: Union[lang.Frame, lang.ObjectTemplate],
    declare: lang.Declare,
    passby: Literal['BYVALUE', 'BYREF']='BYVALUE',
) -> lang.Type:
    """Declare variable in frame"""
    if passby == 'BYVALUE':
        declareByval(frame, declare)
    else:
        assert isinstance(frame, lang.Frame), \
            "Declared BYREF in invalid Frame"
        declareByref(frame, declare)
    return declare.type

def resolveUnary(
    frame: lang.Frame,
    expr: lang.Unary,
) -> lang.Type:
    rType = resolve(frame, expr.right)
    if expr.oper is builtin.sub:
        expectTypeElseError(rType, *builtin.NUMERIC, token=expr.right.token())
        return rType
    if expr.oper is builtin.NOT:
        expectTypeElseError(
            rType, 'BOOLEAN', token=expr.right.token()
        )
        return 'BOOLEAN'
    raise ValueError(f"Unexpected oper {expr.oper}")

def resolveBinary(
    frame: lang.Frame,
    expr: lang.Binary,
) -> lang.Type:
    lType = resolve(frame, expr.left)
    rType = resolve(frame, expr.right)
    if expr.oper in (builtin.AND, builtin.OR):
        expectTypeElseError(lType, 'BOOLEAN', token=expr.left.token())
        expectTypeElseError(rType, 'BOOLEAN', token=expr.right.token())
        return 'BOOLEAN'
    if expr.oper in (builtin.ne, builtin.eq):
        expectTypeElseError(lType, *builtin.EQUATABLE, token=expr.left.token())
        expectTypeElseError(rType, *builtin.EQUATABLE, token=expr.right.token())
        if not (
            (lType == 'BOOLEAN' and rType == 'BOOLEAN')
            or (lType in builtin.NUMERIC and rType in builtin.NUMERIC)
        ):
            raise builtin.LogicError(
                f"Illegal comparison of {lType} and {rType}",
                token=expr.token(),
            )
        return 'BOOLEAN'
    if expr.oper in (builtin.gt, builtin.gte, builtin.lt, builtin.lte):
        expectTypeElseError(lType, *builtin.NUMERIC, token=expr.left.token())
        expectTypeElseError(rType, *builtin.NUMERIC, token=expr.left.token())
        return 'BOOLEAN'
    if expr.oper in (builtin.add, builtin.sub, builtin.mul, builtin.div):
        expectTypeElseError(lType, *builtin.NUMERIC, token=expr.left.token())
        expectTypeElseError(rType, *builtin.NUMERIC, token=expr.left.token())
        if (expr.oper is not builtin.div) and (lType == rType == 'INTEGER'):
            return 'INTEGER'
        return 'REAL'

def resolveAssign(
    keymap: lang.PseudoMap,
    expr: lang.Assign,
) -> lang.Type:
    resolveName(keymap, expr, 'assignee')
    assnType = resolveGetName(keymap, expr.assignee)
    exprType = resolve(keymap, expr.expr)
    expectTypeElseError(
        exprType, assnType, token=expr.token()
    )

def resolveAttr(
    frame: lang.Frame,
    expr: lang.GetAttr,
    *,
    token: lang.Token,
) -> lang.Type:
    """Resolves a GetAttr Expr to return an attribute's type"""
    resolveName(frame, expr, 'object')
    objType = resolve(frame, expr.object)
    # Check objType existence in typesystem
    if not frame.types.has(objType):
        raise builtin.LogicError("Undeclared type", expr.token())
    # Check attribute existence in object template
    obj = frame.types.cloneType(objType).value
    assert isinstance(obj, lang.Object), "Invalid Object"
    if not obj.has(str(expr.name)):
        raise builtin.LogicError("Undeclared attribute", expr.token())
    return obj.getType(str(expr.name))

def resolveIndex(
    frame: lang.Frame,
    expr: lang.GetIndex,
) -> lang.Type:
    """Resolves a GetIndex Expr to return an array element's type"""
    def intsElseError(frame, *indexes):
        for indexExpr in indexes:
            nameType = resolve(frame, indexExpr)
            expectTypeElseError(
                nameType, 'INTEGER', token=indexExpr.token()
            )
    # Array indexes must be integer
    intsElseError(frame, *expr.index)
    expectTypeElseError(
        ## Expect array
        resolve(frame, expr.array), 'ARRAY', token=expr.token())
    array = expr.array.frame.getValue(str(expr.array.name))
    # For mypy type-checking
    assert (isinstance(array, lang.Array)), "Invalid ARRAY"
    return array.elementType

def resolveGetName(frame: lang.Frame, expr: lang.GetName) -> lang.Type:
    """
    Returns the type of value that name is mapped to in frame.
    """
    return frame.getType(expr.name)

def resolveGet(frame, expr: lang.NameExpr) -> lang.Type:
    if isinstance(expr, lang.GetIndex):
        return resolveIndex(frame, expr)
    if isinstance(expr, lang.GetAttr):
        return resolveAttr(frame, expr)
    if isinstance(expr, lang.GetName):
        return resolveGetName(frame, expr)
    assert not isinstance(expr, lang.UnresolvedName), \
        "Encountered UnresolvedName in resolveGet"

def resolveProcCall(
    frame: lang.Frame,
    expr: lang.Call,
) -> Literal['NULL']:
    """
    Resolve a procedure call.
    Statement verification is done in verifyProcedure, not here.
    Delegate argument checking to resolveCall.
    """
    resolveName(frame, expr, 'callable')
    callableType = resolveGetName(frame, expr.callable)
    callFrame = expr.callable.frame
    callable = callFrame.getValue(expr.callable.name)
    if not isinstance(callable, lang.Procedure):
        raise builtin.LogicError(
            "Not PROCEDURE", token=expr.callable.token()
        )
    resolveArgsParams(frame, expr.args, callable.params, token=expr.token())
    return callableType

def resolveFuncCall(
    frame: lang.Frame,
    expr: lang.Call,
) -> lang.Type:
    """
    Resolve a function call.
    Statement verification is done in verifyFunction, not here.
    Delegate argument checking to resolveCall.
    """
    resolveName(frame, expr, 'callable')
    callableType = resolveGetName(frame, expr.callable)
    callFrame = expr.callable.frame
    callable = callFrame.getValue(expr.callable.name)
    if not (
        isinstance(callable, lang.Function)
        or isinstance(callable, lang.Builtin)
    ):
        raise builtin.LogicError(
            "Not FUNCTION", token=expr.callable.token()
        )
    resolveArgsParams(frame, expr.args, callable.params, token=expr.token())
    return callableType

def resolveArgsParams(
    frame: lang.Frame,
    args: lang.Args,
    params: Iterable[lang.Param],
    *,
    token: lang.Token,
) -> None:
    """
    resolveArgsParams() only type-checks the args and stmts of the call.
    It does not resolve the callable. This should be carried out first (e.g. in
    a wrapper function) before resolveArgsParams() is invoked.
    """
    if len(args) != len(params):
        raise builtin.LogicError(
            f"Expected {len(params)} args, got {len(args)}", token=token(),
        )
    for arg, param in zip(args, params):
        # param is a slot from either local or frame
        expectTypeElseError(resolve(frame, arg), param.type, token=arg.token())

def resolve(
    frame: lang.Frame,
    expr: lang.Expr,
) -> lang.Type:
    if isinstance(expr, lang.Literal):
        return resolveLiteral(frame, expr)
    if isinstance(expr, lang.Declare):
        return resolveDeclare(frame, expr)
    elif isinstance(expr, lang.Unary):
        return resolveUnary(frame, expr)
    elif isinstance(expr, lang.Binary):
        return resolveBinary(frame, expr)
    elif isinstance(expr, lang.Assign):
        return resolveAssign(frame, expr)
    elif isinstance(expr, lang.Get):
        return resolveGet(frame, expr)
    elif isinstance(expr, lang.Call):
        return resolveFuncCall(frame, expr)



def resolveExprs(
    frame: lang.Frame,
    exprs: Iterable[lang.Expr],
) -> None:
    for i in range(len(exprs)):
        if isinstance(exprs[i], lang.UnresolvedName):
            exprs[i] = resolveName(frame, exprs[i])
        resolve(frame, exprs[i])

# Verifiers

def verifyStmts(
    frame: lang.Frame,
    stmts: Iterable[lang.Stmt],
    returnType: Optional[lang.Type]=None,
) -> None:
    for stmt in stmts:
        stmtType = verify(frame, stmt)
        if returnType and isinstance(stmt, lang.Return):
            expectTypeElseError(
                stmtType, returnType,
                token=stmt.expr.token()
            )

def verifyOutput(frame: lang.Frame, stmt: lang.Output) -> None:
    resolveExprs(frame, stmt.exprs)

def verifyInput(frame: lang.Frame, stmt: lang.Input) -> None:
    resolveName(frame, stmt, 'key')
    resolve(frame, stmt.key)

def verifyCase(frame: lang.Frame, stmt: lang.Conditional) -> None:
    resolveName(frame, stmt, 'cond')
    resolve(frame, stmt.cond)
    for statements in stmt.stmtMap.values():
        verifyStmts(frame, statements)
    if stmt.fallback:
        verifyStmts(frame, stmt.fallback)

def verifyIf(frame: lang.Frame, stmt: lang.Conditional) -> None:
    resolveName(frame, stmt, 'cond')
    condType = resolve(frame, stmt.cond)
    expectTypeElseError(condType, 'BOOLEAN', token=stmt.cond.token())
    for statements in stmt.stmtMap.values():
        verifyStmts(frame, statements)
    if stmt.fallback:
        verifyStmts(frame, stmt.fallback)

def verifyLoop(frame: lang.Frame, stmt: lang.Loop) -> None:
    if stmt.init:
        verify(frame, stmt.init)
    resolveName(frame, stmt, 'cond')
    condType = resolve(frame, stmt.cond)
    expectTypeElseError(condType, 'BOOLEAN', token=stmt.cond.token())
    verifyStmts(frame, stmt.stmts)

def transformDeclares(frame: lang.Frame, declares: Iterable[lang.Declare], passby: str) -> Tuple[lang.TypedValue]:
    params = tuple()
    for expr in enumerate(declares):
        resolveDeclare(frame, expr, passby=passby)
        params += (frame.get(expr.name),)
    return params

def verifyProcedure(frame: lang.Frame, stmt: lang.ProcFunc) -> None:
    local = lang.Frame(typesys=frame.types, outer=frame)
    params = transformDeclares(local, stmt.params, stmt.passby)
    # Assign procedure in frame first, to make recursive calls work
    frame.declare(stmt.name, 'NULL')
    frame.setValue(stmt.name, lang.Procedure(
        local, params, stmt.stmts
    ))
    for procstmt in callable.stmts:
        if isinstance(procstmt, lang.Return):
            raise builtin.LogicError(
                "Unexpected RETURN in PROCEDURE",
                procstmt.expr.token()
            )
    verifyStmts(local, stmt.stmts)

def verifyFunction(frame: lang.Frame, stmt: lang.ProcFunc) -> None:
    local = lang.Frame(typesys=frame.types, outer=frame)
    params = transformDeclares(local, stmt.params, stmt.passby)
    # Assign function in frame first, to make recursive calls work
    frame.declare(stmt.name, stmt.returnType)
    frame.setValue(stmt.name, lang.Function(
        local, params, stmt.stmts
    ))
    # Check for return statements
    if not any([
        isinstance(stmt, lang.Return)
        for stmt in stmt.stmts
    ]):
        raise builtin.LogicError(
            "No RETURN in function", stmt.name.token()
        )
    verifyStmts(local, stmt.stmts)

def verifyDeclareType(frame: lang.Frame, stmt: lang.TypeStmt) -> None:
    frame.types.declare(str(stmt.name))
    objTemplate = lang.ObjectTemplate(typesys=frame.types)
    for expr in stmt.exprs:
        resolveDeclare(objTemplate, expr)
    frame.types.setTemplate(str(stmt.name), objTemplate)

@overload
def verify(frame: lang.Frame, stmt: lang.ExprStmt) -> lang.Type: ...
@overload
def verify(frame: lang.Frame, stmt: lang.Stmt) -> None: ...
def verify(frame: lang.Frame, stmt: lang.Stmt):
    if isinstance(stmt, lang.Output):
        verifyOutput(frame, stmt)
    elif isinstance(stmt, lang.Input):
        verifyInput(frame, stmt)
    elif isinstance(stmt, lang.Case):
        verifyCase(frame, stmt)
    elif isinstance(stmt, lang.If):
        verifyIf(frame, stmt)
    elif isinstance(stmt, lang.Loop):
        verifyLoop(frame, stmt)
    elif isinstance(stmt, lang.ProcedureStmt):
        verifyProcedure(frame, stmt)
    elif isinstance(stmt, lang.FunctionStmt):
        verifyFunction(frame, stmt)
    elif isinstance(stmt, lang.OpenFile):
        resolveName(frame, stmt, 'filename')
        resolve(frame, stmt.filename)
    elif isinstance(stmt, lang.ReadFile):
        resolveName(frame, stmt, 'filename')
        resolveName(frame, stmt, 'target')
        resolve(frame, stmt.filename)
        resolve(frame, stmt.target)
    elif isinstance(stmt, lang.WriteFile):
        resolveName(frame, stmt, 'filename')
        resolveName(frame, stmt, 'data')
        resolve(frame, stmt.filename)
        resolve(frame, stmt.data)
    elif isinstance(stmt, lang.CloseFile):
        resolveName(frame, stmt, 'filename')
        resolve(frame, stmt.filename)
    elif isinstance(stmt, lang.TypeStmt):
        verifyDeclareType(frame, stmt)
    elif isinstance(stmt, lang.CallStmt):
        return resolveProcCall(frame, stmt.expr)
    elif isinstance(stmt, lang.ExprStmt):
        return resolve(frame, stmt.expr)
