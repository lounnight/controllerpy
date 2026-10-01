"""Stage 3: C++ generation for the supported subset."""

from __future__ import annotations

import ast

import pytest
from controllerpy.compiler.generator import CodeWriter, cpp_string_literal
from controllerpy.compiler.validator.libraries import (
    LIBRARIES,
    ApiClass,
    ApiMethod,
    Library,
)

SHELL = "\ndef main():\n    pass\n\ndef loop():\n    pass\n"


# ----------------------------------------------------------------- variables
def test_includes_and_entry_points(program):
    cpp = program(SHELL)
    assert not cpp.startswith("#include")
    assert "void setup() {\n}\n" in cpp
    assert "void loop() {\n}\n" in cpp


def test_main_becomes_setup_and_loop_stays_loop(program):
    cpp = program("def main():\n    pin_mode(13, OUTPUT)\n\ndef loop():\n    delay(1)\n")
    assert "void setup() {\n    pinMode(13, OUTPUT);\n}" in cpp
    assert "void loop() {\n    delay(1);\n}" in cpp
    assert "int main(" not in cpp


def test_global_constants_become_const_int(program):
    cpp = program("LED = 13\n" + SHELL)
    assert "const int LED = 13;" in cpp


def test_globals_are_typed_by_their_value(program):
    cpp = program(
        "counter = 0\nenabled = True\nname = 'hi'\nlabel: str = 'x'\ntemperature = 25.5\n" + SHELL
    )
    assert "const int counter = 0;" in cpp
    assert "const bool enabled = true;" in cpp
    assert "const char* name = \"hi\";" in cpp
    assert "String label = \"x\";" in cpp
    assert "const float temperature = 25.5;" in cpp


def test_global_that_is_written_inside_loop_is_not_const(program):
    cpp = program(
        """
        counter = 0

        def main():
            pass

        def loop():
            counter = counter + 1
            delay(counter)
        """
    )
    assert "int counter = 0;" in cpp
    assert "const int counter" not in cpp
    assert "counter = counter + 1;" in cpp


def test_annotated_global_without_value(program):
    cpp = program("value: int\n" + SHELL)
    assert "int value;" in cpp


def test_local_variables_are_declared_where_they_are_first_assigned(program):
    cpp = program("def main():\n    total = 0\n    total = total + 1\n\ndef loop():\n    pass\n")
    assert "    int total = 0;\n" in cpp
    assert "    total = total + 1;\n" in cpp
    assert cpp.count("int total") == 1


def test_local_first_assigned_inside_a_block_is_hoisted(program):
    cpp = program(
        """
        def main():
            if digital_read(2) == HIGH:
                total = 1
            digital_write(total, HIGH)

        def loop():
            pass
        """
    )
    assert "    int total;\n" in cpp
    assert "        total = 1;\n" in cpp
    assert "int total = 1" not in cpp


def test_parameters_and_return_types_are_inferred(program):
    cpp = program(
        """
        def add(a, b):
            return a + b

        def average(a, b):
            return (a + b) / 2.0

        def blink(pin):
            digital_write(pin, HIGH)

        def main():
            total = add(1, 2)
            average(1, 2)
            blink(13)

        def loop():
            pass
        """
    )
    assert "int add(int a, int b);" in cpp
    assert "float average(int a, int b);" in cpp
    assert "void blink(int pin);" in cpp
    assert "int add(int a, int b) {" in cpp
    assert "float average(int a, int b) {" in cpp
    assert "void blink(int pin) {" in cpp


def test_explicit_return_annotation_wins(program):
    cpp = program("def half(x) -> float:\n    return x / 2\n" + SHELL)
    assert "float half(int x) {" in cpp


def test_return_type_can_be_resolved_through_another_function(program):
    cpp = program(
        """
        def inner():
            return 1.5

        def outer():
            return inner()

        def main():
            value = outer()

        def loop():
            pass
        """
    )
    assert "float inner() {" in cpp
    assert "float outer() {" in cpp
    assert "float value = outer();" in cpp


def test_boolean_function_return_type(program):
    cpp = program("def ready():\n    return digital_read(2) == HIGH\n" + SHELL)
    assert "bool ready() {" in cpp


# ---------------------------------------------------------------- expressions
def test_operators_are_mapped_to_cpp(program):
    cpp = program(
        """
        def main():
            a = 1
            b = 2
            total = a + b
            diff = a - b
            product = a * b
            quotient = a / b
            whole = a // b
            rest = a % b
            high = a << 2
            low = a >> 1
            masked = a & b
            flipped = a ^ b
            merged = a | b

        def loop():
            pass
        """
    )
    assert "total = a + b;" in cpp
    assert "diff = a - b;" in cpp
    assert "product = a * b;" in cpp
    assert "quotient = a / b;" in cpp
    assert "whole = a / b;" in cpp
    assert "rest = a % b;" in cpp
    assert "high = a << 2;" in cpp
    assert "low = a >> 1;" in cpp
    assert "masked = a & b;" in cpp
    assert "flipped = a ^ b;" in cpp
    assert "merged = a | b;" in cpp


def test_boolean_operators_become_cpp_operators(program):
    cpp = program(
        """
        def main():
            x = 1
            y = 0
            if x and y:
                digital_write(13, HIGH)
            if x or not y:
                digital_write(13, LOW)

        def loop():
            pass
        """
    )
    assert "if (x && y) {" in cpp
    assert "if (x || !y) {" in cpp


def test_not_of_a_comparison_is_parenthesised(program):
    cpp = program("def main():\n    if not (1 < 2):\n        pass\n\ndef loop():\n    pass\n")
    assert "if (!(1 < 2)) {" in cpp


def test_parentheses_are_only_added_where_needed(program):
    cpp = program(
        """
        def main():
            a = 1
            b = 2
            c = 3
            value = a + b * c
            grouped = (a + b) * c
            nested = a - (b - c)

        def loop():
            pass
        """
    )
    assert "value = a + b * c;" in cpp
    assert "grouped = (a + b) * c;" in cpp
    assert "nested = a - (b - c);" in cpp


