"""Stage 2 of the compiler: reject unsupported Python before generating C++.

The validator is the single place that decides whether a construct is part of
the supported micropy subset.  It never executes user code and it never
silently drops a construct: anything it does not understand is reported with a
source location.
"""

from __future__ import annotations

import ast
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

from ..errors import MicropyError
from .context import (
    ANNOTATION_TYPES,
    API_FUNCTIONS,
    ARDUINO_CONSTANTS,
    ARDUINO_OBJECTS,
    BUILTIN_FUNCTIONS,
    CONFLICT_TYPE,
    DEFAULT_TYPE,
    PYTHON_BUILTIN_HINTS,
    UNKNOWN_TYPE,
    VOID_TYPE,
    ClassInfo,
    CompileContext,
    FunctionInfo,
    MethodInfo,
    Scope,
    VarInfo,
    merge_types,
)
from .libraries import API_IMPORT_MODULES, LIBRARIES

__all__ = ["Validator", "UNSUPPORTED_FEATURES"]

#: Python constructs that micropy knows about but deliberately does not support.
UNSUPPORTED_FEATURES: Dict[type, str] = {
    ast.AsyncFunctionDef: "async function",
    ast.Await: "await expression",
    ast.AsyncFor: "async for loop",
    ast.AsyncWith: "async with statement",
    ast.Lambda: "lambda expression",
    ast.With: "with statement",
    ast.Try: "try/except",
    ast.Raise: "raise statement",
    ast.Assert: "assert statement",
    ast.Global: "global statement",
    ast.Nonlocal: "nonlocal statement",
    ast.Delete: "del statement",
    ast.Match: "match statement",
    ast.Yield: "yield expression",
    ast.YieldFrom: "yield from expression",
    ast.ListComp: "list comprehension",
    ast.SetComp: "set comprehension",
    ast.DictComp: "dict comprehension",
    ast.GeneratorExp: "generator expression",
    ast.Dict: "dict literal",
    ast.Set: "set literal",
    ast.Starred: "starred expression",
    ast.Slice: "slice",
    ast.JoinedStr: "f-string",
    ast.FormattedValue: "f-string",
    ast.NamedExpr: "walrus operator (:=",
}

_RETYPE_PASSES = 4
_INT_MIN = -2147483648
_INT_MAX = 2147483647


def _humanize(class_name: str) -> str:
    """``AsyncFunctionDef`` -> ``async function def`` (fallback wording)."""

    out = []
    for index, char in enumerate(class_name):
        if char.isupper() and index:
            out.append(" ")
        out.append(char.lower())
    return "".join(out)


def unsupported_label(node: ast.AST) -> str:
    """Human readable name for an unsupported node."""

    for cls in type(node).__mro__:
        if cls in UNSUPPORTED_FEATURES:
            return UNSUPPORTED_FEATURES[cls]
    return _humanize(type(node).__name__)


def is_docstring(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def iter_statements(body: Sequence[ast.stmt]) -> Iterator[ast.stmt]:
    """Yield statements of *body* in source order, without entering defs."""

    for stmt in body:
        yield stmt
        if isinstance(stmt, ast.If):
            yield from iter_statements(stmt.body)
            yield from iter_statements(stmt.orelse)
        elif isinstance(stmt, (ast.While, ast.For)):
            yield from iter_statements(stmt.body)
            yield from iter_statements(stmt.orelse)


def target_names(target: ast.AST) -> List[Tuple[str, ast.AST]]:
    """Plain ``Name`` targets (attributes/subscripts are bound separately)."""

    if isinstance(target, ast.Name):
        return [(target.id, target)]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: List[Tuple[str, ast.AST]] = []
        for element in target.elts:
            names.extend(target_names(element))
        return names
    return []


def constant_int(node: ast.AST) -> Optional[int]:
    """Value of an integer literal, including ``-1``."""

    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return int(node.value)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
        and not isinstance(node.operand.value, bool)
    ):
        return -int(node.operand.value)
    return None


def is_bool_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, bool)


def types_compatible(declared: str, inferred: str) -> bool:
    """Can *inferred* be stored in something declared as *declared*?"""

    if inferred in (UNKNOWN_TYPE, CONFLICT_TYPE):
        return True
    if declared == inferred:
        return True
    if declared == "float" and inferred in ("int", "bool", "char"):
        return True
    if declared == "int" and inferred in ("bool", "char"):
        return True
    if declared == "String" and inferred == "const char*":
        return True
    return False


def check_reserved_variable(context: CompileContext, node: ast.AST, name: str) -> None:
    """Names owned by the Arduino core cannot become variables."""

    if name in ARDUINO_OBJECTS or name in ARDUINO_CONSTANTS:
        context.error(
            node,
            f"'{name}' is used by the Arduino core and cannot be a variable name.",
            hint="Please pick another name.",
        )


def resolve_annotation(context: CompileContext, node: ast.AST) -> str:
    """Map a Python type annotation onto a C++ type."""

    if isinstance(node, ast.Constant) and node.value is None:
        return VOID_TYPE
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        mapped = ANNOTATION_TYPES.get(node.value)
        if mapped:
            return mapped
    if isinstance(node, ast.Name):
        mapped = ANNOTATION_TYPES.get(node.id)
        if mapped:
            return mapped
        if node.id in context.classes:
            return node.id
        if node.id in context.external_types:
            return context.external_types[node.id]
        context.error(
            node,
            f"Unsupported type annotation: '{node.id}'",
            hint="Supported annotations:",
            hint_lines=["int", "float", "bool", "str"] + sorted(context.classes),
        )
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id in LIBRARIES:
            return node.attr
    context.error(node, "Unsupported type annotation.")
    return UNKNOWN_TYPE  # pragma: no cover - error() always raises


def _merge_observed(observed: Sequence[Optional[str]]) -> str:
    """Combine the observed return types of one function into a C++ type."""

    merged: Optional[str] = None
    for observed_type in observed:
        if observed_type is None:
            continue
        merged = merge_types(merged, observed_type)
        if merged == CONFLICT_TYPE:
            return UNKNOWN_TYPE  # _resolve_return_type() reports the conflict
    if merged is None:
        return VOID_TYPE
    return merged


