"""Model preparation: the order classes have to be emitted in.

C++ needs a class to be defined before another class can hold it by value, so
the generator has to know the dependency order of the classes stage 2 collected
*before* it writes anything.  That is the only part of stage 3 that transforms
its input instead of printing it, and the only part that can fail on a
well-validated program: a dependency cycle is reported here, with the chain
that causes it.
"""

from __future__ import annotations

import ast
from typing import List, Set

from ..validator import ClassInfo, CompileContext

__all__ = ["order_classes"]


def order_classes(context: CompileContext) -> List[ClassInfo]:
    """Every class, dependencies first, recording each class' dependencies."""

    ordered: List[ClassInfo] = []
    visiting: List[str] = []
    done: Set[str] = set()

    def visit(name: str) -> None:
        if name in done:
            return
        if name in visiting:
            chain = " -> ".join(visiting[visiting.index(name) :] + [name])
            context.error(
                context.classes[name].node,
                f"Circular dependency between classes: {chain}",
                hint="C++ classes cannot contain each other by value; restructure your classes.",
            )
        visiting.append(name)
        cls = context.classes[name]
        cls.depends_on = _class_dependencies(context, cls)
        for dependency in sorted(cls.depends_on):
            visit(dependency)
        visiting.pop()
        done.add(name)
        ordered.append(cls)

    for class_name in context.classes:
        visit(class_name)

    return ordered


def _class_dependencies(context: CompileContext, cls: ClassInfo) -> Set[str]:
    """Names of other classes that appear anywhere inside *cls*."""

    dependencies: Set[str] = set()
    for field in cls.fields.values():
        if field.cpp_type in context.classes and field.cpp_type != cls.name:
            dependencies.add(field.cpp_type)
    for method in cls.all_methods():
        if method.node is None:
            continue
        for node in ast.walk(method.node):
            if isinstance(node, ast.Name) and node.id in context.classes and node.id != cls.name:
                dependencies.add(node.id)

    return dependencies