def test_parentheses_around_a_sub_expression_are_preserved(program):
    """Regression: the grouping the source wrote survives the translation."""
    cpp = program(
        """
        def main():
            a = 1
            b = 2
            c = 3
            timing = (10 / 1) / 5
            left = (a - b) - c
            divided = (a / b) * c
            remainder = (a % b) + c

        def loop():
            pass
        """
    )
    assert "timing = (10 / 1) / 5;" in cpp
    assert "left = (a - b) - c;" in cpp
    assert "divided = (a / b) * c;" in cpp
    assert "remainder = (a % b) + c;" in cpp


def test_parentheses_are_not_invented_where_the_source_had_none(program):
    cpp = program(
        """
        def main():
            a = 1
            b = 2
            c = 3
            flat = a + b * c
            chain = a - b - c
            mixed = a * b + c

        def loop():
            pass
        """
    )
    assert "flat = a + b * c;" in cpp
    assert "chain = a - b - c;" in cpp
    assert "mixed = a * b + c;" in cpp


def test_operators_of_every_precedence_keep_their_grouping(program):
    cpp = program(
        """
        def main():
            a = 1
            b = 2
            c = 3
            grouped_add = (a + b) * c
            grouped_sub = (a - b) * c
            grouped_mul = (a * b) + c
            grouped_div = (a / b) + c
            grouped_mod = (a % b) * c

        def loop():
            pass
        """
    )
    assert "grouped_add = (a + b) * c;" in cpp
    assert "grouped_sub = (a - b) * c;" in cpp
    assert "grouped_mul = (a * b) + c;" in cpp
    assert "grouped_div = (a / b) + c;" in cpp
    assert "grouped_mod = (a % b) * c;" in cpp


def test_nested_expressions_keep_every_level_of_grouping(program):
    cpp = program(
        """
        def main():
            a = 1
            b = 2
            c = 3
            deep = ((a + b) * (c - a)) - b
            shifted = (a + b) << c

        def loop():
            pass
        """
    )
    assert "deep = ((a + b) * (c - a)) - b;" in cpp
    assert "shifted = (a + b) << c;" in cpp


def test_grouping_split_across_lines_still_means_the_same(program):
    cpp = program(
        """
        def main():
            a = 1
            b = 2
            c = 3
            value = (
                a + b
            ) * c

        def loop():
            pass
        """
    )
    assert "value = (a + b) * c;" in cpp


def test_chained_unary_signs_are_not_glued_together(program):
    """Regression: ``- -a`` must not become the pre-decrement ``--a``."""
    cpp = program(
        """
        def main():
            a = 1
            negated = - -a
            doubled_sign = + +a

        def loop():
            pass
        """
    )
    assert "negated = -(-a);" in cpp
    assert "doubled_sign = +(+a);" in cpp
    assert "--a" not in cpp
    assert "++a" not in cpp


def test_nested_comparisons_keep_their_grouping(program):
    cpp = program(
        """
        def main():
            a = 1
            b = 2
            c = 3
            relational = a < (b < c)
            equality = a == (b == c)

        def loop():
            pass
        """
    )
    assert "relational = a < (b < c);" in cpp
    assert "equality = a == (b == c);" in cpp


def test_conditional_expressions_keep_their_grouping(program):
    cpp = program(
        """
        def main():
            a = 1
            b = 2
            c = 3
            value = a if (b if c else c) else b

        def loop():
            pass
        """
    )
    assert "value = (c ? b : c) ? a : b;" in cpp


GROUPED_EXPRESSIONS = [
    "(a + b) * (c - d)",
    "((a + b) - (c * d)) / a",
    "(a / (b + c)) % (d - a)",
    "((a << b) + (c >> d)) & (a | b)",
    "(a - (b - (c - d))) * (a + b)",
    "a + b * c - d",
    "(a * b) / (c % d)",
]


def test_generated_expressions_parse_to_the_same_tree(program):
    """Every emitted expression groups its operands like the Python source did."""

    body = "\n".join(f"    value_{index} = {expression}" for index, expression in enumerate(GROUPED_EXPRESSIONS))
    cpp = program("a = 1\nb = 2\nc = 3\nd = 4\n\ndef main():\n" + body + "\n\ndef loop():\n    pass\n")
    for index, expression in enumerate(GROUPED_EXPRESSIONS):
        emitted = next(
            line.split("=", 1)[1].strip().rstrip(";")
            for line in cpp.splitlines()
            if f" value_{index} = " in line
        )
        expected = ast.dump(ast.parse(expression, mode="eval").body)
        assert ast.dump(ast.parse(emitted, mode="eval").body) == expected, expression


def test_parentheses_are_preserved_in_every_value_position(program):
    cpp = program(
        """
        a = 1
        b = 2
        values = [1, 2, 3]

        def one(x):
            return (x + 1)

        def main():
            assigned = (a + b)
            summed = 0
            summed += (a + b)
            called = one((a + b))
            indexed = values[(a)]
            listed = [(a + b), 1]

        def loop():
            pass
        """
    )
    assert "int assigned = (a + b);" in cpp
    assert "summed += (a + b);" in cpp
    assert "int called = one((a + b));" in cpp
    assert "int indexed = values[(a)];" in cpp
    assert "int listed[2] = {(a + b), 1};" in cpp
    assert "return (x + 1);" in cpp


def test_call_arguments_do_not_gain_parentheses(program):
    """A call's own parentheses must not be mistaken for the argument's."""
    cpp = program(
        """
        def one(x):
            return x

        def three():
            return 3

        def main():
            value = one(1 + 2)
            other = one(three())

        def loop():
            pass
        """
    )
    assert "one(1 + 2)" in cpp
    assert "one(three())" in cpp
    assert "one((1 + 2))" not in cpp
    assert "one((three()))" not in cpp


def test_float_operators_use_the_math_helpers(program):
    cpp = program(
        """
        def main():
            whole = 7.5 // 2.0
            rest = 7.5 % 2.0
            power = 2 ** 3
            scaled = 2.0 ** 3

        def loop():
            pass
        """
    )
    assert "whole = floor(7.5 / 2.0);" in cpp
    assert "rest = fmod(7.5, 2.0);" in cpp
    assert "power = pow(2, 3);" in cpp
    assert "scaled = pow(2.0, 3);" in cpp