class Validator:
    """Validates a module and fills the :class:`CompileContext` symbol tables."""

    def __init__(self, context: CompileContext) -> None:
        self.ctx = context
        self._declared_globals: Set[str] = set()

    # ------------------------------------------------------------------ api
    def validate(self, module: ast.Module) -> CompileContext:
        self.ctx.module = module
        self._collect(module)
        self._check_entry_points()
        analyzer = _BodyAnalyzer(self.ctx)
        analyzer.visit(module)
        # Types first (parameters and locals), then return types: a function that
        # does `return a + b` can only be typed once `a` and `b` are known, and
        # `value = helper()` can only be typed once helper() has a return type.
        self._finalize_types()
        for _ in range(_RETYPE_PASSES):
            changed = analyzer.retype_returns()
            self._finalize_types()
            if analyzer.refine_local_types():
                changed = True
                self._finalize_types()
            if not changed:
                break
        self._finalize_returns()
        return self.ctx

    # ------------------------------------------------- phase A: definitions
    def _collect(self, module: ast.Module) -> None:
        for node in module.body:
            self._collect_top_level(node)

    def _collect_top_level(self, node: ast.stmt) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self._collect_import(node)
        elif isinstance(node, ast.FunctionDef):
            self._collect_function(node)
        elif isinstance(node, ast.ClassDef):
            self._collect_class(node)
        elif isinstance(node, ast.Assign):
            self._collect_global_assign(node)
        elif isinstance(node, ast.AnnAssign):
            self._collect_global_annassign(node)
        elif isinstance(node, ast.AugAssign):
            self.ctx.error(
                node,
                "Top-level augmented assignment is not supported.",
                hint="Arduino has no top-level code: update the variable inside main() or loop().",
            )
        elif isinstance(node, (ast.Pass, ast.Expr)):
            if isinstance(node, ast.Expr) and not is_docstring(node):
                self.ctx.error(
                    node,
                    "Top-level statements are not supported.",
                    hint="Move this call into main() or loop(); on Arduino only setup() and loop() run.",
                )
        else:
            self._unsupported(node)

    def _unsupported(self, node: ast.AST) -> None:
        self.ctx.error(node, f"Unsupported Python feature: {unsupported_label(node)}")

    # imports
    def _collect_import(self, node: ast.stmt) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if alias.name in API_IMPORT_MODULES or root in API_IMPORT_MODULES:
                    continue  # `import micropy` is accepted for IDE support only
                library = LIBRARIES.get(root)
                if library is not None:
                    self.ctx.register_library(library)
                    continue
                self._unsupported_library(node, alias.name)
            return

        module = node.module or ""
        if node.level:
            self.ctx.error(node, "Unsupported Python feature: relative import")
        root = module.split(".")[0]
        if module in API_IMPORT_MODULES or root in API_IMPORT_MODULES:
            for alias in node.names:
                if alias.name == "*":
                    continue
                if not self.ctx.register_api_import(alias.name):
                    self.ctx.error(
                        node,
                        f"'{alias.name}' is not part of the micropy API.",
                        hint="Known names:",
                        hint_lines=sorted(API_FUNCTIONS) + sorted(LIBRARIES),
                    )
            return

        library = LIBRARIES.get(root)
        if library is not None and root == module:
            self.ctx.register_library(library)
            for alias in node.names:
                if alias.name in ("*", root):
                    continue
                self.ctx.error(node, f"'{alias.name}' cannot be imported from {module}.")
            return
        self._unsupported_library(node, module or "(relative)")

    def _unsupported_library(self, node: ast.AST, name: str) -> None:
        self.ctx.error(
            node,
            f"Python library '{name}' is not supported on Arduino.",
            hint="Arduino libraries you can import:",
            hint_lines=[f"from micropy import {lib}" for lib in sorted(LIBRARIES)]
            + ["from micropy import *  (IDE/type-checker support only)"],
        )

    # functions
    def _check_user_name(self, node: ast.AST, name: str) -> None:
        if name in API_FUNCTIONS:
            self.ctx.error(
                node, f"'{name}' is an ArduinoPy function and cannot be redefined.", hint="Please pick another name."
            )
        if name in BUILTIN_FUNCTIONS:
            self.ctx.error(
                node, f"'{name}' is provided by Arduino and cannot be redefined.", hint="Please pick another name."
            )
        if name in ARDUINO_CONSTANTS or name in ARDUINO_OBJECTS:
            self.ctx.error(
                node, f"'{name}' is an Arduino name and cannot be redefined.", hint="Please pick another name."
            )

    def _check_reserved_variable(self, node: ast.AST, name: str) -> None:
        check_reserved_variable(self.ctx, node, name)

    def _collect_params(self, node: ast.FunctionDef, *, skip_self: bool) -> List[VarInfo]:
        args = node.args
        if args.posonlyargs:
            self.ctx.error(node, "Unsupported Python feature: positional-only parameters")
        if args.vararg is not None:
            self.ctx.error(node, "Unsupported Python feature: *args")
        if args.kwarg is not None:
            self.ctx.error(node, "Unsupported Python feature: **kwargs")
        if args.kwonlyargs:
            self.ctx.error(node, "Unsupported Python feature: keyword-only parameters")
        if args.defaults:
            self.ctx.error(
                args.defaults[0],
                "Unsupported Python feature: default parameter values",
                hint="Always pass every argument, or define two separate functions.",
            )

        collected = list(args.args)
        if skip_self:
            if not collected or collected[0].arg != "self":
                self.ctx.error(node, f"Method '{node.name}' must take 'self' as its first parameter.")
            collected = collected[1:]

        params: List[VarInfo] = []
        seen: Set[str] = set()
        for arg in collected:
            if arg.arg in seen:
                self.ctx.error(arg, f"Duplicate parameter name: '{arg.arg}'")
            seen.add(arg.arg)
            self._check_reserved_variable(arg, arg.arg)
            annotation = self._annotation(arg.annotation) if arg.annotation is not None else None
            if annotation == VOID_TYPE:
                self.ctx.error(arg, f"Parameter '{arg.arg}' cannot be annotated as None.")
            params.append(
                VarInfo(
                    name=arg.arg,
                    is_param=True,
                    cpp_type=annotation or UNKNOWN_TYPE,
                    lineno=arg.lineno,
                    col_offset=arg.col_offset,
                )
            )
        return params

    def _annotation(self, node: ast.AST) -> str:
        return resolve_annotation(self.ctx, node)

    def _collect_function(self, node: ast.FunctionDef) -> None:
        name = node.name
        if node.decorator_list:
            self.ctx.error(node.decorator_list[0], "Unsupported Python feature: decorator")
        self._check_user_name(node, name)
        params = self._collect_params(node, skip_self=False)
        annotated = self._annotation(node.returns) if node.returns is not None else None

        if name in ("main", "loop"):
            if params:
                self.ctx.error(node, f"{name}() must not take any parameters.", hint=f"def {name}():")
            if annotated not in (None, VOID_TYPE):
                self.ctx.error(node.returns, f"{name}() must not return a value.")
            if name == "main":
                if self.ctx.setup_node is not None:
                    self.ctx.error(node, "Function 'main' is defined more than once.")
                self.ctx.setup_node = node
            else:
                if self.ctx.loop_node is not None:
                    self.ctx.error(node, "Function 'loop' is defined more than once.")
                self.ctx.loop_node = node
            return

        if name in self.ctx.functions or name in self.ctx.classes:
            self.ctx.error(node, f"Function '{name}' is defined more than once.")
        info = FunctionInfo(
            name=name,
            params=params,
            annotated_return=annotated,
            return_type=annotated or UNKNOWN_TYPE,
            node=node,
            lineno=node.lineno,
            col_offset=node.col_offset,
        )
        self.ctx.add_function(info)

    # classes
    def _collect_class(self, node: ast.ClassDef) -> None:
        name = node.name
        if node.decorator_list:
            self.ctx.error(node.decorator_list[0], "Unsupported Python feature: decorator")
        if node.bases or node.keywords:
            self.ctx.error(node, "Unsupported Python feature: class inheritance")
        self._check_user_name(node, name)
        if name in self.ctx.classes or name in self.ctx.functions:
            self.ctx.error(node, f"Class '{name}' is defined more than once.")

        info = ClassInfo(name=name, node=node, lineno=node.lineno, col_offset=node.col_offset)
        for item in node.body:
            if is_docstring(item) or isinstance(item, ast.Pass):
                continue
            if isinstance(item, ast.FunctionDef):
                if item.decorator_list:
                    self.ctx.error(item.decorator_list[0], "Unsupported Python feature: decorator")
                if item.name != "__init__" and item.name.startswith("__") and item.name.endswith("__"):
                    self.ctx.error(item, f"Unsupported Python feature: special method '{item.name}'")
                params = self._collect_params(item, skip_self=True)
                annotated = self._annotation(item.returns) if item.returns is not None else None
                method = MethodInfo(
                    name=item.name,
                    params=params,
                    annotated_return=annotated,
                    return_type=annotated or UNKNOWN_TYPE,
                    is_constructor=item.name == "__init__",
                    node=item,
                    lineno=item.lineno,
                    col_offset=item.col_offset,
                )
                if method.is_constructor:
                    if annotated not in (None, VOID_TYPE):
                        self.ctx.error(item.returns, "__init__ must not return a value.")
                    method.return_type = VOID_TYPE
                    method.annotated_return = VOID_TYPE
                    info.constructor = method
                else:
                    if item.name in info.methods:
                        self.ctx.error(item, f"Method '{item.name}' is defined more than once.")
                    info.methods[item.name] = method
            elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                self.ctx.error(
                    item,
                    "Class attributes are not supported.",
                    hint="Create instance attributes inside __init__:",
                    hint_lines=["def __init__(self, pin):", "    self.pin = pin"],
                )
            else:
                self._unsupported(item)
        self.ctx.add_class(info)

    def _collect_global_targets(self, target: ast.AST) -> List[ast.Name]:
        if isinstance(target, (ast.Tuple, ast.List)):
            names: List[ast.Name] = []
            for element in target.elts:
                names.extend(self._collect_global_targets(element))
            return names
        if not isinstance(target, ast.Name):
            self.ctx.error(
                target,
                "Only simple names can be assigned at the top level.",
                hint="Global variables are plain names, e.g. LED = 13.",
            )
        self._check_user_name(target, target.id)
        if target.id in self._declared_globals:
            self.ctx.error(
                target,
                f"Global variable '{target.id}' is assigned more than once at the top level.",
                hint="Change its value inside main() or loop() instead.",
            )
        self._declared_globals.add(target.id)
        return [target]

    def _collect_global_assign(self, node: ast.Assign) -> None:
        targets: List[ast.Name] = []
        for target in node.targets:
            targets.extend(self._collect_global_targets(target))
        self._check_global_value(node.value)
        for target in targets:
            var = self.ctx.add_global(target.id, target)
            var.value = node.value
            var.write_count += 1

    def _collect_global_annassign(self, node: ast.AnnAssign) -> None:
        if not isinstance(node.target, ast.Name):
            self.ctx.error(node.target, "Only simple names can be assigned at the top level.")
        self._check_user_name(node.target, node.target.id)
        name = node.target.id
        if name in self._declared_globals:
            self.ctx.error(
                node.target,
                f"Global variable '{name}' is assigned more than once at the top level.",
                hint="Change its value inside main() or loop() instead.",
            )
        self._declared_globals.add(name)
        annotation = self._annotation(node.annotation)
        if annotation == VOID_TYPE:
            self.ctx.error(node.annotation, "'None' is not a valid variable type.")
        var = self.ctx.add_global(name, node.target)
        var.cpp_type = annotation
        var.value = node.value
        if node.value is not None:
            self._check_global_value(node.value)
            var.write_count += 1

    def _call_kind(self, call: ast.Call) -> str:
        """Classify a call target (``api``, ``serial``, ``user``, ...)."""

        func = call.func
        if isinstance(func, ast.Name):
            name = func.id
            api = API_FUNCTIONS.get(name)
            if api is not None:
                return "serial" if api.receiver else "api"
            if name in BUILTIN_FUNCTIONS or name in ("len", "String"):
                return "builtin"
            if name in self.ctx.functions:
                return "user"
            if name in self.ctx.classes or name in self.ctx.external_types:
                return "constructor"
            return "unknown"
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id in ARDUINO_OBJECTS:
                return "serial"
            return "method"
        return "unknown"

    def _check_global_value(self, value: ast.AST) -> None:
        for node in ast.walk(value):
            if isinstance(node, ast.Call) and self._call_kind(node) in (
                "api",
                "serial",
                "user",
                "method",
                "unknown",
            ):
                self.ctx.error(
                    node,
                    "Global variables cannot call this function during initialization.",
                    hint="On Arduino the hardware is not ready at that point; assign the value inside main().",
                )

    # ----------------------------------------------------- phase C: finalize
    def _check_entry_points(self) -> None:
        hint_lines = ["def main():   # becomes void setup()", "def loop():   # becomes void loop()"]
        hint = "A micropy program defines both entry points:"
        if self.ctx.setup_node is None:
            raise MicropyError(
                "Missing required function: main()", filename=self.ctx.filename, hint=hint, hint_lines=hint_lines
            )
        if self.ctx.loop_node is None:
            raise MicropyError(
                "Missing required function: loop()", filename=self.ctx.filename, hint=hint, hint_lines=hint_lines
            )

    def _var_error(self, var: VarInfo, message: str, *, hint: Optional[str] = None) -> None:
        raise MicropyError(
            message,
            filename=self.ctx.filename,
            line=var.lineno,
            col=None if var.col_offset is None else var.col_offset + 1,
            hint=hint,
        )

    def _finalize_var(self, var: VarInfo) -> None:
        merged = var.final_type()
        if merged == CONFLICT_TYPE:
            self._var_error(
                var,
                f"'{var.name}' is assigned values of incompatible types.",
                hint="Use a single type for each variable, e.g. 1.0 for float values and 1 for int values.",
            )
        if merged:
            var.cpp_type = merged
        elif var.cpp_type in (None, UNKNOWN_TYPE):
            var.cpp_type = DEFAULT_TYPE
        if var.is_global:
            var.is_const = (
                var.value is not None
                and var.write_count == 1
                and not self.ctx.is_object_type(var.cpp_type)
                and var.cpp_type not in ARDUINO_OBJECTS
            )

    def _finalize_locals(self, params: Sequence[VarInfo], locals_: Dict[str, VarInfo]) -> None:
        for var in list(params):
            self._finalize_var(var)
            var.is_const = False
        for var in locals_.values():
            self._finalize_var(var)
            self._check_hoisted_object(var)

    def _check_hoisted_object(self, var: VarInfo) -> None:
        """Objects declared at the top of a function need a default constructor."""

        if var.declare_node is not None or not self.ctx.is_object_type(var.cpp_type):
            return
        cls = self.ctx.class_of(var.cpp_type)
        if cls is not None and cls.constructor is not None and cls.constructor.params:
            self._var_error(
                var,
                f"Object '{var.name}' has to be created directly in the function body.",
                hint=f"{cls.name}() needs arguments and C++ has no default constructor for it; "
                "move the line out of the if/for/while block.",
            )

    def _resolve_return_type(
        self,
        label: str,
        observed: Sequence[Optional[str]],
        annotated: Optional[str],
        node: Optional[ast.AST],
    ) -> str:
        merged: Optional[str] = None
        for observed_type in observed:
            if observed_type is None:
                continue
            merged = merge_types(merged, observed_type)
            if merged == CONFLICT_TYPE:
                self.ctx.error(
                    node,
                    f"'{label}' returns values of incompatible types.",
                    hint="Make every return statement use the same type.",
                )
        has_bare_return = any(item is None for item in observed)

        if annotated:
            if annotated == VOID_TYPE:
                if merged:
                    self.ctx.error(node, f"'{label}' is annotated to return None but returns a value.")
                return VOID_TYPE
            if merged and not types_compatible(annotated, merged):
                self.ctx.error(node, f"'{label}' is annotated to return {annotated} but returns {merged}.")
            return annotated
        if merged is None:
            return VOID_TYPE
        if has_bare_return:
            self.ctx.error(node, f"'{label}' mixes 'return' with and without a value.")
        return DEFAULT_TYPE if merged == UNKNOWN_TYPE else merged

    def _finalize_types(self) -> None:
        """Give every variable, parameter and attribute a concrete C++ type."""

        for var in self.ctx.globals.values():
            self._finalize_var(var)
        for info in self.ctx.functions.values():
            self._finalize_locals(info.params, info.locals)
        for info in (self.ctx.setup_info, self.ctx.loop_info):
            if info is not None:
                self._finalize_locals(info.params, info.locals)
        for cls in self.ctx.classes.values():
            for method in self._class_methods(cls):
                self._finalize_locals(method.params, method.locals)
            for field in cls.fields.values():
                self._finalize_var(field)
            for method in cls.methods.values():
                if method.name in cls.fields:
                    self.ctx.error(
                        method.node,
                        f"'{method.name}' is used as an attribute and as a method of class '{cls.name}'.",
                        hint="Rename one of them; C++ members cannot share a name.",
                    )
    def _finalize_returns(self) -> None:
        """Turn the observed return types into concrete C++ return types."""

        for info in self.ctx.functions.values():
            info.return_type = self._resolve_return_type(
                f"{info.name}()", info.observed_returns, info.annotated_return, info.node
            )
        for cls in self.ctx.classes.values():
            for method in self._class_methods(cls):
                label = f"{cls.name}()" if method.is_constructor else f"{cls.name}.{method.name}()"
                method.return_type = self._resolve_return_type(
                    label, method.observed_returns, method.annotated_return, method.node
                )

    @staticmethod
    def _class_methods(cls: ClassInfo) -> List[MethodInfo]:
        methods: List[MethodInfo] = []
        if cls.constructor is not None:
            methods.append(cls.constructor)
        methods.extend(cls.methods.values())
        return methods


