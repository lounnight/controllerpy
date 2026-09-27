"""Stage 2, phase 1: collect the top level and give every symbol a type.

:class:`Validator` walks the module once to build the symbol tables (imports,
functions, classes, globals), checks that both entry points exist, and then
finalizes the types the body analysis (:class:`.analyzer.BodyAnalyzer`)
collected.  Anything outside the supported subset is reported here with a
source location instead of being silently dropped.  The walk itself lives in
:mod:`.analyzer`, which is driven from :meth:`Validator.validate`.
"""

from __future__ import annotations

import ast
from typing import Dict, List, Optional, Sequence, Set

from ...errors import ControllerPyError
from .analyzer import RETYPE_PASSES, BodyAnalyzer
from .api import API_FUNCTIONS, ARDUINO_CONSTANTS, ARDUINO_OBJECTS, BUILTIN_FUNCTIONS
from .ast_utils import is_docstring, unsupported_label
from .context import CompileContext
from .libraries import API_IMPORT_MODULES, Library, library_for, supported_libraries
from .naming import check_reserved_variable
from .symbols import ClassInfo, FunctionInfo, MethodInfo, VarInfo
from .types import CONFLICT_TYPE, DEFAULT_TYPE, UNKNOWN_TYPE, VOID_TYPE, merge_types, resolve_annotation, types_compatible

__all__ = ["Validator"]


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
        analyzer = BodyAnalyzer(self.ctx)
        analyzer.visit(module)
        # Types first (parameters and locals), then return types: a function that
        # does `return a + b` can only be typed once `a` and `b` are known, and
        # `value = helper()` can only be typed once helper() has a return type.
        self._finalize_types()
        for _ in range(RETYPE_PASSES):
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
    def _import_library(self, name: str) -> Optional[Library]:
        library = library_for(name)
        if library is not None:
            self.ctx.register_library(library)

        return library

    def _collect_import(self, node: ast.stmt) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if alias.name in API_IMPORT_MODULES or root in API_IMPORT_MODULES:
                    continue
                if self._import_library(root) is not None:
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
                        f"'{alias.name}' is not part of the controllerpy API.",
                        hint="Known names:",
                        hint_lines=sorted(API_FUNCTIONS) + sorted(supported_libraries()),
                    )
            return

        if root == module and self._import_library(root) is not None:
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
            hint_lines=[f"from controllerpy import {lib}" for lib in sorted(supported_libraries())]
            + ["from controllerpy import *  (IDE/type-checker support only)"],
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
        check_reserved_variable(self.ctx.error, node, name)

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
        return resolve_annotation(node, self.ctx.classes, self.ctx.external_types, self.ctx.error)

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
        hint = "A controllerpy program defines both entry points:"
        if self.ctx.setup_node is None:
            raise ControllerPyError(
                "Missing required function: main()", filename=self.ctx.filename, hint=hint, hint_lines=hint_lines
            )
        if self.ctx.loop_node is None:
            raise ControllerPyError(
                "Missing required function: loop()", filename=self.ctx.filename, hint=hint, hint_lines=hint_lines
            )

    def _var_error(self, var: VarInfo, message: str, *, hint: Optional[str] = None) -> None:
        raise ControllerPyError(
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
            for method in cls.all_methods():
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
            for method in cls.all_methods():
                label = f"{cls.name}()" if method.is_constructor else f"{cls.name}.{method.name}()"
                method.return_type = self._resolve_return_type(
                    label, method.observed_returns, method.annotated_return, method.node
                )