def test_comparisons_and_chained_comparisons(program):
    cpp = program(
        """
        def main():
            x = 5
            if x != 3 and x <= 10 and x >= 0:
                pass
            ok = 0 < x < 10

        def loop():
            pass
        """
    )
    assert "if (x != 3 && x <= 10 && x >= 0) {" in cpp
    assert "ok = 0 < x && x < 10;" in cpp


def test_conditional_expression_becomes_a_ternary(program):
    cpp = program("def main():\n    pick = 1 if digital_read(2) == HIGH else 2\n\ndef loop():\n    pass\n")
    assert "pick = digitalRead(2) == HIGH ? 1 : 2;" in cpp


def test_unary_minus_and_invert(program):
    cpp = program("def main():\n    a = -1\n    b = ~a\n\ndef loop():\n    pass\n")
    assert "a = -1;" in cpp
    assert "b = ~a;" in cpp


def test_string_literals_are_escaped(program):
    cpp = program('def main():\n    serial_println("say \\\"hi\\\"\\n")\n\ndef loop():\n    pass\n')
    assert 'Serial.println("say \\\"hi\\\"\\n");' in cpp


def test_cpp_string_literal_helper():
    assert cpp_string_literal("plain") == '"plain"'
    assert cpp_string_literal('a"b') == '"a\\"b"'
    assert cpp_string_literal("tab\tend") == '"tab\\tend"'
    assert cpp_string_literal("bell\x07") == '"bell\\007"'


# ----------------------------------------------------------------- statements
def test_if_elif_else_chain(program):
    cpp = program(
        """
        def main():
            value = 5
            if value > 80:
                digital_write(9, HIGH)
            elif value > 60:
                digital_write(10, HIGH)
            else:
                digital_write(11, LOW)

        def loop():
            pass
        """
    )
    assert (
        "    if (value > 80) {\n"
        "        digitalWrite(9, HIGH);\n"
        "    } else if (value > 60) {\n"
        "        digitalWrite(10, HIGH);\n"
        "    } else {\n"
        "        digitalWrite(11, LOW);\n"
        "    }" in cpp
    )


def test_nested_if_blocks(program):
    cpp = program(
        """
        def main():
            pass

        def loop():
            sensor = digital_read(2)
            temperature = analog_read(A0)
            if sensor:
                if temperature > 50:
                    digital_write(9, HIGH)
                else:
                    digital_write(10, HIGH)
            else:
                digital_write(11, LOW)
        """
    )
    assert cpp.count("if (sensor) {") == 1
    assert "        if (temperature > 50) {" in cpp
    assert "        } else {" in cpp


def test_while_loop_with_break_and_continue(program):
    cpp = program(
        """
        def main():
            pass

        def loop():
            while True:
                reading = digital_read(2)
                if reading == LOW:
                    continue
                break
        """
    )
    assert "while (true) {" in cpp
    assert "continue;" in cpp
    assert "break;" in cpp


def test_range_variants(program):
    cpp = program(
        """
        def main():
            for i in range(10):
                digital_write(i, HIGH)
            for j in range(2, 10):
                digital_write(j, HIGH)
            for k in range(0, 10, 2):
                digital_write(k, HIGH)
            for m in range(10, 0, -1):
                digital_write(m, HIGH)

        def loop():
            pass
        """
    )
    assert "for (int i = 0; i < 10; i++) {" in cpp
    assert "for (int j = 2; j < 10; j++) {" in cpp
    assert "for (int k = 0; k < 10; k += 2) {" in cpp
    assert "for (int m = 10; m > 0; m--) {" in cpp


def test_augmented_assignments(program):
    cpp = program(
        """
        counter = 0

        def main():
            counter = 1
            counter += 2
            counter -= 1
            counter *= 3
            counter //= 2
            counter %= 5
            counter &= 7
            counter |= 8
            counter ^= 1
            counter <<= 1
            counter >>= 1

        def loop():
            pass
        """
    )
    for operator in ("+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="):
        assert f"counter {operator} " in cpp


def test_multi_assignment_and_tuple_targets(program):
    cpp = program("def main():\n    a, b = 1, 2\n\ndef loop():\n    pass\n")
    assert "int a = 1;" in cpp
    assert "int b = 2;" in cpp


def test_tuple_value_can_feed_several_variables(program):
    cpp = program("def main():\n    a, b = 4, 5\n    c = a\n\ndef loop():\n    pass\n")
    assert "int a = 4;" in cpp
    assert "int b = 5;" in cpp
    assert "int c = a;" in cpp


def test_arrays_len_and_index_writes(program):
    cpp = program(
        """
        readings = [0, 0, 0]

        def main():
            size = len(readings)
            readings[1] = 42
            first = readings[0]

        def loop():
            pass
        """
    )
    assert "int readings[3] = {0, 0, 0};" in cpp
    assert "size = (sizeof(readings) / sizeof(readings[0]));" in cpp
    assert "readings[1] = 42;" in cpp
    assert "first = readings[0];" in cpp


def test_string_annotation_uses_the_arduino_string_class(program):
    cpp = program("def main():\n    label: str = 'hi'\n\ndef loop():\n    pass\n")
    assert 'String label = "hi";' in cpp


def test_pass_produces_an_empty_block(program):
    cpp = program("def main():\n    pass\n\ndef loop():\n    pass\n")
    assert "void setup() {\n}" in cpp
    assert "void loop() {\n}" in cpp


def test_docstrings_are_ignored(program):
    cpp = program(
        '''
        """Module docstring."""

        def helper():
            """Does nothing."""
            pass

        def main():
            pass

        def loop():
            pass
        '''
    )
    assert "docstring" not in cpp.lower()
    assert "void helper() {\n}" in cpp


def test_blank_lines_from_the_source_are_kept(program):
    cpp = program(
        """
        def main():
            digital_write(13, HIGH)

            delay(100)

        def loop():
            pass
        """
    )
    assert "    digitalWrite(13, HIGH);\n\n    delay(100);\n" in cpp