class _BodyAnalyzer(ast.NodeVisitor):
    """Validates every statement/expression and infers variable types.

    Expressions are analysed by :meth:`_type`, which both checks the construct
    and returns its C++ type.  Statement handlers are plain ``visit_*`` methods;
    anything not handled falls through to :meth:`generic_visit` and is reported
    as unsupported instead of being silently ignored.
    """

    def __init__(self, context: CompileContext) -> None:
        self.ctx = context
        self.scope = context.scope
        self.owner: Optional[object] = None
        self.class_info: Optional[ClassInfo] = None
        self.entry_name: Optional[str] = None

    # ---------------------------------------------------------------- guards
    def generic_visit(self, node: ast.AST) -> None:  # pragma: no cover - safety net
        self.ctx.error(node, f"Unsupported Python feature: {unsupported_label(node)}")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.ctx.error(
            node,
            "Unsupported Python feature: nested function",
            hint="Define every function at the top level of the file.",
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.ctx.error(node, "Unsupported Python feature: nested class")

    def visit_Import(self, node: ast.Import) -> None:
        self.ctx.error(node, "Unsupported Python feature: import inside a function", hint="Put all imports at the top of the file.")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.ctx.error(node, "Unsupported Python feature: import inside a function", hint="Put all imports at the top of the file.")

    # ---------------------------------------------------------------- module
    def visit_Module(self, node: ast.Module) -> None:
        # Globals first so that functions can be analysed with known types.
        for stmt in node.body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                self._analyze_global(stmt)
        for stmt in node.body:
            self._analyze_top_level(stmt)

    def _analyze_top_level(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, (ast.Import, ast.ImportFrom, ast.Pass, ast.Assign, ast.AnnAssign)) or is_docstring(stmt):
            return
        if isinstance(stmt, ast.FunctionDef):
            if stmt is self.ctx.setup_node or stmt is self.ctx.loop_node:
                self._analyze_entry_point(stmt)
            else:
                self._analyze_function(stmt)
            return
        if isinstance(stmt, ast.ClassDef):
            self._analyze_class(stmt)

    def _analyze_global(self, stmt: ast.stmt) -> None:
        value = getattr(stmt, "value", None)
        if isinstance(stmt, ast.AnnAssign):
            variable = self.ctx.globals.get(stmt.target.id)
            if variable is not None:
                variable.record_type(variable.cpp_type)
        if value is None:
            return
        targets = getattr(stmt, "targets", None)
        if targets is None:
            targets = [stmt.target]
        for target in targets:
            for name, _ in target_names(target):
                variable = self.ctx.globals.get(name)
                if variable is not None:
                    self._bind_value(variable, value)

    def _bind_value(self, var: VarInfo, value: ast.AST) -> None:
        """Record the type of *value* on *var* (module level binding)."""

        if isinstance(value, (ast.List, ast.Tuple)):
            element_type, length = self._literal_elements(value)
            var.is_array = True
            var.array_len = length
            var.record_type(element_type)
            return
        inferred = self._type(value)
        var.record_type(inferred)
        if self.ctx.is_object_type(inferred):
            var.is_object = True

    # ------------------------------------------------------------- functions
    def _analyze_entry_point(self, node: ast.FunctionDef) -> None:
        info = FunctionInfo(
            name=node.name,
            return_type=VOID_TYPE,
            annotated_return=VOID_TYPE,
            node=node,
            lineno=node.lineno,
            col_offset=node.col_offset,
        )
        if node.name == "main":
            self.ctx.setup_info = info
        else:
            self.ctx.loop_info = info
        scope = Scope("function", owner=node.name, parent=self.ctx.scope)
        self._prepare_locals(node, scope, [], info)
        self._run_body(scope, info, None, node.name, node.body)

    def _analyze_function(self, node: ast.FunctionDef) -> None:
        info = self.ctx.functions[node.name]
        scope = Scope("function", owner=info.name, parent=self.ctx.scope)
        for param in info.params:
            scope.declare(
                VarInfo(
                    name=param.name,
                    is_param=True,
                    cpp_type=param.cpp_type,
                    lineno=param.lineno,
                    col_offset=param.col_offset,
                )
            )
        self._prepare_locals(node, scope, info.params, info)
        self._run_body(scope, info, None, None, node.body)

    def _run_body(
        self,
        scope: Scope,
        owner: object,
        class_info: Optional[ClassInfo],
        entry_name: Optional[str],
        body: Sequence[ast.stmt],
    ) -> None:
        previous = (self.scope, self.owner, self.class_info, self.entry_name)
        self.scope, self.owner, self.class_info, self.entry_name = scope, owner, class_info, entry_name
        try:
            self._analyze_body(body)
        finally:
            self.scope, self.owner, self.class_info, self.entry_name = previous

    def _analyze_body(self, body: Sequence[ast.stmt]) -> None:
        for stmt in body:
            self.visit(stmt)

    def _prepare_locals(
        self,
        node: ast.FunctionDef,
        scope: Scope,
        params: Sequence[VarInfo],
        info: object,
    ) -> None:
        """Hoist local variables, following Python's function-wide scoping."""

        param_names = {param.name for param in params}
        first_assignment: Dict[str, ast.stmt] = {}
        assigned_at: Dict[str, ast.AST] = {}
        loop_vars: Dict[str, ast.stmt] = {}

        for stmt in iter_statements(node.body):
            if isinstance(stmt, ast.For):
                for name, target in target_names(stmt.target):
                    loop_vars.setdefault(name, stmt)
                    assigned_at.setdefault(name, target)
            else:
                targets = list(getattr(stmt, "targets", [])) or (
                    [stmt.target] if isinstance(stmt, (ast.AnnAssign, ast.AugAssign)) else []
                )
                for target in targets:
                    for name, target_node in target_names(target):
                        first_assignment.setdefault(name, stmt)
                        assigned_at.setdefault(name, target_node)

        for name, stmt in loop_vars.items():
            self._check_reserved_variable(loop_vars[name], name)
            if name in scope.variables:
                self.ctx.error(
                    loop_vars[name],
                    f"Loop variable '{name}' hides the parameter '{name}'.",
                    hint="Rename the loop variable.",
                )
            if name in self.ctx.globals:
                self.ctx.error(
                    loop_vars[name],
                    f"Loop variable '{name}' hides the global variable '{name}'.",
                    hint="Rename the loop variable.",
                )
            # The C++ for-loop declares the variable itself; make it visible for
            # the rest of the function body so reads/writes can be type-checked.
            if not scope.has_local(name):
                scope.declare(
                    VarInfo(
                        name=name,
                        cpp_type="int",
                        lineno=getattr(assigned_at.get(name), "lineno", None),
                        col_offset=getattr(assigned_at.get(name), "col_offset", None),
                    )
                )

        direct_statements = {id(stmt) for stmt in node.body}
        for name, stmt in first_assignment.items():
            if name in param_names or name in self.ctx.globals:
                continue  # parameters and module level names are not locals
            if name in loop_vars:
                self.ctx.error(
                    stmt,
                    f"Loop variable '{name}' is also used outside the loop.",
                    hint="Rename the loop variable.",
                )
            self._check_reserved_variable(assigned_at.get(name, node), name)
            var = VarInfo(
                name=name,
                value=getattr(stmt, "value", None),
                lineno=getattr(assigned_at.get(name), "lineno", None),
                col_offset=getattr(assigned_at.get(name), "col_offset", None),
            )
            scope.declare(var)
            getattr(info, "locals")[name] = var
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and id(stmt) in direct_statements:
                var.declare_node = stmt
            else:
                getattr(info, "hoisted").append(name)

    # --------------------------------------------------------------- classes
    def _analyze_class(self, node: ast.ClassDef) -> None:
        info = self.ctx.classes[node.name]
        methods: List[MethodInfo] = []
        if info.constructor is not None:
            methods.append(info.constructor)
        methods.extend(info.methods.values())
        self._prepare_fields(info, methods)
        for method in methods:
            self._analyze_method(info, method)

    def _prepare_fields(self, info: ClassInfo, methods: Sequence[MethodInfo]) -> None:
        """Collect ``self.x = ...`` targets so fields exist before analysis."""

        for method in methods:
            if method.node is None:
                continue
            for stmt in iter_statements(method.node.body):
                targets = getattr(stmt, "targets", None)
                if targets is None:
                    targets = [stmt.target] if isinstance(stmt, (ast.AnnAssign, ast.AugAssign)) else []
                for target in targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        info.fields.setdefault(
                            target.attr,
                            VarInfo(name=target.attr, lineno=target.lineno, col_offset=target.col_offset),
                        )

    def _analyze_method(self, info: ClassInfo, method: MethodInfo) -> None:
        if method.node is None:  # pragma: no cover - defensive
            return
        scope = Scope("method", owner=f"{info.name}.{method.name}", parent=self.ctx.scope)
        scope.declare(VarInfo(name="self", is_param=True, is_object=True, cpp_type=info.name))
        for param in method.params:
            scope.declare(
                VarInfo(
                    name=param.name,
                    is_param=True,
                    cpp_type=param.cpp_type,
                    lineno=param.lineno,
                    col_offset=param.col_offset,
                )
            )
        self._prepare_locals(method.node, scope, method.params, method)
        self._run_body(scope, method, info, None, method.node.body)

    # --------------------------------------------------------- annotations
    def _check_reserved_variable(self, node: ast.AST, name: str) -> None:
        check_reserved_variable(self.ctx, node, name)

    def _annotation(self, node: ast.AST) -> str:
        return resolve_annotation(self.ctx, node)

    # ------------------------------------------------------------ statements
    def visit_Assign(self, node: ast.Assign) -> None:
        targets = list(node.targets)
        if len(targets) == 1 and isinstance(targets[0], (ast.Tuple, ast.List)) and isinstance(
            node.value, (ast.Tuple, ast.List)
        ):
            target_elements = targets[0].elts
            value_elements = node.value.elts
            if len(target_elements) != len(value_elements):
                self.ctx.error(
                    node,
                    "Cannot unpack: the number of names and values does not match.",
                    hint="Use the same number of names and values.",
                )
            for target, value in zip(target_elements, value_elements):
                self._bind_target(target, node, types=(self._type(value),))
            return
        if isinstance(node.value, (ast.List, ast.Tuple)):
            element_type, length = self._literal_elements(node.value)
            for target in targets:
                self._bind_target(target, node, types=(element_type,), is_array=True, array_len=length)
            return
        inferred = self._type(node.value)
        for target in targets:
            self._bind_target(target, node, types=(inferred,))

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        declared = self._annotation(node.annotation)
        if declared == VOID_TYPE:
            self.ctx.error(node.annotation, "'None' is not a valid variable type.")
        if isinstance(node.value, (ast.List, ast.Tuple)):
            element_type, length = self._literal_elements(node.value)
            self._bind_target(
                node.target, node, types=(declared, element_type), is_array=True, array_len=length
            )
            return
        inferred = self._type(node.value) if node.value is not None else None
        types = (declared,) if inferred is None else (declared, inferred)
        self._bind_target(node.target, node, types=types)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        label = _augassign_label(node.op)
        if label is None:
            self.ctx.error(node, f"Unsupported augmented assignment: {type(node.op).__name__}")
        target_type = self._type(node.target)
        if target_type in ("const char*", "String"):
            self.ctx.error(node, f"Cannot use {label} on a string.")
            return
        self._type(node.value)
        self._bind_target(node.target, node, types=())

    def visit_Expr(self, node: ast.Expr) -> None:
        if is_docstring(node):
            return
        self._type(node.value)

    def visit_If(self, node: ast.If) -> None:
        self._type(node.test)
        self._analyze_body(node.body)
        self._analyze_body(node.orelse)

    def visit_While(self, node: ast.While) -> None:
        if node.orelse:
            self.ctx.error(node, "Unsupported Python feature: while/else")
        self._type(node.test)
        self._analyze_body(node.body)

    def visit_For(self, node: ast.For) -> None:
        if node.orelse:
            self.ctx.error(node, "Unsupported Python feature: for/else")
        if not isinstance(node.target, ast.Name):
            self.ctx.error(node, "For loops must use a single variable: for i in range(...)")
        iterator = node.iter
        if not (
            isinstance(iterator, ast.Call)
            and isinstance(iterator.func, ast.Name)
            and iterator.func.id == "range"
        ):
            self.ctx.error(
                iterator,
                "Only 'for <name> in range(...)' loops are supported.",
                hint="Use a while loop for anything else.",
            )
        self._check_range(iterator)
        self._analyze_body(node.body)

    def _check_range(self, call: ast.Call) -> None:
        if call.keywords:
            self.ctx.error(call, "range() does not accept keyword arguments.")
        args = list(call.args)
        if not 1 <= len(args) <= 3:
            self.ctx.error(call, f"range() takes 1 to 3 arguments but got {len(args)}.")
        for arg in args:
            if self._type(arg) not in ("int", "bool", UNKNOWN_TYPE):
                self.ctx.error(arg, "range() arguments must be integers.")
        if len(args) == 3:
            step = constant_int(args[2])
            if step is None:
                self.ctx.error(
                    args[2],
                    "The step argument of range() must be a constant integer.",
                    hint="C++ for loops cannot change the step at runtime; use a while loop instead.",
                )
            elif step == 0:
                self.ctx.error(args[2], "range() step cannot be zero.")

    def visit_Return(self, node: ast.Return) -> None:
        if self.entry_name:
            if node.value is not None:
                self.ctx.error(node, f"{self.entry_name}() must not return a value.")
            return
        if self.owner is None:
            self.ctx.error(node, "Unsupported Python feature: 'return' outside of a function")
            return
        value_type = self._type(node.value) if node.value is not None else None
        self.owner.observed_returns.append(value_type)  # type: ignore[attr-defined]

    def visit_Break(self, node: ast.Break) -> None:
        return

    def visit_Continue(self, node: ast.Continue) -> None:
        return

    def visit_Pass(self, node: ast.Pass) -> None:
        return

    # ---------------------------------------------------------- assign targets
    def _bind_target(
        self,
        target: ast.AST,
        stmt: ast.stmt,
        *,
        types: Sequence[Optional[str]] = (),
        is_array: bool = False,
        array_len: Optional[int] = None,
    ) -> None:
        if isinstance(target, ast.Name):
            name = target.id
            global_var = self.ctx.globals.get(name)
            if global_var is not None:
                # Top-level names behave like C++ globals: functions assign them.
                global_var.write_count += 1
                for observed in types:
                    global_var.record_type(observed)
                return
            var = self.scope.lookup(name)
            if var is None:
                self.ctx.error(target, f"'{name}' is not defined.")
                return
            if var.is_param:
                return
            if is_array:
                if var.declare_node is not stmt:
                    self.ctx.error(
                        target,
                        f"Array '{name}' must get its values where it is declared.",
                        hint="Move the list literal to the top of the function.",
                    )
                    return
                var.is_array = True
                var.array_len = array_len
            elif var.is_array:
                self.ctx.error(
                    target,
                    f"Array '{name}' cannot be reassigned.",
                    hint="C++ arrays cannot be assigned; write to the elements instead.",
                )
                return
            var.write_count += 1
            for observed in types:
                var.record_type(observed)
            return

        if isinstance(target, ast.Attribute):
            if is_array:
                self.ctx.error(target, "Object attributes cannot hold array values.")
            if isinstance(target.value, ast.Name) and target.value.id == "self":
                if self.class_info is None:
                    self.ctx.error(target, "'self' can only be used inside a class method.")
                    return
                field = self.class_info.fields.get(target.attr)
                if field is None:
                    field = VarInfo(name=target.attr, lineno=target.lineno, col_offset=target.col_offset)
                    self.class_info.fields[target.attr] = field
                field.write_count += 1
                for observed in types:
                    field.record_type(observed)
                return
            base_type = self._type(target.value)
            class_info = self.ctx.class_of(base_type)
            if class_info is None:
                self.ctx.error(target, f"Cannot assign to attribute '{target.attr}' of this value.")
                return
            field = class_info.fields.get(target.attr)
            if field is None:
                self.ctx.error(target, f"Class '{class_info.name}' has no attribute '{target.attr}'.")
                return
            field.write_count += 1
            for observed in types:
                field.record_type(observed)
            return

        if isinstance(target, ast.Subscript):
            base = target.value
            if not isinstance(base, ast.Name):
                self.ctx.error(target, "Unsupported assignment target.")
                return
            var = self.scope.lookup(base.id)
            if var is None:
                self.ctx.error(base, f"'{base.id}' is not defined.")
                return
            if not var.is_array:
                self.ctx.error(target, f"'{base.id}' is not an array, so it cannot be indexed.")
                return
            index_type = self._type(target.slice)
            if index_type not in ("int", "bool", "char", UNKNOWN_TYPE):
                self.ctx.error(target.slice, "Array indices must be integers.")
            var.write_count += 1
            return

        self.ctx.error(target, "Unsupported assignment target.")

    # ------------------------------------------------------------ expressions
    def _type(self, node: ast.AST) -> str:
        """Infer (and validate) the C++ type of an expression."""

        inferred = self._infer(node)
        self.ctx.expression_types[id(node)] = inferred
        return inferred

    def _infer(self, node: ast.AST) -> str:
        if isinstance(node, ast.Constant):
            return self._constant_type(node)
        if isinstance(node, ast.Name):
            return self._name_type(node)
        if isinstance(node, ast.Attribute):
            return self._attribute_type(node)
        if isinstance(node, ast.Call):
            return self._call_type(node)
        if isinstance(node, ast.Subscript):
            return self._subscript_type(node)
        if isinstance(node, ast.BinOp):
            return self._binop_type(node)
        if isinstance(node, ast.UnaryOp):
            return self._unary_type(node)
        if isinstance(node, ast.BoolOp):
            return self._boolop_type(node)
        if isinstance(node, ast.Compare):
            return self._compare_type(node)
        if isinstance(node, ast.IfExp):
            return self._ifexp_type(node)
        if isinstance(node, (ast.List, ast.Tuple)):
            self.ctx.error(
                node,
                "List literals can only be assigned to a variable.",
                hint="values = [1, 2, 3]",
            )
        self.ctx.error(node, f"Unsupported Python feature: {unsupported_label(node)}")
        return UNKNOWN_TYPE  # pragma: no cover - error() always raises

    def _constant_type(self, node: ast.Constant) -> str:
        value = node.value
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            if value < _INT_MIN or value > _INT_MAX:
                self.ctx.error(node, f"Integer literal {value} does not fit into an Arduino int (32 bit).")
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, str):
            return "const char*"
        if value is None:
            self.ctx.error(
                node, "Unsupported Python feature: None", hint="Use a real value, or a bool flag instead."
            )
        if isinstance(value, bytes):
            self.ctx.error(node, "Unsupported Python feature: bytes literal")
        self.ctx.error(node, f"Unsupported literal: {value!r}")
        return UNKNOWN_TYPE  # pragma: no cover

    def _name_type(self, node: ast.Name) -> str:
        name = node.id
        if name in ARDUINO_CONSTANTS:
            return "int"
        if name in ARDUINO_OBJECTS:
            return name
        if name in self.ctx.external_types:
            return self.ctx.external_types[name]
        if name in self.ctx.functions:
            self.ctx.error(node, f"'{name}' is a function; call it like {name}(...)")
        if name == "String":
            self.ctx.error(node, "'String' must be called: String(value)")
        if name in self.ctx.classes:
            self.ctx.error(node, f"'{name}' is a class; create an object with {name}(...)")
        var = self.scope.lookup(name)
        if var is None:
            hint = PYTHON_BUILTIN_HINTS.get(name)
            if hint:
                self.ctx.error(node, f"Python builtin '{name}' is not available on Arduino.", hint=hint)
            self.ctx.error(node, f"Unknown name: '{name}'", hint="Declare it first, or check the spelling.")
        if var.is_array:
            self.ctx.error(
                node,
                f"Array '{name}' cannot be used as a value.",
                hint=f"Index it ({name}[0]) or use len({name}).",
            )
        return self._variable_type(var)

    @staticmethod
    def _variable_type(var: VarInfo) -> str:
        merged = var.final_type()
        if merged and merged != CONFLICT_TYPE:
            return merged
        if var.cpp_type != UNKNOWN_TYPE:
            return var.cpp_type
        return UNKNOWN_TYPE

    def _attribute_type(self, node: ast.Attribute) -> str:
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            if self.class_info is None:
                self.ctx.error(node, "'self' can only be used inside a class method.")
                return UNKNOWN_TYPE
            field = self.class_info.fields.get(node.attr)
            if field is None:
                self.ctx.error(node, f"Class '{self.class_info.name}' has no attribute '{node.attr}'.")
                return UNKNOWN_TYPE
            return self._variable_type(field)
        base_type = self._type(node.value)
        if base_type in ARDUINO_OBJECTS:
            self.ctx.error(node, f"{base_type}.{node.attr} must be called as a method.")
            return UNKNOWN_TYPE
        class_info = self.ctx.class_of(base_type)
        if class_info is None:
            if self.ctx.is_object_type(base_type):
                return UNKNOWN_TYPE  # library object: pass through
            self.ctx.error(node, f"Cannot read attribute '{node.attr}' of this value.")
            return UNKNOWN_TYPE
        field = class_info.fields.get(node.attr)
        if field is None:
            self.ctx.error(node, f"Class '{class_info.name}' has no attribute '{node.attr}'.")
            return UNKNOWN_TYPE
        return self._variable_type(field)

    def _call_type(self, node: ast.Call) -> str:
        if node.keywords:
            self.ctx.error(node, "Unsupported Python feature: keyword arguments")
        if any(isinstance(arg, ast.Starred) for arg in node.args):
            self.ctx.error(node, "Unsupported Python feature: starred arguments")
        func = node.func
        if isinstance(func, ast.Name) and func.id == "len":
            return self._len_type(node)
        arg_types = [self._type(arg) for arg in node.args]
        if isinstance(func, ast.Name):
            return self._name_call_type(node, func.id, arg_types)
        if isinstance(func, ast.Attribute):
            return self._method_call_type(node, func, arg_types)
        self.ctx.error(node.func, "Unsupported call expression.")
        return UNKNOWN_TYPE  # pragma: no cover

    def _name_call_type(self, node: ast.Call, name: str, arg_types: Sequence[str]) -> str:
        api = API_FUNCTIONS.get(name)
        if api is not None:
            self._check_arity(node, name, len(node.args), api.min_args, api.max_args)
            return api.returns
        if name in BUILTIN_FUNCTIONS:
            self._check_arity(node, name, len(node.args), 1, 5)
            if name in ("pow", "sqrt", "floor", "ceil", "round"):
                return "float"
            merged: Optional[str] = None
            for arg_type in arg_types:
                merged = merge_types(merged, arg_type)
                if merged == CONFLICT_TYPE:
                    merged = UNKNOWN_TYPE
                    break
            return merged or UNKNOWN_TYPE
        if name == "len":
            return self._len_type(node)
        if name == "String":
            return "String"
        if name == "range":
            self.ctx.error(node, "range() can only be used in a for loop.")
        cls = self.ctx.classes.get(name)
        if cls is not None:
            params = cls.constructor.params if cls.constructor is not None else []
            self._check_arity(node, name, len(node.args), len(params), len(params))
            for param, arg_type in zip(params, arg_types):
                if param.cpp_type == UNKNOWN_TYPE:
                    param.record_type(arg_type)
            return cls.name
        if name in self.ctx.external_types:
            # Arduino library object, e.g. Servo() -> `Servo servo;`
            return self.ctx.external_types[name]
        info = self.ctx.functions.get(name)
        if info is None:
            hint = PYTHON_BUILTIN_HINTS.get(name)
            if hint:
                self.ctx.error(node, f"Python builtin '{name}' is not available on Arduino.", hint=hint)
            known = sorted(list(API_FUNCTIONS) + list(self.ctx.functions))
            self.ctx.error(
                node,
                f"Unknown ArduinoPy function: {name}()",
                hint="Supported Arduino functions include:",
                hint_lines=[f"{item}()" for item in known],
            )
        self._check_arity(node, name, len(node.args), len(info.params), len(info.params))
        for param, arg_type in zip(info.params, arg_types):
            if param.cpp_type == UNKNOWN_TYPE:
                param.record_type(arg_type)
        return info.return_type or UNKNOWN_TYPE

    def _method_call_type(self, node: ast.Call, func: ast.Attribute, arg_types: Sequence[str]) -> str:
        attr = func.attr
        base = func.value
        if isinstance(base, ast.Name) and base.id == "self":
            if self.class_info is None:
                self.ctx.error(node, "'self' can only be used inside a class method.")
                return UNKNOWN_TYPE
            method = self.class_info.methods.get(attr)
            if method is None:
                if attr in self.class_info.fields:
                    self.ctx.error(node, f"'{attr}' is an attribute of {self.class_info.name}, not a method.")
                    return UNKNOWN_TYPE
                self.ctx.error(node, f"Class '{self.class_info.name}' has no method '{attr}'.")
                return UNKNOWN_TYPE
            self._check_arity(node, f"{self.class_info.name}.{attr}", len(node.args), len(method.params), len(method.params))
            for param, arg_type in zip(method.params, arg_types):
                if param.cpp_type == UNKNOWN_TYPE:
                    param.record_type(arg_type)
            return method.return_type or UNKNOWN_TYPE
        if isinstance(base, ast.Name) and base.id in ARDUINO_OBJECTS:
            return UNKNOWN_TYPE  # Serial.begin(...) / Wire.begin() pass through
        base_type = self._type(base)
        if base_type in ARDUINO_OBJECTS:
            return UNKNOWN_TYPE
        class_info = self.ctx.class_of(base_type)
        if class_info is None:
            if self.ctx.is_object_type(base_type):
                return UNKNOWN_TYPE  # Arduino library API: pass through
            self.ctx.error(node, f"Cannot call method '{attr}' on this value.")
            return UNKNOWN_TYPE
        method = class_info.methods.get(attr)
        if method is None:
            self.ctx.error(node, f"Class '{class_info.name}' has no method '{attr}'.")
            return UNKNOWN_TYPE
        self._check_arity(node, f"{class_info.name}.{attr}", len(node.args), len(method.params), len(method.params))
        for param, arg_type in zip(method.params, arg_types):
            if param.cpp_type == UNKNOWN_TYPE:
                param.record_type(arg_type)
        return method.return_type or UNKNOWN_TYPE

    def _len_type(self, node: ast.Call) -> str:
        """``len(values)`` -> ``sizeof(values) / sizeof(values[0])``."""

        self._check_arity(node, "len", len(node.args), 1, 1)
        base = node.args[0]
        if isinstance(base, ast.Name):
            var = self.scope.lookup(base.id)
            if var is not None and var.is_array:
                return "int"
        self.ctx.error(
            node,
            "len() is only supported for arrays created from a list literal.",
            hint="values = [1, 2, 3]  then  len(values)",
        )
        return "int"  # pragma: no cover

    def _subscript_type(self, node: ast.Subscript) -> str:
        base = node.value
        if not isinstance(base, ast.Name):
            self.ctx.error(node, "Only arrays can be indexed.")
            return UNKNOWN_TYPE
        var = self.scope.lookup(base.id)
        if var is None:
            self.ctx.error(base, f"'{base.id}' is not defined.")
            return UNKNOWN_TYPE
        if not var.is_array:
            self.ctx.error(
                node,
                f"'{base.id}' is not an array, so it cannot be indexed.",
                hint="Only list literals become arrays in micropy.",
            )
            return UNKNOWN_TYPE
        index_type = self._type(node.slice)
        if index_type not in ("int", "bool", "char", UNKNOWN_TYPE):
            self.ctx.error(node.slice, "Array indices must be integers.")
        return self._variable_type(var)

    def _binop_type(self, node: ast.BinOp) -> str:
        left = self._type(node.left)
        right = self._type(node.right)
        op = node.op
        if isinstance(op, (ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift)):
            for operand in (left, right):
                if operand not in ("int", "bool", "char", UNKNOWN_TYPE):
                    self.ctx.error(node, f"Bitwise and shift operators need integer values, not {operand}.")
            return "int"
        if isinstance(op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)):
            for operand in (left, right):
                if operand in ("const char*", "String"):
                    self.ctx.error(
                        node,
                        "String arithmetic is not supported.",
                        hint="Print values separately with serial_print()/serial_println().",
                    )
                if self.ctx.is_object_type(operand):
                    self.ctx.error(node, f"Operators cannot be used with objects of type '{operand}'.")
            if "float" in (left, right):
                return "float"
            if UNKNOWN_TYPE in (left, right):
                return UNKNOWN_TYPE
            return "int"
        if isinstance(op, ast.Pow):
            for operand in (left, right):
                if operand not in ("int", "float", "bool", "char", UNKNOWN_TYPE):
                    self.ctx.error(node, "The '**' operator needs numeric values.")
            return "float" if "float" in (left, right) else "int"
        self.ctx.error(node, f"Unsupported Python feature: operator {type(op).__name__}")
        return UNKNOWN_TYPE  # pragma: no cover

    def _unary_type(self, node: ast.UnaryOp) -> str:
        operand = self._type(node.operand)
        if isinstance(node.op, ast.Not):
            return "bool"
        if isinstance(node.op, ast.Invert):
            if operand not in ("int", "bool", "char", UNKNOWN_TYPE):
                self.ctx.error(node, "'~' needs an integer value.")
            return "int"
        if isinstance(node.op, (ast.USub, ast.UAdd)):
            if operand in ("const char*", "String") or self.ctx.is_object_type(operand):
                self.ctx.error(node, "Unary +/- is not supported for this value.")
            return operand
        self.ctx.error(node, f"Unsupported Python feature: unary {type(node.op).__name__}")
        return UNKNOWN_TYPE  # pragma: no cover

    def _boolop_type(self, node: ast.BoolOp) -> str:
        for value in node.values:
            self._type(value)
        return "bool"

    def _compare_type(self, node: ast.Compare) -> str:
        left_type = self._type(node.left)
        if len(node.ops) > 1:
            for comparator in node.comparators:
                if any(isinstance(child, ast.Call) for child in ast.walk(comparator)):
                    self.ctx.error(
                        node,
                        "Chained comparisons cannot contain function calls.",
                        hint="Split them into two separate conditions.",
                    )
        for op, comparator in zip(node.ops, node.comparators):
            if isinstance(op, (ast.In, ast.NotIn)):
                self.ctx.error(node, "Unsupported Python feature: the 'in' operator")
            if isinstance(op, (ast.Is, ast.IsNot)):
                self.ctx.error(node, "Unsupported Python feature: 'is' comparison", hint="Compare values with == instead.")
            right_type = self._type(comparator)
            if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
                for operand in (left_type, right_type):
                    if operand in ("const char*", "String"):
                        self.ctx.error(
                            node,
                            "Ordered comparison of strings is not supported.",
                            hint="Use == or != for strings.",
                        )
            left_type = right_type
        return "bool"

    def _ifexp_type(self, node: ast.IfExp) -> str:
        self._type(node.test)
        merged = merge_types(self._type(node.body), self._type(node.orelse))
        if merged == CONFLICT_TYPE:
            self.ctx.error(node, "Both branches of a conditional expression must have the same type.")
        return merged or UNKNOWN_TYPE

    def _literal_elements(self, node: ast.AST) -> Tuple[str, int]:
        elements = list(getattr(node, "elts"))
        if not elements:
            self.ctx.error(node, "Empty lists are not supported.", hint="Give the array at least one element.")
        element_type: Optional[str] = None
        for element in elements:
            if isinstance(element, (ast.List, ast.Tuple, ast.Dict, ast.Set)):
                self.ctx.error(element, "Nested lists are not supported on Arduino.", hint="Use separate arrays.")
            observed = self._type(element)
            if self.ctx.is_object_type(observed):
                self.ctx.error(element, "Lists of objects are not supported on Arduino.")
            element_type = merge_types(element_type, observed)
            if element_type == CONFLICT_TYPE:
                self.ctx.error(node, "All elements of a list must have the same type.")
        return (element_type or DEFAULT_TYPE), len(elements)

    def _check_arity(self, node: ast.AST, name: str, given: int, low: int, high: int) -> None:
        if low <= given <= high:
            return
        if low == high:
            expected = f"exactly {low} argument{'s' if low != 1 else ''}"
        else:
            expected = f"{low} to {high} arguments"
        verb = "was" if given == 1 else "were"
        self.ctx.error(node, f"{name}() takes {expected} but {given} {verb} given.")


    # ------------------------------------------------------------ return types
    def retype_returns(self) -> bool:
        """Re-infer return types now that parameters and locals have types.

        A function such as ``def add(a, b): return a + b`` can only be typed
        after the call sites told us that ``a`` and ``b`` are integers, so this
        runs as a small fixpoint loop after the first analysis pass.
        """

        targets = self._return_targets()
        for _ in range(_RETYPE_PASSES):
            changed = False
            for owner, node, class_info in targets:
                if owner.annotated_return is not None or owner in (self.ctx.setup_info, self.ctx.loop_info):
                    continue
                observed = self._collect_return_types(owner, node, class_info)
                if observed != list(owner.observed_returns):
                    owner.observed_returns = observed
                    changed = True
                resolved = _merge_observed(observed)
                if resolved != owner.return_type:
                    owner.return_type = resolved
                    changed = True
            if not changed:
                return False
        return True

    def _return_targets(self) -> List[Tuple[object, ast.FunctionDef, Optional[ClassInfo]]]:
        targets: List[Tuple[object, ast.FunctionDef, Optional[ClassInfo]]] = []
        for info in self.ctx.functions.values():
            if info.node is not None:
                targets.append((info, info.node, None))
        for cls in self.ctx.classes.values():
            for method in Validator._class_methods(cls):
                if method.node is not None:
                    targets.append((method, method.node, cls))
        for info in (self.ctx.setup_info, self.ctx.loop_info):
            if info is not None and info.node is not None:
                targets.append((info, info.node, None))
        return targets

    def refine_local_types(self) -> bool:
        """Type locals that were inferred from a forward referenced function."""

        changed = False
        for owner, _, class_info in self._return_targets():
            scope: Optional[Scope] = None
            for var in getattr(owner, "locals").values():
                if var.value is None or var.final_type() not in (None, UNKNOWN_TYPE, CONFLICT_TYPE):
                    continue
                if scope is None:
                    scope = self._rebuild_scope(owner, class_info)
                inferred = self._safe_type_in(var.value, scope, owner, class_info)
                if inferred in (None, UNKNOWN_TYPE, CONFLICT_TYPE):
                    continue
                var.record_type(inferred)
                changed = True
        return changed

    def _safe_type_in(
        self,
        node: ast.AST,
        scope: Scope,
        owner: object,
        class_info: Optional[ClassInfo],
    ) -> str:
        previous = (self.scope, self.owner, self.class_info, self.entry_name)
        self.scope, self.owner, self.class_info, self.entry_name = scope, owner, class_info, None
        try:
            return self._type(node)
        except MicropyError:
            return UNKNOWN_TYPE
        finally:
            self.scope, self.owner, self.class_info, self.entry_name = previous

    def _collect_return_types(
        self, owner: object, node: ast.FunctionDef, class_info: Optional[ClassInfo]
    ) -> List[Optional[str]]:
        scope = self._rebuild_scope(owner, class_info)
        previous = (self.scope, self.owner, self.class_info, self.entry_name)
        self.scope, self.owner, self.class_info, self.entry_name = scope, owner, class_info, None
        observed: List[Optional[str]] = []
        try:
            for stmt in iter_statements(node.body):
                if isinstance(stmt, ast.Return):
                    observed.append(None if stmt.value is None else self._safe_type(stmt.value))
        finally:
            self.scope, self.owner, self.class_info, self.entry_name = previous
        return observed

    def _safe_type(self, node: ast.AST) -> str:
        """Best effort type for an already validated expression."""

        try:
            return self._type(node)
        except MicropyError:
            return UNKNOWN_TYPE

    def _rebuild_scope(self, owner: object, class_info: Optional[ClassInfo]) -> Scope:
        scope = Scope("function", owner=getattr(owner, "name", None), parent=self.ctx.scope)
        if class_info is not None:
            scope.declare(VarInfo(name="self", is_param=True, is_object=True, cpp_type=class_info.name))
        for param in getattr(owner, "params"):
            scope.declare(
                VarInfo(name=param.name, is_param=True, cpp_type=param.resolved_type())
            )
        for name, var in getattr(owner, "locals").items():
            scope.declare(
                VarInfo(
                    name=name,
                    cpp_type=var.resolved_type(),
                    is_array=var.is_array,
                    array_len=var.array_len,
                )
            )
        return scope

_AUGASSIGN_LABELS: Dict[type, str] = {
    ast.Add: "+=",
    ast.Sub: "-=",
    ast.Mult: "*=",
    ast.Div: "/=",
    ast.Mod: "%=",
    ast.BitAnd: "&=",
    ast.BitOr: "|=",
    ast.BitXor: "^=",
    ast.LShift: "<<=",
    ast.RShift: ">>=",
    ast.FloorDiv: "//=",
    ast.Pow: "**=",
}


def _augassign_label(op: ast.AST) -> Optional[str]:
    return _AUGASSIGN_LABELS.get(type(op))
