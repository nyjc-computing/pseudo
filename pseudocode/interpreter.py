from typing import Optional, Iterable, Tuple, Callable as function

from . import builtin, lang, system



# ----------------------------------------------------------------------

# Helper functions

def expectTypeElseError(
    exprmode: str,
    *expected: str,
    errmsg: str="Expected",
    token: lang.Token,
) -> None:
    if not exprmode in expected:
        raise builtin.RuntimeError(f"{errmsg} {expected}", token=token)

def declaredElseError(
    frame: lang.Frame,
    name: lang.NameKey,
    errmsg: str="Undeclared",
    token: lang.Token=None,
) -> None:
    if not frame.has(name):
        raise builtin.RuntimeError(errmsg, token)

def undeclaredElseError(
    frame: lang.Frame,
    name: lang.NameKey,
    errmsg="Already declared",
    token: lang.Token=None,
) -> None:
    if frame.has(name):
        raise builtin.RuntimeError(errmsg, token)



class Interpreter:
    """
    Interprets a list of statements with a given frame.
    """
    outputHandler: function = print
    def __init__(
        self,
        frame: lang.Frame,
        statements: Iterable[lang.Stmt],
    ) -> None:
        self.frame = frame
        self.statements = statements

    def registerOutputHandler(self, handler: function) -> None:
        """
        Register handler as the function to use to handle
        any output from the executed statements.
        The default handler is Python's print().
        """
        self.outputHandler = handler

    def interpret(self) -> None:
        executeStmts(
            self.frame,
            self.statements,
            output=self.outputHandler,
        )



# Evaluators

def evalIndex(
    frame: lang.Frame,
    indexes: Iterable[tuple],
) -> Tuple[int]:
    return tuple((
        evaluate(frame, expr) for expr in indexes
    ))

def evalLiteral(
    frame: lang.Frame,
    literal: lang.Literal,
) -> lang.PyLiteral:
    return literal.value

def evalUnary(frame: lang.Frame, expr: lang.Unary) -> lang.PyLiteral:
    rightval = evaluate(frame, expr.right)
    return expr.oper(rightval)

def evalBinary(frame: lang.Frame, expr: lang.Binary) -> lang.PyLiteral:
    leftval = evaluate(frame, expr.left)
    rightval = evaluate(frame, expr.right)
    return expr.oper(leftval, rightval)

def evalGet(frame: lang.Frame, expr: lang.Get) -> lang.Value:
    # Frame should have been inserted in resolver
    # So ignore the frame that is passed here
    obj = expr.frame
    # evaluate obj until object is retrieved
    if isinstance(obj, lang.Expr):
        obj = evaluate(frame, obj)
    if not isinstance(obj, lang.Object):
        raise builtin.RuntimeError("Invalid object", expr.token())
    name = expr.name
    if isinstance(obj, lang.Array):
        name = evalIndex(frame, expr.name)
    return obj.getValue(name)

def evalCall(frame: lang.Frame, expr: lang.Call, **kwargs) -> Optional[lang.Value]:
    callable = evalGet(frame, expr.callable)
    if isinstance(callable, lang.Builtin):
        if callable.func is system.EOF:
            name = evaluate(frame, expr.args[0])
            file = frame.getValue(name)
            return callable.func(file.iohandler)
        argvals = [evaluate(frame, arg) for arg in expr.args]
        return callable.func(*argvals)
    elif isinstance(callable, lang.Callable):
        # Assign args to param slots
        for arg, slot in zip(expr.args, callable.params):
            argval = evaluate(frame, arg)
            slot.value = argval
        return executeStmts(frame, callable.stmts)

def evalAssign(frame: lang.Frame, expr: lang.Assign) -> lang.Value:
    value = evaluate(frame, expr.expr)
    obj = expr.assignee.frame
    if type(obj) in (lang.Get, lang.Call):
        obj = evaluate(frame, obj)
    name = expr.assignee.name
    if type(obj) in (lang.Array,):
        name = evalIndex(frame, expr.assignee.name)
    obj.setValue(name, value)
    return value