def test_cpp_keywords_are_escaped_in_identifiers(program):
    cpp = program("def main():\n    explicit = 1\n    class_name = explicit\n\ndef loop():\n    pass\n")
    assert "int explicit_ = 1;" in cpp
    assert "int class_name = explicit_;" in cpp


def test_arduino_names_are_escaped_when_used_as_variables(program):
    cpp = program("def main():\n    delay = 5\n    delay = delay + 1\n\ndef loop():\n    pass\n")
    assert "int delay_ = 5;" in cpp
    assert "delay_ = delay_ + 1;" in cpp


def test_arduino_core_names_cannot_be_used_as_variables(error):
    error(
        "def main():\n    Serial = 5\n\ndef loop():\n    pass\n",
        message="'Serial' is used by the Arduino core and cannot be a variable name.",
    )
    error(
        "def blink(HIGH):\n    pass\n\ndef main():\n    pass\n\ndef loop():\n    pass\n",
        message="'HIGH' is used by the Arduino core and cannot be a variable name.",
    )


def test_swap_uses_temporaries(program):
    cpp = program("def main():\n    a = 1\n    b = 2\n    a, b = b, a\n\ndef loop():\n    pass\n")
    assert "int controllerpy_tmp0 = b;" in cpp
    assert "int controllerpy_tmp1 = a;" in cpp
    assert "a = controllerpy_tmp0;" in cpp
    assert "b = controllerpy_tmp1;" in cpp


def test_floor_division_and_power_augmented_assignment(program):
    cpp = program(
        """
        def main():
            total = 7
            total //= 2
            total **= 2
            ratio = 7.5
            ratio //= 2.0

        def loop():
            pass
        """
    )
    assert "total /= 2;" in cpp
    assert "total = pow(total, 2);" in cpp
    assert "ratio = floor(ratio / 2.0);" in cpp


# -------------------------------------------------------------------- serial
def test_serial_helpers_map_to_the_serial_object(program):
    cpp = program(
        """
        def main():
            serial_begin(9600)
            serial_print('a')
            serial_println('b')
            serial_println()
            serial_println(12)

        def loop():
            available = serial_available()
            data = serial_read()
            serial_flush()
            serial_end()
        """
    )
    assert "Serial.begin(9600);" in cpp
    assert 'Serial.print("a");' in cpp
    assert 'Serial.println("b");' in cpp
    assert "Serial.println();" in cpp
    assert "Serial.println(12);" in cpp
    assert "Serial.available();" in cpp
    assert "Serial.read();" in cpp
    assert "Serial.flush();" in cpp
    assert "Serial.end();" in cpp


def test_serial_calls_can_be_written_in_cpp_style(program):
    cpp = program("def main():\n    Serial.begin(9600)\n\ndef loop():\n    pass\n")
    assert "Serial.begin(9600);" in cpp


# ---------------------------------------------------------------- libraries
def test_library_import_adds_the_include_and_the_object(program):
    cpp = program(
        """
        from controllerpy import Servo

        servo = Servo()

        def main():
            servo.attach(9)

        def loop():
            servo.write(90)
        """
    )
    assert "#include <Servo.h>" in cpp
    assert "Servo servo;" in cpp
    assert "servo.attach(9);" in cpp
    assert "servo.write(90);" in cpp


def test_a_registered_constructor_produces_the_library_type(program):
    cpp = program(
        """
        from controllerpy import Servo

        servo = Servo()

        def main():
            pass

        def loop():
            pass
        """
    )
    assert "#include <Servo.h>" in cpp
    assert "Servo servo;" in cpp


def test_library_object_inside_a_function(program):
    cpp = program(
        """
        from controllerpy import SoftwareSerial

        def main():
            link = SoftwareSerial(10, 11)
            link.begin(9600)

        def loop():
            pass
        """
    )
    assert "#include <SoftwareSerial.h>" in cpp
    assert "SoftwareSerial link(10, 11);" in cpp
    # Nothing is registered for SoftwareSerial's members, so they are emitted as written.
    assert "link.begin(9600);" in cpp


def test_a_library_type_without_registered_methods_is_declared_and_used_as_written(program):
    cpp = program(
        """
        from controllerpy import LiquidCrystal

        lcd = LiquidCrystal(12, 13, 14, 15, 16)

        def main():
            lcd.begin(16, 2)
            lcd.print("hi")

        def loop():
            pass
        """
    )
    assert "#include <LiquidCrystal.h>" in cpp
    assert "LiquidCrystal lcd(12, 13, 14, 15, 16);" in cpp
    assert "lcd.begin(16, 2);" in cpp
    assert 'lcd.print("hi");' in cpp


def test_the_core_libraries_are_called_without_being_included(program):
    # Wire, SPI and EEPROM are provided by the Arduino core, so the calls go out
    # as written and the generated program includes no header for them.
    cpp = program(
        """
        def main():
            Wire.begin()
            SPI.transfer(176)
            EEPROM.write(0, 255)

        def loop():
            pass
        """
    )
    assert "#include" not in cpp
    assert "Wire.begin();" in cpp
    assert "SPI.transfer(176);" in cpp
    assert "EEPROM.write(0, 255);" in cpp


def test_a_registered_method_keeps_its_cpp_name(program):
    cpp = program(
        """
        from controllerpy import Servo

        servo = Servo()

        def main():
            servo.attach(9)
            servo.detach()

        def loop():
            servo.write(90)
            value = servo.read()
        """
    )
    assert "servo.attach(9);" in cpp
    assert "servo.detach();" in cpp
    assert "servo.write(90);" in cpp
    assert "int value = servo.read();" in cpp


@pytest.fixture
def renaming_library(monkeypatch) -> Library:
    """A library that only exists for the test that asks for it.

    It carries one method the C++ side spells differently and one it does not, so
    a test can tell a mapped name from a name that was simply left alone.
    """

    library = Library(
        "Gadget",
        "Gadget.h",
        "Gadget",
        classes=(
            ApiClass(
                "Gadget",
                "Gadget",
                methods=(
                    ApiMethod("set_speed", 1, 1, "int", "setSpeed"),
                    ApiMethod("stop", 0, 0),
                ),
            ),
        ),
    )
    monkeypatch.setitem(LIBRARIES, "Gadget", library)

    return library


