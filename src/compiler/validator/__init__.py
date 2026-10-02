"""Stage 2 of the compiler: Python -> validated, typed Arduino C++.

Stage 2 is the only stage that knows what controllerpy is: it decides which Python
constructs are part of the supported subset and works out the C++ type of every
name.  It is split so each module has one job:

- :mod:`api`, :mod:`types`, :mod:`naming`, :mod:`libraries`: the tables that
  describe the target - the Arduino API, the type system, the C++ naming rules
  and the importable libraries.
- :mod:`symbols`: the records the symbol tables are made of.
- :mod:`context`: :class:`CompileContext`, the state stage 3 reads.
- :mod:`ast_utils`: pure AST helpers and the unsupported-feature policy.
- :mod:`collector` and :mod:`analyzer`: the two phases - the first collects
  definitions and finalises types, the second analyses bodies.

Nothing below depends on the generator, and the modules build on each other in
that order, so the package has no cycles.  The first group stays a leaf of the
package: it reports a problem through the :class:`~controllerpy.errors.ErrorReporter`
it is handed (``CompileContext.error``), and :mod:`types` is told which class
names exist instead of being given the context to read them from.
"""

from .analyzer import BodyAnalyzer
from .api import (
    API_FUNCTIONS,
    ARDUINO_CONSTANTS,
    ARDUINO_OBJECTS,
    BUILTIN_FUNCTIONS,
    PYTHON_BUILTIN_HINTS,
    STRING_METHODS,
    ApiFunction,
)
from .ast_utils import UNSUPPORTED_FEATURES
from .collector import Validator
from .context import CompileContext
from .libraries import API_IMPORT_MODULES, LIBRARIES, ApiClass, ApiMethod, Library
from .symbols import ClassInfo, FunctionInfo, MethodInfo, Scope, VarInfo
from .types import CONFLICT_TYPE, DEFAULT_TYPE, UNKNOWN_TYPE, VOID_TYPE

__all__ = [
    "API_FUNCTIONS",
    "API_IMPORT_MODULES",
    "ARDUINO_CONSTANTS",
    "ARDUINO_OBJECTS",
    "BUILTIN_FUNCTIONS",
    "CONFLICT_TYPE",
    "DEFAULT_TYPE",
    "LIBRARIES",
    "PYTHON_BUILTIN_HINTS",
    "STRING_METHODS",
    "UNSUPPORTED_FEATURES",
    "UNKNOWN_TYPE",
    "VOID_TYPE",
    "ApiClass",
    "ApiFunction",
    "ApiMethod",
    "BodyAnalyzer",
    "ClassInfo",
    "CompileContext",
    "FunctionInfo",
    "Library",
    "MethodInfo",
    "Scope",
    "VarInfo",
    "Validator",
]
