"""Stage 2: the validator decides what is part of the supported subset."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import get_type_hints

import pytest

import micropy.compiler.validator as validator
from micropy.compiler.validator.types import SCALAR_TYPES

SHELL = "\ndef main():\n    pass\n\ndef loop():\n    pass\n"


# entry
def test_missing_main_is_reported(error):
    exc = error("def loop():\n    pass\n", message="Missing required function: main()")
    assert exc.line is None
    assert exc.filename == "main.py"
    assert "def main()" in "\n".join(exc.hint_lines)


def test_missing_loop_is_reported(error):
    error("def main():\n    pass\n", message="Missing required function: loop()")


def test_duplicate_main_is_reported(error):
    error(
        """
        def main():
            pass

        def main():
            pass

        def loop():
            pass
        """,
        message="Function 'main' is defined more than once.",
        line=4,
        col=1,
    )


def test_duplicate_loop_is_reported(error):
    error(
        "def main():\n    pass\n\ndef loop():\n    pass\n\ndef loop():\n    pass\n",
        message="Function 'loop' is defined more than once.",
    )


def test_main_must_not_take_parameters(error):
    error("def main(value):\n    pass\n\ndef loop():\n    pass\n", message="main() must not take any parameters.")


def test_main_must_not_return_a_value(error):
    error(
        "def main():\n    return 1\n\ndef loop():\n    pass\n",
        message="main() must not return a value.",
    )


def test_loop_must_not_be_annotated_to_return(error):
    error("def main():\n    pass\n\ndef loop() -> int:\n    pass\n", message="loop() must not return a value.")


def test_bare_return_inside_loop_is_allowed(program):
    cpp = program("def main():\n    pass\n\ndef loop():\n    return\n")
    assert "    return;" in cpp


def test_main_and_loop_are_not_user_functions(result):
    compiled = result(SHELL)
    assert compiled.context.functions == {}
    assert compiled.context.setup_node is not None
    assert compiled.context.loop_node is not None


# ----------------------------------------------------------------- functions
def test_unknown_function_lists_the_supported_ones(error):
    error(
        "def main():\n    foo(1)\n\ndef loop():\n    pass\n",
        message="Unknown ArduinoPy function: foo()",
        hint="digital_write()",
        line=2,
        col=5,
    )


def test_arity_is_checked_for_arduino_functions(error):
    error(
        "def main():\n    digital_write(13)\n\ndef loop():\n    pass\n",
        message="digital_write() takes exactly 2 arguments but 1 was given.",
        line=2,
        col=5,
    )


def test_arity_is_checked_for_pulse_in(error):
    error(
        "def main():\n    pulseIn(7)\n\ndef loop():\n    pass\n",
        message="pulseIn() takes 2 to 3 arguments but 1 was given.",
        line=2,
        col=5,
    )
    error(
        "def main():\n    pulseIn(7, HIGH, 500, 1)\n\ndef loop():\n    pass\n",
        message="pulseIn() takes 2 to 3 arguments but 4 were given.",
        line=2,
        col=5,
    )


def test_pulse_in_cannot_be_redefined(error):
    error(
        "def pulseIn(pin):\n    pass\n\ndef main():\n    pass\n\ndef loop():\n    pass\n",
        message="'pulseIn' is an ArduinoPy function and cannot be redefined.",
    )


def test_arity_is_checked_for_tone_and_no_tone(error):
    error(
        "def main():\n    tone(8)\n\ndef loop():\n    pass\n",
        message="tone() takes 2 to 3 arguments but 1 was given.",
        line=2,
        col=5,
    )
    error(
        "def main():\n    tone(8, 1000, 500, 1)\n\ndef loop():\n    pass\n",
        message="tone() takes 2 to 3 arguments but 4 were given.",
        line=2,
        col=5,
    )
    error(
        "def main():\n    noTone()\n\ndef loop():\n    pass\n",
        message="noTone() takes exactly 1 argument but 0 were given.",
        line=2,
        col=5,
    )
    error(
        "def main():\n    noTone(8, 9)\n\ndef loop():\n    pass\n",
        message="noTone() takes exactly 1 argument but 2 were given.",
        line=2,
        col=5,
    )


def test_tone_names_cannot_be_redefined(error):
    error(
        "def tone(pin, frequency):\n    pass\n\ndef main():\n    pass\n\ndef loop():\n    pass\n",
        message="'tone' is an ArduinoPy function and cannot be redefined.",
    )
    error(
        "def noTone(pin):\n    pass\n\ndef main():\n    pass\n\ndef loop():\n    pass\n",
        message="'noTone' is an ArduinoPy function and cannot be redefined.",
    )


def test_arity_is_checked_for_user_functions(error):
    error(
        """
        def blink(pin, ms):
            digital_write(pin, HIGH)

        def main():
            blink(13)

        def loop():
            pass
        """,
        message="blink() takes exactly 2 arguments but 1 was given.",
    )


def test_duplicate_function_is_reported(error):
    error(
        """
        def helper():
            pass

        def helper():
            pass

        def main():
            pass

        def loop():
            pass
        """,
        message="Function 'helper' is defined more than once.",
    )


def test_arduino_names_cannot_be_redefined(error):
    error(
        "def delay(ms):\n    pass\n\ndef main():\n    pass\n\ndef loop():\n    pass\n",
        message="'delay' is an ArduinoPy function and cannot be redefined.",
    )
    error(
        "def main():\n    pass\n\ndef loop():\n    pass\n\nHIGH = 1\n",
        message="'HIGH' is an Arduino name and cannot be redefined.",
    )


def test_default_parameter_values_are_rejected(error):
    error(
        "def blink(pin, ms=100):\n    pass\n\ndef main():\n    pass\n\ndef loop():\n    pass\n",
        message="Unsupported Python feature: default parameter values",
    )


@pytest.mark.parametrize(
    "signature",
    ["def f(*args):", "def f(**kwargs):", "def f(a, *, b):", "def f(a, /, b):"],
)
def test_exotic_parameter_lists_are_rejected(error, signature):
    error(f"{signature}\n    pass\n\ndef main():\n    pass\n\ndef loop():\n    pass\n", message="Unsupported Python feature")


def test_duplicate_parameter_is_rejected(error):
    error(
        "def f(a, a):\n    pass\n\ndef main():\n    pass\n\ndef loop():\n    pass\n",
        message="Duplicate parameter name: 'a'",
    )


# ------------------------------------------------------- unsupported syntax
@pytest.mark.parametrize(
    "source, expected",
    [
        ("async def foo():\n    pass\n\n" + SHELL, "async function"),
        ("def f():\n    return lambda x: x\n\n" + SHELL, "lambda expression"),
        ("def f():\n    with open('x') as handle:\n        pass\n\n" + SHELL, "with statement"),
        ("def f():\n    try:\n        pass\n    except Exception:\n        pass\n\n" + SHELL, "try/except"),
        ("def f():\n    raise ValueError('x')\n\n" + SHELL, "raise statement"),
        ("def f():\n    assert True\n\n" + SHELL, "assert statement"),
        ("counter = 0\n\ndef f():\n    global counter\n\n" + SHELL, "global statement"),
        ("def f():\n    values = [x for x in range(3)]\n\n" + SHELL, "list comprehension"),
        ("def f():\n    values = {1: 2}\n\n" + SHELL, "dict literal"),
        ("def f():\n    values = {1, 2}\n\n" + SHELL, "set literal"),
        ("def f():\n    yield 1\n\n" + SHELL, "yield expression"),
        ("def f():\n    serial_println(f'x={1}')\n\n" + SHELL, "f-string"),
        ("def f():\n    if (value := 3) > 1:\n        pass\n\n" + SHELL, "walrus operator"),
        ("def f():\n    data = b'abc'\n\n" + SHELL, "bytes literal"),
        ("def f():\n    if 3 in [1, 2]:\n        pass\n\n" + SHELL, "the 'in' operator"),
        ("def f():\n    if 3 is 3:\n        pass\n\n" + SHELL, "'is' comparison"),
        ("def f():\n    del x\n\n" + SHELL, "del statement"),
        ("values = [1, 2]\n\ndef f():\n    part = values[0:1]\n\ndef main():\n    pass\n\ndef loop():\n    pass\n", "slice"),
    ],
)
def test_unsupported_python_features_are_rejected(error, source, expected):
    error(source, message=f"Unsupported Python feature: {expected}")


def test_nested_function_is_rejected(error):
    error(
        "def outer():\n    def inner():\n        pass\n\n" + SHELL,
        message="Unsupported Python feature: nested function",
    )


def test_top_level_statement_is_rejected(error):
    error(
        "pin_mode(13, OUTPUT)\n" + SHELL,
        message="Top-level statements are not supported.",
        line=1,
        col=1,
    )


def test_top_level_augmented_assignment_is_rejected(error):
    error(
        "counter = 0\ncounter += 1\n" + SHELL,
        message="Top-level augmented assignment is not supported.",
    )


def test_keyword_arguments_are_rejected(error):
    error(
        "def main():\n    pin_mode(13, mode=OUTPUT)\n\ndef loop():\n    pass\n",
        message="Unsupported Python feature: keyword arguments",
        line=2,
        col=5,
    )


def test_starred_arguments_are_rejected(error):
    error(
        "def main():\n    digital_write(*pins)\n\ndef loop():\n    pass\n",
        message="Unsupported Python feature: starred arguments",
    )


def test_none_is_rejected(error):
    error(
        "def main():\n    value = None\n\ndef loop():\n    pass\n",
        message="Unsupported Python feature: None",
    )


def test_import_inside_a_function_is_rejected(error):
    error(
        "def main():\n    import time\n\ndef loop():\n    pass\n",
        message="Unsupported Python feature: import inside a function",
    )


def test_relative_import_is_rejected(error):
    error(
        "from .helpers import thing\n" + SHELL, message="Unsupported Python feature: relative import"
    )


# ------------------------------------------------------------------- imports
def test_python_library_is_rejected_with_a_clear_message(error):
    error(
        "import requests\n" + SHELL,
        message="Python library 'requests' is not supported on Arduino.",
        hint="from micropy import",
        line=1,
        col=1,
    )


def test_from_import_of_a_python_library_is_rejected(error):
    error("from numpy import array\n" + SHELL, message="Python library 'numpy' is not supported on Arduino.")


def test_known_arduino_library_import_is_accepted(result):
    compiled = result("from micropy import Servo\n" + SHELL)
    assert "Servo.h" in compiled.context.includes
    assert compiled.context.external_types["Servo"] == "Servo"


def test_api_star_import_is_accepted_for_ide_support(result):
    compiled = result("from micropy import *\nimport micropy\n" + SHELL)
    assert compiled.context.includes == []


def test_unknown_name_from_api_import_is_rejected(error):
    error(
        "from micropy import teleport\n" + SHELL,
        message="'teleport' is not part of the micropy API.",
    )


def test_ide_only_module_imports_are_skipped(result):
    compiled = result(
        "import builtins\nfrom builtins import *\nimport micropy_api\nfrom micropy_api import *\n" + SHELL
    )
    assert compiled.context.includes == []


def test_named_import_from_the_api_stub_is_accepted(result):
    compiled = result("from micropy_api import HIGH, pin_mode\n" + SHELL)
    assert compiled.context.includes == []


# ------------------------------------------------------------------- classes
CLASS_SHELL = """
class Led:
    def __init__(self, pin):
        self.pin = pin

    def on(self):
        digital_write(self.pin, HIGH)
{extra}
def main():
    pass