def test_a_renamed_method_is_emitted_under_its_cpp_name(program, renaming_library):
    cpp = program(
        """
        from controllerpy import Gadget

        gadget = Gadget()

        def main():
            value = gadget.set_speed(100)

        def loop():
            pass
        """
    )
    assert "int value = gadget.setSpeed(100);" in cpp


def test_a_method_without_a_cpp_name_keeps_its_python_name(program, renaming_library):
    cpp = program(
        """
        from controllerpy import Gadget

        gadget = Gadget()

        def main():
            gadget.stop()

        def loop():
            pass
        """
    )
    assert "gadget.stop();" in cpp


def test_a_renamed_method_is_emitted_on_a_library_object_from_inside_a_function(program, renaming_library):
    cpp = program(
        """
        from controllerpy import Gadget

        def main():
            gadget = Gadget()
            gadget.set_speed(1)

        def loop():
            pass
        """
    )
    assert "gadget.setSpeed(1);" in cpp


def test_a_renamed_library_method_does_not_rename_a_user_class_method(program):
    cpp = program(
        """
        class Motor:
            def __init__(self, pin):
                self.pin = pin

            def set_speed(self, value):
                return value

        motor = Motor(9)

        def main():
            value = motor.set_speed(100)

        def loop():
            pass
        """
    )
    assert "int value = motor.set_speed(100);" in cpp


@pytest.fixture
def library_with_its_own_cpp_type(monkeypatch) -> Library:
    """A library whose class type and whose own ``cpp_type`` disagree.

    ``Library.cpp_type`` is the older, coarser description of the library and
    ``ApiClass.cpp_type`` is what the class is actually called.  A test can only
    see which of the two a constructor uses if the two differ.
    """

    library = Library(
        "Widget",
        "Widget.h",
        "widget_handle",
        classes=(ApiClass("Widget", "Widget", methods=(ApiMethod("set_speed", 1, 1, "int", "setSpeed"),)),),
    )
    monkeypatch.setitem(LIBRARIES, "Widget", library)

    return library


def test_a_constructor_produces_the_type_its_class_declares(program, library_with_its_own_cpp_type):
    cpp = program(
        """
        from controllerpy import Widget

        w = Widget()

        def main():
            value = w.set_speed(1)

        def loop():
            pass
        """
    )
    assert "Widget w;" in cpp
    assert "widget_handle w;" not in cpp
    # The type the constructor produced is the one the method system reads.
    assert "int value = w.setSpeed(1);" in cpp


@pytest.fixture
def class_only_library(monkeypatch) -> Library:
    """A library that only exists for the test that asks for it.

    It declares no type of its own, only a class, so nothing but the class
    registration can make the type available.
    """

    library = Library(
        "Doohickey",
        "Doohickey.h",
        None,
        classes=(
            ApiClass(
                "Doohickey",
                "Doohickey",
                methods=(ApiMethod("set_speed", 1, 1, "int", "setSpeed", params=("int",)),),
                ctor_min_args=0,
                ctor_max_args=0,
            ),
        ),
    )
    monkeypatch.setitem(LIBRARIES, "Doohickey", library)

    return library


def test_a_class_only_library_provides_the_type_its_class_declares(program, class_only_library):
    cpp = program(
        """
        from controllerpy import Doohickey

        thing = Doohickey()

        def main():
            pass

        def loop():
            pass
        """
    )
    assert "#include <Doohickey.h>" in cpp
    assert "Doohickey thing;" in cpp


def test_a_class_only_library_class_uses_its_registered_methods(program, class_only_library):
    cpp = program(
        """
        from controllerpy import Doohickey

        thing = Doohickey()

        def main():
            value = thing.set_speed(100)

        def loop():
            pass
        """
    )
    assert "int value = thing.setSpeed(100);" in cpp


def test_a_declared_argument_type_does_not_change_the_cpp_it_generates(program, class_only_library):
    # The class registers set_speed() as taking an int; describing the type is
    # a check, so the call is generated exactly as it was without it.
    cpp = program(
        """
        from controllerpy import Doohickey

        thing = Doohickey()

        def main():
            thing.set_speed(100)

        def loop():
            pass
        """
    )
    assert "thing.setSpeed(100);" in cpp


@pytest.fixture
def multi_class_library(monkeypatch) -> Library:
    """A library that only exists for the test that asks for it.

    It declares no type of its own and contributes two classes, each with its
    own constructor, so neither class can be standing in for the other.
    """

    library = Library(
        "SomeLib",
        "SomeLib.h",
        None,
        classes=(
            ApiClass("Foo", "Foo", methods=(ApiMethod("ping", 0, 0),)),
            ApiClass("Bar", "Bar", ctor_min_args=1, ctor_max_args=1),
        ),
    )
    monkeypatch.setitem(LIBRARIES, "SomeLib", library)

    return library


def test_one_library_can_provide_several_classes(program, multi_class_library):
    cpp = program(
        """
        from controllerpy import Foo
        from controllerpy import Bar

        foo = Foo()
        bar = Bar(3)

        def main():
            foo.ping()

        def loop():
            pass
        """
    )
    assert cpp.count("#include <SomeLib.h>") == 1
    assert "Foo foo;" in cpp
    assert "Bar bar(3);" in cpp
    assert "foo.ping();" in cpp


@pytest.fixture
def oddly_named_class_library(monkeypatch) -> Library:
    """A library that only exists for the test that asks for it.

    Its class is imported under one name and is a different type in C++, which
    is what tells the two apart.
    """

    library = Library(
        "OddLib",
        "OddLib.h",
        None,
        classes=(ApiClass("Odd", "odd_t", methods=(ApiMethod("ping", 0, 0),)),),
    )
    monkeypatch.setitem(LIBRARIES, "OddLib", library)

    return library


def test_a_class_is_found_by_the_type_it_produces(program, oddly_named_class_library):
    cpp = program(
        """
        from controllerpy import Odd

        odd = Odd()

        def main():
            odd.ping()

        def loop():
            pass
        """
    )
    assert "odd_t odd;" in cpp
    assert "odd.ping();" in cpp