def evaluate(
    frame: lang.Frame,
    expr: lang.Expr,
    **kwargs,
) -> lang.Value:
    if isinstance(expr, lang.Literal):
        return evalLiteral(frame, expr)
    if isinstance(expr, lang.Unary):
        return evalUnary(frame, expr)
    if isinstance(expr, lang.Binary):
        return evalBinary(frame, expr)
    if isinstance(expr, lang.Assign):
        return evalAssign(frame, expr)
    if isinstance(expr, lang.Get):
        return evalGet(frame, expr)
    if isinstance(expr, lang.Call):
        return evalCall(frame, expr)
    else:
        raise TypeError(f"Unexpected expr {expr}")

# Executors

def executeStmts(
    frame: lang.Frame,
    stmts: Iterable[lang.Stmt],
    **kwargs,
) -> Optional[lang.Value]:
    for stmt in stmts:
        if isinstance(stmt, lang.Return):
            return execReturn(frame, stmt, **kwargs)
        else:
            execute(frame, stmt, **kwargs)

def execOutput(
    frame: lang.Frame,
    stmt: lang.Output,
    *,
    output: function,
    **kwargs,
) -> None:
    for expr in stmt.exprs:
        value = evaluate(frame, expr)
        if type(value) is bool:
            value = str(value).upper()
        output(str(value), end='')
    output('')  # Add \n

def execInput(
    frame: lang.Frame,
    stmt: lang.Input,
    **kwargs,
) -> None:
    name = stmt.name.name
    frame.setValue(name, input())

def execCase(
    frame: lang.Frame,
    stmt: lang.Conditional,
    **kwargs,
) -> None:
    cond = evaluate(frame, stmt.cond)
    if cond in stmt.stmtMap:
        executeStmts(frame, stmt.stmtMap[cond], **kwargs)
    elif stmt.fallback:
        executeStmts(frame, stmt.fallback, **kwargs)

def execIf(
    frame: lang.Frame,
    stmt: lang.Conditional,
    **kwargs,
) -> None:
    cond = evaluate(frame, stmt.cond)
    if cond in stmt.stmtMap:
        executeStmts(frame, stmt.stmtMap[True], **kwargs)
    elif stmt.fallback:
        executeStmts(frame, stmt.fallback, **kwargs)

def execWhile(
    frame: lang.Frame,
    stmt: lang.Loop,
    **kwargs,
) -> None:
    if stmt.init:
        execute(frame, stmt.init, **kwargs)
    while evaluate(frame, stmt.cond) is True:
        executeStmts(frame, stmt.stmts, **kwargs)

def execRepeat(
    frame: lang.Frame,
    stmt: lang.Loop,
    **kwargs,
) -> None:
    executeStmts(frame, stmt.stmts)
    while evaluate(frame, stmt.cond) is False:
        executeStmts(frame, stmt.stmts)

def execOpenFile(
    frame: lang.Frame,
    stmt: lang.OpenFile,
    **kwargs,
) -> None:
    filename: str = evaluate(frame, stmt.filename)
    undeclaredElseError(
        frame, filename, "File already opened", stmt.filename.token()
    )
    frame.declare(filename, 'FILE')
    frame.setValue(
        filename,
        lang.File(
            filename,
            stmt.mode,
            open(filename, stmt.mode[0].lower())
        ),
    )

def execReadFile(
    frame: lang.Frame,
    stmt: lang.ReadFile,
    **kwargs,
) -> None:
    filename = evaluate(frame, stmt.filename)
    assert isinstance(filename, str), f"Invalid filename {filename}"
    declaredElseError(
        frame, filename, "File not open", stmt.filename.token()
    )
    file = frame.getValue(filename)
    assert isinstance(file, lang.File), f"Invalid file {file}"
    expectTypeElseError(
        frame.getType(filename), 'FILE', token=stmt.filename.token()
    )
    expectTypeElseError(file.mode, 'READ', token=stmt.filename.token())
    varname = evaluate(frame, stmt.target)
    declaredElseError(frame, varname, token=stmt.target.token())
    # TODO: Catch and handle Python file io errors
    line = file.iohandler.readline().rstrip()
    # TODO: Type conversion
    frame.setValue(varname, line)

