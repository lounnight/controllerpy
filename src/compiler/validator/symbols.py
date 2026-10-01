"""The records that make up the symbol tables.

These are plain data holders: what is known about a variable, a function, a
method, a class and the lexical scope a name was found in.  Stage 2 fills them
in, stage 3 (the generator) reads them, and nothing here reaches back - types
come from :mod:`.types`, so the records stay independent of the context.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .types import CONFLICT_TYPE, DEFAULT_TYPE, UNKNOWN_TYPE, merge_types

__all__ = ["ClassInfo", "FunctionInfo", "MethodInfo", "Scope", "VarInfo"]


@dataclass
class VarInfo:
    name: str
    cpp_type: str = UNKNOWN_TYPE
    is_const: bool = False
    is_param: bool = False
    is_global: bool = False
    is_array: bool = False
    array_len: Optional[int] = None
    append_count: int = 0
    insert_count: int = 0
    pop_count: int = 0
    clear_growth: Optional[int] = None
    is_object: bool = False
    is_external: bool = False
    declare_node: Optional[ast.AST] = None
    value: Optional[ast.AST] = None
    write_count: int = 0
    observed_types: Set[str] = field(default_factory=set)
    lineno: Optional[int] = None
    col_offset: Optional[int] = None

    def record_type(self, cpp_type: Optional[str]) -> None:
        if cpp_type and cpp_type != UNKNOWN_TYPE:
            self.observed_types.add(cpp_type)

    def final_type(self) -> Optional[str]:
        result: Optional[str] = None
        for observed in sorted(self.observed_types):
            result = merge_types(result, observed)
            if result == CONFLICT_TYPE:
                return CONFLICT_TYPE
        
        return result

    def resolved_type(self) -> str:
        final = self.final_type()
        if not final or final == CONFLICT_TYPE:
            return self.cpp_type if self.cpp_type != UNKNOWN_TYPE else DEFAULT_TYPE
        
        return final

    @property
    def has_count(self) -> bool:
        return bool(self.append_count or self.insert_count or self.pop_count or self.clear_growth is not None)

    @property
    def guaranteed_count(self) -> int:
        growth = self.append_count + self.insert_count - self.pop_count
        if self.clear_growth is not None:
            return growth - self.clear_growth
        return (self.array_len or 0) + growth


@dataclass
class FunctionInfo:
    name: str
    params: List[VarInfo] = field(default_factory=list)
    return_type: str = UNKNOWN_TYPE
    annotated_return: Optional[str] = None
    observed_returns: List[Optional[str]] = field(default_factory=list)
    locals: Dict[str, VarInfo] = field(default_factory=dict)
    hoisted: List[str] = field(default_factory=list)
    lineno: Optional[int] = None
    col_offset: Optional[int] = None
    node: Optional[ast.FunctionDef] = None

    @property
    def arity_text(self) -> str:
        return f"{self.name}({', '.join(p.name for p in self.params)})"


@dataclass
class MethodInfo:
    name: str
    params: List[VarInfo] = field(default_factory=list)
    return_type: str = UNKNOWN_TYPE
    annotated_return: Optional[str] = None
    observed_returns: List[Optional[str]] = field(default_factory=list)
    locals: Dict[str, VarInfo] = field(default_factory=dict)
    hoisted: List[str] = field(default_factory=list)
    is_constructor: bool = False
    lineno: Optional[int] = None
    col_offset: Optional[int] = None
    node: Optional[ast.FunctionDef] = None


@dataclass
class ClassInfo:
    name: str
    fields: Dict[str, VarInfo] = field(default_factory=dict)
    methods: Dict[str, MethodInfo] = field(default_factory=dict)
    constructor: Optional[MethodInfo] = None
    is_struct: bool = False
    depends_on: Set[str] = field(default_factory=set)
    lineno: Optional[int] = None
    col_offset: Optional[int] = None
    node: Optional[ast.ClassDef] = None

    @property
    def field_names(self) -> List[str]:
        return list(self.fields)

    @property
    def method_names(self) -> List[str]:
        return [name for name in self.methods if not self.methods[name].is_constructor]

    def all_methods(self) -> List[MethodInfo]:
        """Every method of the class, the constructor first."""

        methods: List[MethodInfo] = []
        if self.constructor is not None:
            methods.append(self.constructor)
        methods.extend(self.methods.values())
        return methods


class Scope:
    def __init__(self, kind: str, owner: Optional[str] = None, parent: Optional["Scope"] = None) -> None:
        self.kind = kind
        self.owner = owner
        self.parent = parent
        self.variables: Dict[str, VarInfo] = {}

    def declare(self, var: VarInfo) -> VarInfo:
        self.variables[var.name] = var
        return var

    def local(self, name: str) -> Optional[VarInfo]:
        return self.variables.get(name)

    def has_local(self, name: str) -> bool:
        return name in self.variables

    def lookup(self, name: str) -> Optional[VarInfo]:
        scope: Optional[Scope] = self
        while scope is not None:
            found = scope.variables.get(name)
            if found is not None:
                return found
            scope = scope.parent
        return None