def test_an_arduino_builtin_object_member_keeps_its_name(program):
    cpp = program(
        """
        def main():
            Serial.begin(9600)
            Serial.println("hi")

        def loop():
            pass
        """
    )
    assert "Serial.begin(9600);" in cpp
    assert 'Serial.println("hi");' in cpp


# ------------------------------------------------------------------- classes
def test_class_becomes_a_cpp_class(program):
    cpp = program(
        """
        class Led:
            def __init__(self, pin):
                self.pin = pin
                pin_mode(pin, OUTPUT)

            def on(self):
                digital_write(self.pin, HIGH)

            def off(self):
                digital_write(self.pin, LOW)

        def main():
            led = Led(13)
            led.on()

        def loop():
            pass
        """
    )
    assert cpp.count("class Led {") == 1
    assert "public:" in cpp
    assert "    int pin;" in cpp
    assert "    Led(int pin) {" in cpp
    assert "        this->pin = pin;" in cpp
    assert "    void on() {" in cpp
    assert "        digitalWrite(this->pin, HIGH);" in cpp
    assert "Led led(13);" in cpp
    assert "led.on();" in cpp


def test_methods_can_call_methods(program):
    cpp = program(
        """
        class Motor:
            def __init__(self, pin):
                self.pin = pin

            def start(self):
                self.enable(True)

            def enable(self, state):
                digital_write(self.pin, state)

        def main():
            motor = Motor(5)
            motor.start()

        def loop():
            pass
        """
    )
    assert "this->enable(true);" in cpp
    assert "void enable(bool state) {" in cpp


def test_class_field_types_are_promoted(program):
    cpp = program(
        """
        class Sensor:
            def __init__(self, pin):
                self.pin = pin
                self.average = 0

            def sample(self):
                self.average = analog_read(self.pin) / 2.0

        def main():
            pass

        def loop():
            pass
        """
    )
    assert "    float average;" in cpp


def test_classes_are_ordered_by_their_dependencies(program):
    cpp = program(
        """
        class Inner:
            def __init__(self, value):
                self.value = value

        class Outer:
            def __init__(self):
                self.inner = Inner(1)

        def main():
            outer = Outer()

        def loop():
            pass
        """
    )
    assert cpp.index("class Inner {") < cpp.index("class Outer {")


def test_global_object_is_declared_after_its_class(program):
    cpp = program(
        """
        class Led:
            def __init__(self, pin):
                self.pin = pin

        status = Led(13)

        def main():
            pass

        def loop():
            pass
        """
    )
    assert cpp.index("class Led {") < cpp.index("Led status(13);")


def test_prototypes_are_emitted_before_use(program):
    cpp = program("def helper():\n    digital_write(13, HIGH)\n" + SHELL)
    assert "void helper();" in cpp
    assert cpp.index("void helper();") < cpp.index("void setup()")


# ------------------------------------------------------------------- structs
def test_a_class_of_fields_becomes_a_cpp_struct(program):
    cpp = program(
        """
        class Point:
            x: int
            y: float

        def main():
            point = Point()
            point.x = 3
            point.y = 1.5

        def loop():
            pass
        """
    )
    assert cpp.count("struct Point {") == 1
    assert "public:" not in cpp
    assert "    int x;\n    float y;\n};" in cpp
    assert "    Point point;\n" in cpp
    assert "    point.x = 3;\n" in cpp
    assert "    point.y = 1.5;\n" in cpp


def test_a_struct_field_keeps_its_declared_type(program):
    cpp = program(
        """
        class Reading:
            label: str

        def main():
            reading = Reading()
            reading.label = "voltage"

        def loop():
            pass
        """
    )
    assert "    String label;\n};" in cpp
    assert "    reading.label = \"voltage\";\n" in cpp


def test_a_struct_object_is_declared_after_its_struct(program):
    cpp = program(
        """
        class Point:
            x: int

        origin = Point()

        def main():
            origin.x = 1

        def loop():
            pass
        """
    )
    assert "Point origin;" in cpp
    assert cpp.index("struct Point {") < cpp.index("Point origin;")


def test_a_struct_may_be_a_parameter_and_a_return_type(program):
    cpp = program(
        """
        class Point:
            x: int

        def shifted(point: Point) -> Point:
            other = Point()
            other.x = point.x + 1
            return other

        def main():
            start = Point()
            start.x = 1
            shifted(start)

        def loop():
            pass
        """
    )
    assert "Point shifted(Point point);" in cpp
    assert "Point shifted(Point point) {" in cpp
    assert "    Point other;" in cpp
    assert "    return other;" in cpp


def test_a_struct_may_hold_another_struct(program):
    cpp = program(
        """
        class Point:
            x: int

        class Waypoint:
            point: Point

        def main():
            waypoint = Waypoint()
            waypoint.point = Point()

        def loop():
            pass
        """
    )
    assert "    Point point;\n};" in cpp
    assert "    Waypoint waypoint;\n" in cpp
    assert "    waypoint.point = Point();\n" in cpp
    assert cpp.index("struct Point {") < cpp.index("struct Waypoint {")


def test_a_class_may_hold_a_struct(program):
    cpp = program(
        """
        class Point:
            x: int

        class Marker:
            def __init__(self, origin: Point):
                self.origin = origin

        def main():
            marker = Marker(Point())

        def loop():
            pass
        """
    )
    assert "    Point origin;\n" in cpp
    assert "    Marker(Point origin) {" in cpp
    assert "    Marker marker(Point());" in cpp
    assert cpp.index("struct Point {") < cpp.index("class Marker {")


def test_a_struct_field_named_after_a_cpp_keyword_is_renamed(program):
    cpp = program(
        """
        class Flag:
            explicit: bool

        def main():
            flag = Flag()
            flag.explicit = True

        def loop():
            pass
        """
    )
    assert "    bool explicit_;\n};" in cpp
    assert "    flag.explicit_ = true;\n" in cpp


