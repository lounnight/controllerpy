"""Stage 3: the C++ backend.

Turns a validated, typed AST into the C++ of a single sketch.  The public
surface is deliberately small:

* :class:`CppGenerator` - run the whole stage on a :class:`CompileContext`.
* :class:`CodeWriter` - the indented-line buffer it writes into.
* :func:`cpp_string_literal` - how a Python string becomes a C++ literal.
"""

from .formatting import CodeWriter, cpp_string_literal
from .generator import CppGenerator

__all__ = ["CodeWriter", "CppGenerator", "cpp_string_literal"]