def execWriteFile(
    frame: lang.Frame,
    stmt: lang.WriteFile,
    **kwargs,
) -> None:
    filename = evaluate(frame, stmt.filename)
    assert isinstance(filename, str), f"Invalid filename {filename}"
    declaredElseError(
        frame, filename, "File not open", token=stmt.filename.token()
    )
    file = frame.getValue(filename)
    assert isinstance(file, lang.File), f"Invalid file {file}"
    expectTypeElseError(
        frame.getType(filename), 'FILE', token=stmt.filename.token()
    )
    expectTypeElseError(
        file.mode, 'WRITE', 'APPEND', token=stmt.filename.token()
    )
    writedata = evaluate(frame, stmt.data)
    if type(writedata) is bool:
        writedata = str(writedata).upper()
    else:
        writedata = str(writedata)
    # Move pointer to next line after writing
    if not writedata.endswith('\n'):
        writedata += '\n'
    # TODO: Catch and handle Python file io errors
    file.iohandler.write(writedata)

def execCloseFile(
    frame: lang.Frame,
    stmt: lang.CloseFile,
    **kwargs,
) -> None:
    filename = evaluate(frame, stmt.filename)
    assert isinstance(filename, str), f"Invalid filename {filename}"
    declaredElseError(
        frame, filename, "File not open", token=stmt.filename.token()
    )
    file = frame.getValue(filename)
    assert isinstance(file, lang.File), f"Invalid file {file}"
    expectTypeElseError(
        frame.getType(filename), 'FILE', token=stmt.filename.token()
    )
    file.iohandler.close()
    frame.delete(filename)

def execFile(
    frame: lang.Frame,
    stmt: lang.FileStmt,
    **kwargs,
) -> None:
    if isinstance(stmt, lang.OpenFile):
        execOpenFile(frame, stmt)
    elif isinstance(stmt, lang.ReadFile):
        execReadFile(frame, stmt)
    elif isinstance(stmt, lang.WriteFile):
        execWriteFile(frame, stmt)
    elif isinstance(stmt, lang.CloseFile):
        execCloseFile(frame, stmt)

def execCall(
    frame: lang.Frame,
    stmt: lang.CallStmt,
    **kwargs,
) -> None:
    evalCall(frame, stmt.expr, **kwargs)

def execAssign(
    frame: lang.Frame,
    stmt: lang.AssignStmt,
    **kwargs,
) -> None:
    evaluate(frame, stmt.expr, **kwargs)

def execReturn(
    frame: lang.Frame,
    stmt: lang.Return,
    **kwargs,
) -> lang.Value:
    return evaluate(frame, stmt.expr, **kwargs)



def execute(
    frame: lang.Frame,
    stmt: lang.Stmt,
    **kwargs,
) -> None:
    if isinstance(stmt, lang.Output):
        execOutput(frame, stmt, **kwargs)
    if isinstance(stmt, lang.Input):
        execInput(frame, stmt, **kwargs)
    if isinstance(stmt, lang.Case):
        execCase(frame, stmt, **kwargs)
    if isinstance(stmt, lang.If):
        execIf(frame, stmt, **kwargs)
    if isinstance(stmt, lang.While):
        execWhile(frame, stmt, **kwargs)
    if isinstance(stmt, lang.Repeat):
        execRepeat(frame, stmt, **kwargs)
    if (
        isinstance(stmt, lang.OpenFile)
        or isinstance(stmt, lang.ReadFile)
        or isinstance(stmt, lang.WriteFile)
        or isinstance(stmt, lang.CloseFile)
    ):
        execFile(frame, stmt, **kwargs)
    if isinstance(stmt, lang.CallStmt):
        execCall(frame, stmt, **kwargs)
    if isinstance(stmt, lang.AssignStmt):
        execAssign(frame, stmt, **kwargs)
    if isinstance(stmt, lang.Return):
        execReturn(frame, stmt, **kwargs)
    if (
        isinstance(stmt, lang.DeclareStmt)
        or isinstance(stmt, lang.ProcedureStmt)
        or isinstance(stmt, lang.FunctionStmt)
    ):
        pass
    raise ValueError(f"Invalid Stmt {stmt}")