def test_a_list_of_struct_objects_becomes_a_cpp_array(program):
    cpp = program(
        """
        class Reading:
            value: int
            bright: bool

        readings = [
            Reading(),
            Reading(),
        ]

        def main():
            pass

        def loop():
            pass
        """
    )
    assert "Reading readings[2] = {Reading(), Reading()};" in cpp
    assert "const Reading" not in cpp
    assert cpp.index("struct Reading {") < cpp.index("Reading readings[2]")


def test_a_local_list_of_struct_objects_becomes_a_cpp_array(program):
    cpp = program(
        """
        class Reading:
            value: int

        def main():
            readings = [Reading(), Reading()]
            size = len(readings)

        def loop():
            pass
        """
    )
    assert "    Reading readings[2] = {Reading(), Reading()};\n" in cpp
    assert "    int size = (sizeof(readings) / sizeof(readings[0]));\n" in cpp


def test_a_list_of_structs_with_nested_struct_fields_becomes_a_cpp_array(program):
    cpp = program(
        """
        class Reading:
            value: int

        class Sample:
            label: str
            first: Reading

        samples = [Sample(), Sample()]

        def main():
            pass

        def loop():
            pass
        """
    )
    assert "Sample samples[2] = {Sample(), Sample()};" in cpp
    assert cpp.index("struct Reading {") < cpp.index("struct Sample {")
    assert cpp.index("struct Sample {") < cpp.index("Sample samples[2]")


def test_indexing_a_struct_array_reads_elements_and_fields(program):
    cpp = program(
        """
        class Reading:
            value: int
            bright: bool

        readings = [
            Reading(),
            Reading(),
        ]

        def main():
            element = readings[0]
            value = readings[0].value
            bright = readings[1].bright

        def loop():
            pass
        """
    )
    assert "    Reading element = readings[0];\n" in cpp
    assert "    int value = readings[0].value;\n" in cpp
    assert "    bool bright = readings[1].bright;\n" in cpp


def test_indexing_a_struct_array_writes_fields(program):
    cpp = program(
        """
        class Reading:
            value: int
            bright: bool

        readings = [
            Reading(),
            Reading(),
        ]

        def main():
            readings[0].value = 123
            readings[1].bright = True

        def loop():
            pass
        """
    )
    assert "    readings[0].value = 123;\n" in cpp
    assert "    readings[1].bright = true;\n" in cpp


def test_indexing_nested_struct_fields_through_an_array(program):
    cpp = program(
        """
        class Reading:
            value: int

        class Sample:
            first: Reading

        samples = [Sample(), Sample()]

        def main():
            value = samples[0].first.value
            samples[1].first.value = 7

        def loop():
            pass
        """
    )
    assert "    int value = samples[0].first.value;\n" in cpp
    assert "    samples[1].first.value = 7;\n" in cpp


def test_a_whole_struct_can_be_assigned_to_an_array_element(program):
    cpp = program(
        """
        class Reading:
            value: int
            bright: bool

        readings = [
            Reading(),
            Reading(),
        ]

        def main():
            reading = Reading()
            reading.value = 4
            readings[0] = Reading()
            readings[1] = reading

        def loop():
            pass
        """
    )
    assert "    readings[0] = Reading();\n" in cpp
    assert "    readings[1] = reading;\n" in cpp


def test_a_whole_struct_can_be_assigned_to_a_nested_struct_array_element(program):
    cpp = program(
        """
        class Reading:
            value: int

        class Sample:
            first: Reading

        samples = [Sample(), Sample()]

        def main():
            samples[0] = Sample()
            samples[1] = samples[0]

        def loop():
            pass
        """
    )
    assert "    samples[0] = Sample();\n" in cpp
    assert "    samples[1] = samples[0];\n" in cpp


def test_an_appended_struct_list_becomes_a_counted_cpp_array(program):
    cpp = program(
        """
        class Reading:
            value: int
            bright: bool

        readings = []

        def main():
            readings.append(Reading())
            readings.append(Reading())
            size = len(readings)

        def loop():
            pass
        """
    )
    assert "Reading readings[2];\n" in cpp
    assert "int readings_count = 0;\n" in cpp
    assert "    readings[readings_count++] = Reading();\n" in cpp
    assert cpp.count("readings[readings_count++] = Reading();") == 2
    assert "    int size = readings_count;\n" in cpp
    assert cpp.index("struct Reading {") < cpp.index("Reading readings[2]")


def test_a_local_appended_struct_list_becomes_a_counted_cpp_array(program):
    cpp = program(
        """
        class Reading:
            value: int

        def main():
            readings = []
            reading = Reading()
            readings.append(reading)
            size = len(readings)

        def loop():
            pass
        """
    )
    assert "    Reading readings[1];\n" in cpp
    assert "    int readings_count = 0;\n" in cpp
    assert "    readings[readings_count++] = reading;\n" in cpp
    assert "    int size = readings_count;\n" in cpp


def test_a_list_literal_and_an_append_size_the_array_for_both(program):
    cpp = program(
        """
        class Reading:
            value: int

        readings = [Reading()]

        def main():
            readings.append(Reading())

        def loop():
            pass
        """
    )
    assert "Reading readings[2] = {Reading()};\n" in cpp
    assert "int readings_count = 1;\n" in cpp
    assert "    readings[readings_count++] = Reading();\n" in cpp


def test_a_struct_with_struct_fields_can_be_appended(program):
    cpp = program(
        """
        class Reading:
            value: int

        class Sample:
            first: Reading

        samples = []

        def main():
            samples.append(Sample())
            samples.append(Sample())
            size = len(samples)

        def loop():
            pass
        """
    )
    assert "Sample samples[2];\n" in cpp
    assert "int samples_count = 0;\n" in cpp
    assert "    samples[samples_count++] = Sample();\n" in cpp
    assert "    int size = samples_count;\n" in cpp
    assert cpp.index("struct Reading {") < cpp.index("struct Sample {")
    assert cpp.index("struct Sample {") < cpp.index("Sample samples[2]")