def loop():
    pass
"""


def test_class_with_constructor_and_method_compiles(result):
    compiled = result(CLASS_SHELL.format(extra=""))
    assert list(compiled.context.classes) == ["Led"]
    assert list(compiled.context.classes["Led"].fields) == ["pin"]
    assert list(compiled.context.classes["Led"].methods) == ["on"]


def test_class_inheritance_is_rejected(error):
    error(
        """
        class Base:
            def __init__(self):
                pass

        class Child(Base):
            def __init__(self):
                pass

        def main():
            pass

        def loop():
            pass
        """,
        message="Unsupported Python feature: class inheritance",
    )


def test_class_attributes_are_rejected(error):
    error(
        CLASS_SHELL.format(extra="") .replace("    def on(self):", "    shared = 1\n\n    def on(self):"),
        message="Class attributes are not supported.",
    )


def test_method_without_self_is_rejected(error):
    error(
        CLASS_SHELL.format(extra="").replace("def on(self):", "def on():"),
        message="Method 'on' must take 'self' as its first parameter.",
    )


def test_special_methods_other_than_init_are_rejected(error):
    error(
        CLASS_SHELL.format(extra="").replace("    def on(self):", "    def __del__(self):"),
        message="Unsupported Python feature: special method '__del__'",
    )


def test_decorators_are_rejected(error):
    error(
        CLASS_SHELL.format(extra="").replace("    def on(self):", "    @staticmethod\n    def on(self):"),
        message="Unsupported Python feature: decorator",
    )


def test_unknown_attribute_is_rejected(error):
    error(
        CLASS_SHELL.format(extra="").replace("digital_write(self.pin, HIGH)", "digital_write(self.missing, HIGH)"),
        message="Class 'Led' has no attribute 'missing'.",
    )


def test_unknown_method_is_rejected(error):
    error(
        """
        class Led:
            def __init__(self, pin):
                self.pin = pin

        def main():
            led = Led(13)
            led.blink()

        def loop():
            pass
        """,
        message="Class 'Led' has no method 'blink'.",
    )


def test_wrong_number_of_constructor_arguments_is_rejected(error):
    error(
        """
        class Led:
            def __init__(self, pin):
                self.pin = pin

        def main():
            led = Led(13, 7)

        def loop():
            pass
        """,
        message="Led() takes exactly 1 argument but 2 were given.",
    )


def test_self_outside_a_class_is_rejected(error):
    error(
        "def main():\n    self.pin = 1\n\ndef loop():\n    pass\n",
        message="'self' can only be used inside a class method.",
    )


def test_attribute_and_method_sharing_a_name_is_rejected(error):
    error(
        """
        class Led:
            def __init__(self, pin):
                self.pin = pin
                self.on = 3

            def on(self):
                digital_write(self.pin, HIGH)

        def main():
            pass

        def loop():
            pass
        """,
        message="'on' is used as an attribute and as a method of class 'Led'.",
    )


def test_class_and_function_with_the_same_name_is_rejected(error):
    error(
        """
        class Led:
            def __init__(self):
                pass

        def Led():
            pass

        def main():
            pass

        def loop():
            pass
        """,
        message="Function 'Led' is defined more than once.",
    )


# ---------------------------------------------------------------------- loops
def test_range_without_arguments_is_rejected(error):
    error(
        "def main():\n    pass\n\ndef loop():\n    for i in range():\n        pass\n",
        message="range() takes 1 to 3 arguments but got 0.",
    )


def test_range_with_four_arguments_is_rejected(error):
    error(
        "def main():\n    pass\n\ndef loop():\n    for i in range(0, 10, 2, 1):\n        pass\n",
        message="range() takes 1 to 3 arguments but got 4.",
    )


def test_range_with_zero_step_is_rejected(error):
    error(
        "def main():\n    pass\n\ndef loop():\n    for i in range(0, 10, 0):\n        pass\n",
        message="range() step cannot be zero.",
    )


def test_range_with_dynamic_step_is_rejected(error):
    error(
        "def main():\n    pass\n\ndef loop():\n    step = 2\n    for i in range(0, 10, step):\n        pass\n",
        message="The step argument of range() must be a constant integer.",
        hint="while loop",
    )


def test_range_with_float_arguments_is_rejected(error):
    error(
        "def main():\n    pass\n\ndef loop():\n    for i in range(2.5):\n        pass\n",
        message="range() arguments must be integers.",
    )


def test_range_with_keyword_arguments_is_rejected(error):
    error(
        "def main():\n    pass\n\ndef loop():\n    for i in range(0, stop=10):\n        pass\n",
        message="range() does not accept keyword arguments.",
    )


def test_for_over_something_else_than_range_is_rejected(error):
    error(
        "def main():\n    pass\n\ndef loop():\n    for value in [1, 2]:\n        pass\n",
        message="Only 'for <name> in range(...)' loops are supported.",
        hint="while loop",
    )


def test_for_else_is_rejected(error):
    error(
        "def main():\n    pass\n\ndef loop():\n    for i in range(3):\n        pass\n    else:\n        pass\n",
        message="Unsupported Python feature: for/else",
    )


def test_while_else_is_rejected(error):
    error(
        "def main():\n    pass\n\ndef loop():\n    while True:\n        pass\n    else:\n        pass\n",
        message="Unsupported Python feature: while/else",
    )


def test_loop_variable_hiding_a_parameter_is_rejected(error):
    error(
        """
        def count(n):
            for n in range(3):
                pass

        def main():
            pass

        def loop():
            pass
        """,
        message="Loop variable 'n' hides the parameter 'n'.",
    )


def test_loop_variable_hiding_a_global_is_rejected(error):
    error(
        "COUNT = 3\n\ndef main():\n    pass\n\ndef loop():\n    for COUNT in range(3):\n        pass\n",
        message="Loop variable 'COUNT' hides the global variable 'COUNT'.",
    )


def test_range_can_use_a_runtime_bound(result):
    compiled = result("def f(n):\n    for i in range(n):\n        pass\n" + SHELL)
    assert "for (int i = 0; i < n; i++)" in compiled.cpp


def test_break_and_continue_are_accepted(program):
    cpp = program(
        """
        def main():
            pass

        def loop():
            for i in range(10):
                if i == 3:
                    continue
                if i == 5:
                    break
        """
    )
    assert "continue;" in cpp
    assert "break;" in cpp


# ------------------------------------------------------------------ variables
def test_unknown_name_is_rejected(error):
    error(
        "def main():\n    value = missing + 1\n\ndef loop():\n    pass\n",
        message="Unknown name: 'missing'",
        line=2,
        col=13,
    )


def test_python_builtins_are_rejected_with_a_hint(error):
    error(
        "def main():\n    print('hi')\n\ndef loop():\n    pass\n",
        message="Python builtin 'print' is not available on Arduino.",
        hint="serial_println()",
        line=2,
        col=5,
    )


def test_incompatible_variable_types_are_rejected(error):
    error(
        "def main():\n    value = 1\n    value = 'text'\n\ndef loop():\n    pass\n",
        message="'value' is assigned values of incompatible types.",
    )


def test_int_and_float_are_promoted_not_rejected(result):
    compiled = result("def main():\n    value = 1\n    value = 1.5\n\ndef loop():\n    pass\n")
    assert "float value = 1;" in compiled.cpp


def test_arduino_api_return_types_are_known_to_the_type_system():
    """Every registered return type must be one the inference lattice can merge.

    A type such as ``long`` is understood by C++ but not by micropy's type
    system, so the result could never be assigned to an existing int or float
    variable.
    """
    known = set(SCALAR_TYPES) | {validator.VOID_TYPE}
    for name, function in validator.API_FUNCTIONS.items():
        assert function.returns in known, f"{name}() is typed {function.returns}"


def test_pulse_in_returns_int():
    assert validator.API_FUNCTIONS["pulseIn"].returns == "int"


def test_pulse_in_result_is_an_int(result):
    compiled = result("def main():\n    duration = pulseIn(7, HIGH)\n\ndef loop():\n    pass\n")
    assert "int duration = pulseIn(7, HIGH);" in compiled.cpp


def test_pulse_in_result_promotes_a_float_variable_to_float(result):
    """Regression: pulseIn() is an int-valued call, so float stays float."""
    compiled = result("timing = 0.0\n\ndef main():\n    pass\n\ndef loop():\n    timing = pulseIn(7, HIGH)\n")
    assert "float timing = 0.0;" in compiled.cpp


def test_pulse_in_result_still_rejects_a_genuinely_incompatible_scope_assignment(error):
    error(
        "timing = 0.0\n\ndef main():\n    pass\n\ndef loop():\n    timing = 'text'\n",
        message="'timing' is assigned values of incompatible types.",
    )


def test_string_arithmetic_is_rejected(error):
    error(
        "def main():\n    text = 'a' + 'b'\n\ndef loop():\n    pass\n",
        message="String arithmetic is not supported.",
        hint="serial_println()",
    )


def test_bitwise_operators_need_integers(error):
    error(
        "def main():\n    value = 1.5\n    mask = value & 3\n\ndef loop():\n    pass\n",
        message="Bitwise and shift operators need integer values",
    )


def test_ordered_string_comparison_is_rejected(error):
    error(
        "def main():\n    if 'a' < 'b':\n        pass\n\ndef loop():\n    pass\n",
        message="Ordered comparison of strings is not supported.",
    )


def test_chained_comparison_with_calls_is_rejected(error):
    error(
        "def main():\n    pass\n\ndef loop():\n    if 0 < digital_read(2) < 10:\n        pass\n",
        message="Chained comparisons cannot contain function calls.",
    )


def test_integer_literal_too_large_is_rejected(error):
    error(
        "def main():\n    big = 3000000000\n\ndef loop():\n    pass\n",
        message="does not fit into an Arduino int",
    )


def test_augmented_assignment_on_a_string_is_rejected(error):
    error(
        "def main():\n    text = 'a'\n    text += 'b'\n\ndef loop():\n    pass\n",
        message="Cannot use += on a string.",
    )


def test_unsupported_augmented_assignment_is_rejected(error):
    error(
        "def main():\n    value = 2\n    value @= 2\n\ndef loop():\n    pass\n",
        message="Unsupported augmented assignment: MatMult",
    )


# ---------------------------------------------------------------- annotations
def test_unknown_annotation_is_rejected(error):
    error(
        "def main():\n    value: dict = 1\n\ndef loop():\n    pass\n",
        message="Unsupported type annotation: 'dict'",
        line=2,
        col=12,
    )


def test_annotation_on_return_value_conflict_is_rejected(error):
    error(
        "def value() -> int:\n    return 1.5\n\ndef main():\n    pass\n\ndef loop():\n    pass\n",
        message="'value()' is annotated to return int but returns float.",
    )


def test_mixing_bare_and_valued_return_is_rejected(error):
    error(
        """
        def check(value):
            if value > 0:
                return value
            return

        def main():
            pass

        def loop():
            pass
        """,
        message="'check()' mixes 'return' with and without a value.",
    )


def test_conflicting_return_types_are_rejected(error):
    error(
        """
        def pick(value):
            if value > 0:
                return 1
            return 'text'

        def main():
            pass

        def loop():
            pass
        """,
        message="'pick()' returns values of incompatible types.",
    )


# ---------------------------------------------------------------------- lists
def test_arrays_are_created_from_list_literals(result):
    compiled = result("values = [1, 2, 3]\n" + SHELL)
    assert "const int values[3] = {1, 2, 3};" in compiled.cpp


def test_array_cannot_be_used_as_a_value(error):
    error(
        "values = [1, 2, 3]\n\ndef main():\n    total = values\n\ndef loop():\n    pass\n",
        message="Array 'values' cannot be used as a value.",
        hint="Index it",
    )


def test_array_cannot_be_reassigned(error):
    error(
        "def main():\n    values = [1, 2]\n    values = [3, 4]\n\ndef loop():\n    pass\n",
        message="Array 'values' must get its values where it is declared.",
    )


def test_array_literal_inside_a_block_is_rejected(error):
    error(
        "def main():\n    if True:\n        values = [1, 2]\n\ndef loop():\n    pass\n",
        message="Array 'values' must get its values where it is declared.",
        hint="top of the function",
    )


def test_empty_list_is_rejected(error):
    error(
        "def main():\n    values = []\n\ndef loop():\n    pass\n",
        message="Empty lists are not supported.",
    )


def test_mixed_list_types_are_rejected(error):
    error(
        "def main():\n    values = [1, 'two']\n\ndef loop():\n    pass\n",
        message="All elements of a list must have the same type.",
    )


def test_nested_lists_are_rejected(error):
    error(
        "def main():\n    values = [[1], [2]]\n\ndef loop():\n    pass\n",
        message="Nested lists are not supported on Arduino.",
    )


def test_list_literal_outside_an_assignment_is_rejected(error):
    error(
        "def main():\n    serial_println([1, 2])\n\ndef loop():\n    pass\n",
        message="List literals can only be assigned to a variable.",
    )


def test_indexing_a_non_array_is_rejected(error):
    error(
        "def main():\n    value = 1\n    first = value[0]\n\ndef loop():\n    pass\n",
        message="'value' is not an array, so it cannot be indexed.",
    )


def test_len_of_a_non_array_is_rejected(error):
    error(
        "def main():\n    value = 1\n    size = len(value)\n\ndef loop():\n    pass\n",
        message="len() is only supported for arrays created from a list literal.",
    )


def test_index_must_be_an_integer(error):
    error(
        "values = [1, 2]\n\ndef main():\n    first = values[1.5]\n\ndef loop():\n    pass\n",
        message="Array indices must be integers.",
    )


def test_unpacking_a_mismatched_tuple_is_rejected(error):
    error(
        "def main():\n    a, b = 1, 2, 3\n\ndef loop():\n    pass\n",
        message="Cannot unpack: the number of names and values does not match.",
    )


# -------------------------------------------------------------------- globals
def test_global_function_call_initializer_is_rejected(error):
    error(
        "value = digital_read(2)\n" + SHELL,
        message="Global variables cannot call this function during initialization.",
        hint="assign the value inside main()",
    )


def test_math_helpers_are_allowed_in_global_initializers(result):
    compiled = result("ROOT = sqrt(16)\n" + SHELL)
    assert "const float ROOT = sqrt(16);" in compiled.cpp


def test_attribute_assignment_on_a_non_object_is_rejected(error):
    error(
        "def main():\n    value = 1\n    value.pin = 3\n\ndef loop():\n    pass\n",
        message="Cannot assign to attribute 'pin' of this value.",
    )


def test_object_created_inside_a_block_is_rejected(error):
    error(
        """
        class Led:
            def __init__(self, pin):
                self.pin = pin

        def main():
            if True:
                led = Led(13)

        def loop():
            pass
        """,
        message="Object 'led' has to be created directly in the function body.",
        hint="default constructor",
    )


def test_class_typed_global_is_a_known_type(result):
    compiled = result(
        """
        class Led:
            def __init__(self, pin):
                self.pin = pin

        led = Led(13)

        def main():
            pass

        def loop():
            pass
        """
    )
    assert compiled.context.globals["led"].cpp_type == "Led"


# ----------------------------------------------------------------- layering
#: The modules that describe the target.  :mod:`context` imports both of
#: them, so anything they import back closes a cycle in the module graph.
TARGET_DESCRIPTION_MODULES = ("naming", "types")


def _imported_siblings(path: Path) -> set:
    """The sibling modules *path* imports, TYPE_CHECKING blocks included."""

    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            found.add(node.module)
    return found


@pytest.mark.parametrize("module", TARGET_DESCRIPTION_MODULES)
def test_target_modules_do_not_depend_on_the_context(module):
    package = Path(validator.__file__).parent

    assert "context" not in _imported_siblings(package / f"{module}.py")


#: The one function of each module that has to report a problem.
REPORTING_FUNCTIONS = {"naming": "check_reserved_variable", "types": "resolve_annotation"}


@pytest.mark.parametrize("module", sorted(REPORTING_FUNCTIONS))
def test_target_modules_report_through_the_reporter_not_the_context(module):

    imported = importlib.import_module(f"micropy.compiler.validator.{module}")
    function = getattr(imported, REPORTING_FUNCTIONS[module])
    annotations = {getattr(hint, "__name__", str(hint)) for hint in get_type_hints(function).values()}

    assert "ErrorReporter" in annotations
    assert "CompileContext" not in annotations