# ---------------------------------------------------------------- formatting
def test_generated_code_is_consistently_formatted(program, result):
    cpp = program(
        """
        LED = 13

        def main():
            pin_mode(LED, OUTPUT)

        def loop():
            digital_write(LED, HIGH)
            delay(1000)
        """
    )
    assert "\t" not in cpp
    assert cpp.endswith("}\n")
    assert "\n\n\n" not in cpp
    for line in cpp.splitlines():
        assert line == line.rstrip()

def test_generation_is_deterministic(result):
    source = "LED = 13\n\ndef main():\n    pin_mode(LED, OUTPUT)\n\ndef loop():\n    digital_write(LED, HIGH)\n"
    first = result(source).cpp
    second = result(source).cpp
    assert first == second


def test_code_writer_indents_and_strips_trailing_blank_lines():
    writer = CodeWriter()
    writer.line("void setup() {")
    writer.indent()
    writer.line("pinMode(13, OUTPUT);")
    writer.dedent()
    writer.line("}")
    writer.blank()
    assert writer.text() == "void setup() {\n    pinMode(13, OUTPUT);\n}\n"


# -------------------------------------------------------------- Arduino API
def test_arduino_api_functions_map_to_cpp(program):
    cpp = program(
        """
        def main():
            pin_mode(13, OUTPUT)
            digital_write(13, HIGH)
            digital_read(13)
            analog_read(A0)
            analog_write(9, 128)
            delay(1)
            delay_microseconds(10)
            millis()
            micros()

        def loop():
            reading = analog_read(A1)
            analog_write(10, reading / 4)
        """
    )
    assert "pinMode(13, OUTPUT);" in cpp
    assert "digitalWrite(13, HIGH);" in cpp
    assert "digitalRead(13);" in cpp
    assert "analogRead(A0);" in cpp
    assert "analogWrite(9, 128);" in cpp
    assert "    delay(1);" in cpp
    assert "delayMicroseconds(10);" in cpp
    assert "millis();" in cpp
    assert "micros();" in cpp
    assert "analogRead(A1);" in cpp
    assert "analogWrite(10, reading / 4);" in cpp


def test_arduino_constants_are_never_replaced_by_numbers(program):
    cpp = program(
        """
        def main():
            pin_mode(2, INPUT_PULLUP)
            pin_mode(3, INPUT_PULLDOWN)
            digital_write(4, LOW)
            digital_write(5, HIGH)
            attach = CHANGE
            rising = RISING
            falling = FALLING
            builtin = LED_BUILTIN

        def loop():
            pass
        """
    )
    for constant in ("INPUT_PULLUP", "INPUT_PULLDOWN", "LOW", "HIGH", "CHANGE", "RISING", "FALLING", "LED_BUILTIN"):
        assert constant in cpp
    assert "pinMode(2, INPUT_PULLUP);" in cpp
    assert "digitalWrite(4, LOW);" in cpp
    assert "digitalWrite(5, HIGH);" in cpp


def test_pulse_in_maps_to_the_arduino_function(program):
    cpp = program(
        """
        def main():
            pin_mode(7, INPUT)
            pulseIn(7, HIGH)

        def loop():
            duration = pulseIn(7, HIGH)
            released = pulseIn(8, LOW)
            bounded = pulseIn(9, HIGH, 500000)
        """
    )
    assert "pinMode(7, INPUT);" in cpp
    assert "pulseIn(7, HIGH);" in cpp
    assert "int duration = pulseIn(7, HIGH);" in cpp
    assert "int released = pulseIn(8, LOW);" in cpp
    assert "int bounded = pulseIn(9, HIGH, 500000);" in cpp


def test_pulse_in_result_is_used_like_any_other_value(program):
    cpp = program(
        """
        def main():
            pass

        def loop():
            duration = pulseIn(7, HIGH)
            serial_println(duration)
        """
    )
    assert "int duration = pulseIn(7, HIGH);" in cpp
    assert "Serial.println(duration);" in cpp


def test_pulse_in_result_promotes_a_float_global_to_float(program):
    """Regression: pulseIn() returns an int, so a float variable stays valid."""
    cpp = program(
        """
        buzzer = 8
        trig_pin = 9
        echo_pin = 10
        timing = 0.0
        distance = 0.0

        def main():
            pin_mode(echo_pin, INPUT)
            pin_mode(trig_pin, OUTPUT)
            pin_mode(buzzer, OUTPUT)

        def loop():
            timing = pulseIn(echo_pin, HIGH)
            distance = (timing * 0.34) / 2
        """
    )
    assert "float timing = 0.0;" in cpp
    assert "float distance = 0.0;" in cpp
    assert "timing = pulseIn(echo_pin, HIGH);" in cpp
    assert "distance = (timing * 0.34) / 2;" in cpp


def test_pulse_in_result_updates_an_int_global_from_a_function(program):
    """Assigning inside loop() updates the module level variable - never a shadow."""
    cpp = program(
        """
        echo_pin = 10
        timing = 0

        def main():
            pin_mode(echo_pin, INPUT)

        def loop():
            timing = pulseIn(echo_pin, HIGH)
        """
    )
    assert "int timing = 0;" in cpp
    assert "timing = pulseIn(echo_pin, HIGH);" in cpp
    assert cpp.count("int timing") == 1


def test_tone_and_no_tone_map_to_the_arduino_functions(program):
    cpp = program(
        """
        def main():
            tone(8, 1000)

        def loop():
            tone(8, 1000, 500)
            noTone(8)
        """
    )
    assert "tone(8, 1000);" in cpp
    assert "tone(8, 1000, 500);" in cpp
    assert "noTone(8);" in cpp


def test_tone_accepts_a_pin_variable_and_a_computed_frequency(program):
    cpp = program(
        """
        BUZZER = 8
        BASE = 440

        def main():
            pin_mode(BUZZER, OUTPUT)

        def loop():
            tone(BUZZER, BASE * 2)
            tone(BUZZER, 880, 250)
            noTone(BUZZER)
        """
    )
    assert "const int BUZZER = 8;" in cpp
    assert "const int BASE = 440;" in cpp
    assert "pinMode(BUZZER, OUTPUT);" in cpp
    assert "tone(BUZZER, BASE * 2);" in cpp
    assert "tone(BUZZER, 880, 250);" in cpp
    assert "noTone(BUZZER);" in cpp
