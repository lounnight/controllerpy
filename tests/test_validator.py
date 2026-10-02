"""Stage 2: the validator decides what is part of the supported subset."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import get_type_hints

import pytest

import controllerpy.compiler.validator as validator
from controllerpy.compiler.validator.libraries import LIBRARIES, ApiClass, ApiMethod, Library, library_for, supported_libraries
from controllerpy.compiler.validator.types import SCALAR_TYPES

SHELL = "\ndef main():\n    pass\n\ndef loop():\n    pass\n"

#: The registry is the source of truth for which libraries can be imported, so
#: the import tests are written against whatever it lists.
LIBRARY_NAMES = sorted(supported_libraries())


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
        hint="from controllerpy import",
        line=1,
        col=1,
    )


def test_from_import_of_a_python_library_is_rejected(error):
    error("from numpy import array\n" + SHELL, message="Python library 'numpy' is not supported on Arduino.")


def test_known_arduino_library_import_is_accepted(result):
    compiled = result("from controllerpy import Servo\n" + SHELL)
    assert "Servo.h" in compiled.context.includes
    assert compiled.context.external_types["Servo"] == "Servo"


def test_api_star_import_is_accepted_for_ide_support(result):
    compiled = result("from controllerpy import *\nimport controllerpy\n" + SHELL)
    assert compiled.context.includes == []


def test_unknown_name_from_api_import_is_rejected(error):
    error(
        "from controllerpy import teleport\n" + SHELL,
        message="'teleport' is not part of the controllerpy API.",
    )


def test_ide_only_module_imports_are_skipped(result):
    compiled = result(
        "import builtins\nfrom builtins import *\nimport controllerpy_api\nfrom controllerpy_api import *\n" + SHELL
    )
    assert compiled.context.includes == []


def test_named_import_from_the_api_stub_is_accepted(result):
    compiled = result("from controllerpy_api import HIGH, pin_mode\n" + SHELL)
    assert compiled.context.includes == []


# ------------------------------------------------ imports through the registry
@pytest.mark.parametrize("name", LIBRARY_NAMES)
def test_every_registered_library_is_importable_from_the_api_module(result, name):
    library = library_for(name)
    compiled = result(f"from controllerpy import {name}\n" + SHELL)

    assert compiled.context.imported_libraries[name] is library
    assert compiled.context.includes == [library.header]
    assert f"#include <{library.header}>" in compiled.cpp
    if library.cpp_type is None:
        assert name not in compiled.context.external_types
    else:
        assert compiled.context.external_types[name] == library.cpp_type


@pytest.mark.parametrize("name", LIBRARY_NAMES)
def test_every_registered_library_is_importable_by_its_own_name(result, name):
    compiled = result(f"import {name}\n" + SHELL)

    assert compiled.context.includes == [library_for(name).header]


@pytest.mark.parametrize("name", LIBRARY_NAMES)
def test_every_registered_library_is_importable_from_its_own_module(result, name):
    compiled = result(f"from {name} import {name}\n" + SHELL)

    assert compiled.context.includes == [library_for(name).header]


def test_a_library_module_name_is_metadata_and_not_an_import_alias(error):
    # Servo records module="servo", but a library is only ever imported by the
    # name the registry lists it under.
    error(
        "from servo import Servo\n" + SHELL,
        message="Python library 'servo' is not supported on Arduino.",
    )


def test_importing_a_library_by_its_module_name_is_rejected(error):
    error("import servo\n" + SHELL, message="Python library 'servo' is not supported on Arduino.")


def test_a_name_that_is_not_a_registered_library_is_rejected(error):
    error(
        "from controllerpy import Widget\n" + SHELL,
        message="'Widget' is not part of the controllerpy API.",
    )


def test_the_unsupported_library_hint_lists_the_registered_libraries(error):
    exc = error("import requests\n" + SHELL, message="not supported on Arduino")

    for name in LIBRARY_NAMES:
        assert f"from controllerpy import {name}" in exc.hint_lines


def test_the_unknown_api_name_hint_lists_the_registered_libraries(error):
    exc = error("from controllerpy import Widget\n" + SHELL)

    for name in LIBRARY_NAMES:
        assert name in exc.hint_lines


# --------------------------------------------- library class constructors
def test_servo_is_created_with_the_registered_constructor(result):
    compiled = result("from controllerpy import Servo\n\nservo = Servo()\n" + SHELL)

    assert compiled.context.globals["servo"].cpp_type == "Servo"
    assert "Servo servo;" in compiled.cpp


def test_servo_constructor_rejects_an_argument(error):
    error(
        "from controllerpy import Servo\n\nservo = Servo(9)\n" + SHELL,
        message="Servo() takes exactly 0 arguments but 1 was given.",
        line=3,
        col=9,
    )


def test_servo_constructor_rejects_several_arguments(error):
    error(
        "from controllerpy import Servo\n\nservo = Servo(9, 8)\n" + SHELL,
        message="Servo() takes exactly 0 arguments but 2 were given.",
    )


def test_a_library_class_is_only_known_once_it_is_imported(error):
    error("def main():\n    servo = Servo()\n\ndef loop():\n    pass\n", message="Unknown ArduinoPy function: Servo()")


@pytest.fixture
def registered_library(monkeypatch) -> Library:
    """A library that only exists for the test that asks for it.

    It takes one or two constructor arguments, so the checks below cannot pass by
    accident against a fixed arity, and the compiler knows nothing about it that
    is not in the registry entry.
    """

    library = Library(
        "Widget",
        "Widget.h",
        "Widget",
        classes=(
            ApiClass(
                "Widget",
                "Widget",
                methods=(ApiMethod("spin", 0, 1, "int"),),
                ctor_min_args=1,
                ctor_max_args=2,
            ),
        ),
    )
    monkeypatch.setitem(LIBRARIES, "Widget", library)

    return library


def test_a_registered_constructor_takes_the_arguments_it_declares(result, registered_library):
    compiled = result("from controllerpy import Widget\n\nw = Widget(3)\n" + SHELL)

    assert compiled.context.globals["w"].cpp_type == "Widget"
    assert "Widget w(3);" in compiled.cpp


def test_a_registered_constructor_rejects_too_few_arguments(error, registered_library):
    error(
        "from controllerpy import Widget\n\nw = Widget()\n" + SHELL,
        message="Widget() takes 1 to 2 arguments but 0 were given.",
    )


def test_a_registered_constructor_rejects_too_many_arguments(error, registered_library):
    error(
        "from controllerpy import Widget\n\nw = Widget(1, 2, 3)\n" + SHELL,
        message="Widget() takes 1 to 2 arguments but 3 were given.",
    )


def test_a_library_without_class_metadata_keeps_its_constructor_unchecked(result):
    # SoftwareSerial registers no class, so its type is used as it stands.
    compiled = result("from controllerpy import SoftwareSerial\n\nlink = SoftwareSerial(10, 11, 12)\n" + SHELL)

    assert compiled.context.globals["link"].cpp_type == "SoftwareSerial"
    assert "SoftwareSerial link(10, 11, 12);" in compiled.cpp


# ----------------------------------------------- library class methods
SERVO = "from controllerpy import Servo\n\nservo = Servo()\n"
WIDGET = "from controllerpy import Widget\n\nw = Widget(3)\n"


def running(preamble: str, body: str) -> str:
    """A module that declares *preamble* and calls *body* from main()."""

    return preamble + f"\ndef main():\n    {body}\n\ndef loop():\n    pass\n"


@pytest.mark.parametrize(
    "call",
    ["servo.attach(9)", "servo.attach(9, 8, 7)", "servo.detach()", "servo.write(90)"],
)
def test_a_library_method_takes_the_arguments_it_declares(result, call):
    compiled = result(running(SERVO, call))

    assert f"{call};" in compiled.cpp


@pytest.mark.parametrize("call", ["servo.attach(9)", "servo.read()"])
def test_a_library_method_returns_what_it_declares(result, call):
    compiled = result(running(SERVO, f"value = {call}"))

    assert f"int value = {call};" in compiled.cpp


@pytest.mark.parametrize(
    ("call", "message"),
    [
        ("servo.attach()", "Servo.attach() takes 1 to 3 arguments but 0 were given."),
        ("servo.attach(1, 2, 3, 4)", "Servo.attach() takes 1 to 3 arguments but 4 were given."),
        ("servo.detach(1)", "Servo.detach() takes exactly 0 arguments but 1 was given."),
        ("servo.write()", "Servo.write() takes exactly 1 argument but 0 were given."),
        ("servo.read(1)", "Servo.read() takes exactly 0 arguments but 1 was given."),
    ],
)
def test_a_library_method_rejects_arguments_it_does_not_take(error, call, message):
    error(running(SERVO, call), message=message)


def test_a_library_class_has_only_the_methods_it_declares(error):
    error(running(SERVO, "servo.tune(90)"), message="Class 'Servo' has no method 'tune'.")


def test_a_library_object_without_class_metadata_keeps_its_methods_unchecked(result):
    # SoftwareSerial registers no class, so nothing is known about its members.
    compiled = result(running("from controllerpy import SoftwareSerial\n\nlink = SoftwareSerial(10, 11)\n", "link.begin(9600)"))

    assert "link.begin(9600);" in compiled.cpp


# ------------------------------------------ libraries the core also provides
LIQUID_CRYSTAL = "from controllerpy import LiquidCrystal\n\nlcd = LiquidCrystal(12, 13, 14, 15, 16)\n"


def test_liquid_crystal_is_registered_as_a_library_type(result):
    compiled = result(LIQUID_CRYSTAL + SHELL)

    assert compiled.context.includes == ["LiquidCrystal.h"]
    assert compiled.context.external_types["LiquidCrystal"] == "LiquidCrystal"
    assert "LiquidCrystal lcd(12, 13, 14, 15, 16);" in compiled.cpp


@pytest.mark.parametrize(
    "call",
    ['lcd.begin(16, 2)', 'lcd.begin(16, 2, 10, 10)', 'lcd.print("hi")', "lcd.setCursor(0, 1)", "lcd.nonsense(1, 2, 3)"],
)
def test_liquid_crystal_members_are_passed_through(result, call):
    # Nothing is registered for LiquidCrystal's methods, so every one of them is
    # emitted as written, whatever its arity and whatever it returns.
    compiled = result(running(LIQUID_CRYSTAL, call))

    assert f"{call};" in compiled.cpp


@pytest.mark.parametrize(
    ("arguments", "declared"),
    [("", "LiquidCrystal lcd;"), ("()", "LiquidCrystal lcd;"), ("(9)", "LiquidCrystal lcd(9);")],
)
def test_liquid_crystal_constructor_arguments_are_not_checked(result, arguments, declared):
    compiled = result(f"from controllerpy import LiquidCrystal\n\nlcd = LiquidCrystal{arguments}\n" + SHELL)

    assert declared in compiled.cpp


def test_a_library_type_can_be_annotated(result):
    compiled = result("from controllerpy import LiquidCrystal\n\nlcd: LiquidCrystal = LiquidCrystal(12, 13)\n" + SHELL)

    assert "LiquidCrystal lcd(12, 13);" in compiled.cpp


@pytest.mark.parametrize(
    "call",
    ["Wire.begin()", "Wire.beginTransmission(3)", "Wire.write(1)", "SPI.transfer(0)", "EEPROM.read(0)", "EEPROM.write(1, 255)"],
)
def test_a_core_library_needs_no_import_to_be_used(result, call):
    # Wire, SPI and EEPROM come with the Arduino core, so there is nothing to
    # import and nothing to include.
    compiled = result(running("", call))

    assert compiled.context.includes == []
    assert f"{call};" in compiled.cpp


def test_a_core_library_can_be_imported_for_its_header(result):
    compiled = result("from controllerpy import Wire\n" + SHELL)

    assert compiled.context.includes == ["Wire.h"]
    # Importing it registers no type: the core declares the object, not a type
    # a program declares a value of.
    assert compiled.context.external_types == {}


def test_a_core_library_member_must_be_called(error):
    error(running("", "value = Wire.available"), message="Wire.available must be called as a method.")


def test_a_core_library_name_cannot_be_redefined(error):
    error("Wire = 5\n" + SHELL, message="'Wire' is an Arduino name and cannot be redefined.")


def test_a_core_library_name_cannot_be_a_variable(error):
    error(running("", "Wire = 5"), message="'Wire' is used by the Arduino core and cannot be a variable name.")


def test_a_registered_method_is_found_on_any_value_of_the_class(result, registered_library):
    compiled = result(running(WIDGET, "other = Widget(5)\n    other.spin()"))

    assert "Widget other(5);" in compiled.cpp
    assert "other.spin();" in compiled.cpp


def test_a_registered_method_returns_what_it_declares(result, registered_library):
    compiled = result(running(WIDGET, "value = w.spin(1)"))

    assert "int value = w.spin(1);" in compiled.cpp


def test_a_registered_method_rejects_arguments_it_does_not_take(error, registered_library):
    error(running(WIDGET, "w.spin(1, 2)"), message="Widget.spin() takes 0 to 1 arguments but 2 were given.")


def test_a_registered_class_has_only_the_methods_it_declares(error, registered_library):
    error(running(WIDGET, "w.tune()"), message="Class 'Widget' has no method 'tune'.")


def test_a_library_method_is_unknown_before_the_library_is_imported(error):
    error("def main():\n    servo.attach(9)\n\ndef loop():\n    pass\n", message="Unknown name: 'servo'")


# ------------------------------------------- libraries with no cpp_type
@pytest.fixture
def class_only_library(monkeypatch) -> Library:
    """A library that only exists for the test that asks for it.

    It declares no type of its own, only a class, so nothing but the class
    registration can make the type available.
    """

    library = Library(
        "Gadget",
        "Gadget.h",
        None,
        classes=(ApiClass("Gadget", "Gadget", methods=(ApiMethod("ping", 0, 0),), ctor_min_args=0, ctor_max_args=0),),
    )
    monkeypatch.setitem(LIBRARIES, "Gadget", library)

    return library


def test_a_class_only_library_provides_its_type(result, class_only_library):
    compiled = result("from controllerpy import Gadget\n" + SHELL)

    assert compiled.context.includes == ["Gadget.h"]
    assert compiled.context.external_types["Gadget"] == "Gadget"


def test_a_class_only_library_validates_its_constructor(error, class_only_library):
    error("from controllerpy import Gadget\n\ngadget = Gadget(1)\n" + SHELL, message="Gadget() takes exactly 0 arguments but 1 was given.")


def test_a_class_only_library_keeps_its_method_validation(error, class_only_library):
    error(
        "from controllerpy import Gadget\n\ngadget = Gadget()\n\ndef main():\n    gadget.ping(1)\n\ndef loop():\n    pass\n",
        message="Gadget.ping() takes exactly 0 arguments but 1 was given.",
    )


def test_a_class_only_library_records_the_library_and_the_class_it_provides(result, class_only_library):
    compiled = result("from controllerpy import Gadget\n" + SHELL)

    # The library is imported under the name of the class it provides, and the
    # class is what the compiler resolves that name to.
    assert list(compiled.context.imported_libraries) == ["Gadget"]
    assert compiled.context.library_class("Gadget").cpp_type == "Gadget"


def test_a_library_without_classes_keeps_only_its_own_type(result):
    compiled = result("from controllerpy import SoftwareSerial\n" + SHELL)

    assert compiled.context.external_types == {"SoftwareSerial": "SoftwareSerial"}
    assert compiled.context.library_class("SoftwareSerial") is None


# ------------------------------------------------- argument type checking
@pytest.fixture
def typed_library(monkeypatch) -> Library:
    """A library that describes the types of some of the arguments it takes.

    It registers ``set_speed``, ``configure`` and a constructor whose types it
    knows, and ``ping``, whose types it does not, so both paths are exercised.
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
                    ApiMethod("set_speed", 1, 1, "void", params=("int",)),
                    ApiMethod("configure", 2, 2, "void", params=("int", "float")),
                    ApiMethod("ping", 0, 1, "int"),
                ),
                ctor_params=("int",),
                ctor_min_args=1,
                ctor_max_args=1,
            ),
        ),
    )
    monkeypatch.setitem(LIBRARIES, "Gadget", library)

    return library


TYPED = "from controllerpy import Gadget\n\ngadget = Gadget(10)\n"


def test_a_method_takes_the_argument_types_it_declares(result, typed_library):
    compiled = result(running(TYPED, "gadget.set_speed(100)"))

    assert "gadget.set_speed(100);" in compiled.cpp


def test_a_method_rejects_an_argument_type_it_does_not_declare(error, typed_library):
    error(running(TYPED, "gadget.set_speed('100')"), message="Argument 1 of Gadget.set_speed() must be int, not const char*.")


@pytest.mark.parametrize("body", ["gadget.configure(1, 2.5)", "gadget.configure(1, 2)"])
def test_every_argument_of_a_method_is_checked_in_turn(result, typed_library, body):
    # An int is stored in a float, the way the type system allows everywhere else.
    compiled = result(running(TYPED, body))

    assert f"{body};" in compiled.cpp


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("gadget.configure('1', 2.5)", "Argument 1 of Gadget.configure() must be int, not const char*."),
        ("gadget.configure(1, '2.5')", "Argument 2 of Gadget.configure() must be float, not const char*."),
    ],
)
def test_a_method_rejects_the_argument_type_at_the_position_it_was_given(error, typed_library, body, message):
    error(running(TYPED, body), message=message)


def test_a_constructor_takes_the_argument_types_it_declares(result, typed_library):
    compiled = result("from controllerpy import Gadget\n\ngadget = Gadget(10)\n" + SHELL)

    assert "Gadget gadget(10);" in compiled.cpp


def test_a_constructor_rejects_an_argument_type_it_does_not_declare(error, typed_library):
    error("from controllerpy import Gadget\n\ngadget = Gadget('10')\n" + SHELL, message="Argument 1 of Gadget() must be int, not const char*.")


def test_a_method_without_declared_types_only_has_its_arity_checked(result, typed_library):
    # Gadget.ping() registers no types, so this compiles the way it did before
    # any library could describe one.
    compiled = result(running(TYPED, "value = gadget.ping(1.5)"))

    assert "int value = gadget.ping(1.5);" in compiled.cpp


def test_a_method_without_declared_types_still_rejects_too_many_arguments(error, typed_library):
    error(running(TYPED, "gadget.ping(1, 2)"), message="Gadget.ping() takes 0 to 1 arguments but 2 were given.")


@pytest.mark.parametrize("call", ["servo.attach(9)", "servo.write(90)", "servo.read()", "servo.write(90.5)"])
def test_servo_still_takes_the_arguments_it_always_took(result, call):
    # Servo describes no argument types, so all it ever checked is its arity.
    compiled = result(running(SERVO, call))

    assert f"{call};" in compiled.cpp


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


# ------------------------------------------------------------------- structs
STRUCT_SHELL = """
class Point:
    x: int
    y: float
{extra}
def main():
    pass

def loop():
    pass
"""


def test_a_class_of_fields_is_a_struct(result):
    compiled = result(STRUCT_SHELL.format(extra=""))
    point = compiled.context.classes["Point"]
    assert point.is_struct is True
    assert list(point.fields) == ["x", "y"]
    assert point.fields["x"].cpp_type == "int"
    assert point.fields["y"].cpp_type == "float"
    assert point.methods == {}


def test_a_class_with_methods_is_not_a_struct(result):
    compiled = result(CLASS_SHELL.format(extra=""))
    assert compiled.context.classes["Led"].is_struct is False


def test_a_struct_field_may_hold_another_struct(result):
    compiled = result(
        """
        class Point:
            x: int

        class Waypoint:
            point: Point
            name: str

        def main():
            pass

        def loop():
            pass
        """
    )
    assert compiled.context.classes["Waypoint"].fields["point"].cpp_type == "Point"
    assert compiled.context.classes["Waypoint"].fields["name"].cpp_type == "String"


def test_a_struct_is_a_known_object_type(result):
    compiled = result(
        """
        class Point:
            x: int

        def main():
            point = Point()
            point.x = 3

        def loop():
            pass
        """
    )
    assert compiled.context.is_object_type("Point")
    assert compiled.context.setup_info.locals["point"].cpp_type == "Point"


def test_a_struct_field_with_a_value_is_rejected(error):
    error(
        STRUCT_SHELL.format(extra="").replace("    x: int\n", "    x: int = 5\n"),
        message="A struct field cannot have a value.",
    )


def test_a_struct_field_annotated_as_none_is_rejected(error):
    error(
        STRUCT_SHELL.format(extra="").replace("    x: int\n", "    x: None\n"),
        message="'None' is not a valid field type.",
    )


def test_a_duplicate_struct_field_is_rejected(error):
    error(
        STRUCT_SHELL.format(extra="").replace("    x: int\n", "    x: int\n    x: float\n"),
        message="Struct field 'x' is declared more than once.",
    )


def test_a_struct_field_that_is_not_a_simple_name_is_rejected(error):
    error(
        STRUCT_SHELL.format(extra="").replace("    x: int\n", "    self.x: int\n"),
        message="Only a simple name can be declared as a struct field.",
    )


def test_a_struct_field_named_after_an_arduino_name_is_rejected(error):
    error(
        STRUCT_SHELL.format(extra="").replace("    x: int\n", "    HIGH: int\n"),
        message="'HIGH' is used by the Arduino core and cannot be a variable name.",
    )


def test_a_struct_cannot_be_created_with_arguments(error):
    error(
        """
        class Point:
            x: int

        def main():
            point = Point(1, 2)

        def loop():
            pass
        """,
        message="Struct 'Point' cannot be created with arguments.",
        hint="point = Point()",
    )


def test_a_class_attribute_next_to_a_method_is_still_rejected(error):
    error(
        CLASS_SHELL.format(extra="").replace("    def on(self):", "    shared: int\n\n    def on(self):"),
        message="Class attributes are not supported.",
    )


def test_a_list_of_struct_objects_keeps_the_element_type(result):
    compiled = result(
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
    readings = compiled.context.globals["readings"]
    assert readings.cpp_type == "Reading"
    assert readings.is_array is True
    assert readings.array_len == 2
    assert compiled.context.is_struct_type(readings.cpp_type)


def test_a_local_list_of_struct_objects_keeps_the_element_type(result):
    compiled = result(
        """
        class Reading:
            value: int

        def main():
            readings = [Reading(), Reading()]

        def loop():
            pass
        """
    )
    readings = compiled.context.setup_info.locals["readings"]
    assert readings.cpp_type == "Reading"
    assert readings.is_array is True
    assert readings.array_len == 2


def test_a_list_of_structs_with_nested_struct_fields_keeps_the_element_type(result):
    compiled = result(
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
    samples = compiled.context.globals["samples"]
    assert samples.cpp_type == "Sample"
    assert samples.array_len == 2
    assert compiled.context.classes["Sample"].fields["first"].cpp_type == "Reading"


def test_a_list_of_class_objects_is_rejected(error):
    error(
        """
        class Led:
            def __init__(self, pin: int):
                self.pin = pin

        def main():
            leds = [Led(13), Led(7)]

        def loop():
            pass
        """,
        message="Lists of class objects are not supported on Arduino.",
        hint="Use a struct: a class with fields and no methods.",
    )


def test_a_list_of_library_objects_is_rejected(error):
    error(
        "from controllerpy import Servo\n\ndef main():\n    servos = [Servo(), Servo()]\n\ndef loop():\n    pass\n",
        message="Lists of class objects are not supported on Arduino.",
    )


def test_a_list_of_two_different_struct_types_is_rejected(error):
    error(
        """
        class Point:
            x: int

        class Waypoint:
            point: Point

        def main():
            places = [Point(), Waypoint()]

        def loop():
            pass
        """,
        message="All elements of a list must have the same type.",
    )


def test_a_list_mixing_a_struct_and_an_int_is_rejected(error):
    error(
        """
        class Point:
            x: int

        def main():
            places = [Point(), 3]

        def loop():
            pass
        """,
        message="All elements of a list must have the same type.",
    )


STRUCT_ARRAY_SHELL = """
class Reading:
    value: int
    bright: bool

readings = [
    Reading(),
    Reading(),
]

def main():
    {line}

def loop():
    pass
"""


def test_reading_a_struct_array_element_is_a_struct(result):
    compiled = result(STRUCT_ARRAY_SHELL.format(line="value = readings[0]"))
    assert compiled.context.setup_info.locals["value"].cpp_type == "Reading"


def test_reading_an_int_field_through_an_index_is_an_int(result):
    compiled = result(STRUCT_ARRAY_SHELL.format(line="value = readings[0].value"))
    assert compiled.context.setup_info.locals["value"].cpp_type == "int"


def test_reading_a_bool_field_through_an_index_is_a_bool(result):
    compiled = result(STRUCT_ARRAY_SHELL.format(line="bright = readings[0].bright"))
    assert compiled.context.setup_info.locals["bright"].cpp_type == "bool"


def test_writing_fields_through_an_index_is_accepted(result):
    compiled = result(
        STRUCT_ARRAY_SHELL.format(line="readings[0].value = 123\n    readings[0].bright = True")
    )
    assert compiled.context.classes["Reading"].fields["value"].cpp_type == "int"
    assert compiled.context.classes["Reading"].fields["bright"].cpp_type == "bool"


def test_a_struct_element_can_be_passed_to_a_function(result):
    compiled = result(
        STRUCT_ARRAY_SHELL.format(line="value = brightness(readings[1])")
        + "\ndef brightness(reading: Reading) -> bool:\n    return reading.bright\n"
    )
    assert compiled.context.setup_info.locals["value"].cpp_type == "bool"


def test_writing_a_wrong_type_through_an_index_is_rejected(error):
    error(
        STRUCT_ARRAY_SHELL.format(line="readings[0].value = 'text'"),
        message="'value' is assigned values of incompatible types.",
    )


def test_a_float_index_into_a_struct_array_is_rejected(error):
    error(
        STRUCT_ARRAY_SHELL.format(line="value = readings[1.5].value"),
        message="Array indices must be integers.",
    )


def test_reading_an_unknown_field_through_an_index_is_rejected(error):
    error(
        STRUCT_ARRAY_SHELL.format(line="value = readings[0].missing"),
        message="Class 'Reading' has no attribute 'missing'.",
    )


def test_indexing_a_struct_element_is_rejected(error):
    error(
        STRUCT_ARRAY_SHELL.format(line="value = readings[0][0]"),
        message="Only arrays can be indexed.",
    )


def test_reading_a_nested_struct_field_through_an_index(result):
    compiled = result(
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
    assert compiled.context.setup_info.locals["value"].cpp_type == "int"


def test_a_new_struct_can_be_assigned_to_an_array_element(result):
    compiled = result(STRUCT_ARRAY_SHELL.format(line="readings[0] = Reading()"))
    readings = compiled.context.globals["readings"]
    assert readings.cpp_type == "Reading"
    assert readings.is_array is True


def test_a_struct_variable_can_be_assigned_to_an_array_element(result):
    compiled = result(
        STRUCT_ARRAY_SHELL.format(line="reading = Reading()\n    readings[0] = reading")
    )
    assert compiled.context.setup_info.locals["reading"].cpp_type == "Reading"


def test_an_int_assigned_to_a_struct_array_element_is_rejected(error):
    error(
        STRUCT_ARRAY_SHELL.format(line="readings[0] = 123"),
        message="Array 'readings' holds Reading values, not int.",
    )


def test_another_struct_assigned_to_a_struct_array_element_is_rejected(error):
    error(
        STRUCT_ARRAY_SHELL.format(line="readings[0] = Note()")
        + "\nclass Note:\n    text: str\n",
        message="Array 'readings' holds Reading values, not Note.",
    )


def test_an_int_assigned_to_a_nested_struct_array_element_is_rejected(error):
    error(
        """
        class Reading:
            value: int

        class Sample:
            first: Reading

        samples = [Sample(), Sample()]

        def main():
            samples[0] = 7

        def loop():
            pass
        """,
        message="Array 'samples' holds Sample values, not int.",
    )


def test_a_struct_assigned_to_a_scalar_array_element_is_rejected(error):
    error(
        """
        class Reading:
            value: int

        def main():
            values = [1, 2, 3]
            values[0] = Reading()

        def loop():
            pass
        """,
        message="Array 'values' holds int values, not Reading.",
    )


APPEND_SHELL = """
class Reading:
    value: int
    bright: bool

class Sample:
    first: Reading

readings = []
"""


def test_an_appended_struct_fills_an_empty_list(result):
    compiled = result(APPEND_SHELL + "def main():\n    readings.append(Reading())\n\ndef loop():\n    pass\n")
    readings = compiled.context.globals["readings"]
    assert readings.cpp_type == "Reading"
    assert readings.is_array is True
    assert readings.array_len == 0
    assert readings.append_count == 1


def test_every_append_is_counted(result):
    compiled = result(
        APPEND_SHELL
        + "def main():\n    readings.append(Reading())\n    readings.append(Reading())\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.globals["readings"].append_count == 2


def test_a_struct_variable_can_be_appended(result):
    compiled = result(
        APPEND_SHELL + "def main():\n    reading = Reading()\n    readings.append(reading)\n\ndef loop():\n    pass\n"
    )
    readings = compiled.context.globals["readings"]
    assert readings.cpp_type == "Reading"
    assert compiled.context.setup_info.locals["reading"].cpp_type == "Reading"


def test_a_local_list_can_be_appended_to(result):
    compiled = result(
        """
        class Reading:
            value: int

        def main():
            readings = []
            readings.append(Reading())

        def loop():
            pass
        """
    )
    readings = compiled.context.setup_info.locals["readings"]
    assert readings.cpp_type == "Reading"
    assert readings.array_len == 0
    assert readings.append_count == 1


def test_a_struct_with_a_struct_field_can_be_appended(result):
    compiled = result(
        """
        class Reading:
            value: int

        class Sample:
            first: Reading

        samples = []

        def main():
            samples.append(Sample())

        def loop():
            pass
        """
    )
    assert compiled.context.globals["samples"].cpp_type == "Sample"


def test_len_of_an_appended_list_is_an_int(result):
    compiled = result(
        APPEND_SHELL
        + "def main():\n    readings.append(Reading())\n    size = len(readings)\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["size"].cpp_type == "int"


def test_an_empty_list_without_an_append_is_rejected(error):
    error(
        "readings = []\n\ndef main():\n    pass\n\ndef loop():\n    pass\n",
        message="Empty lists are not supported.",
        hint="Give the array at least one element.",
    )


def test_a_primitive_appended_to_a_struct_list_is_rejected(error):
    error(
        APPEND_SHELL + "def main():\n    readings.append(Reading())\n    readings.append(123)\n\ndef loop():\n    pass\n",
        message="List 'readings' holds Reading values, not int.",
    )


def test_another_struct_appended_to_a_struct_list_is_rejected(error):
    error(
        APPEND_SHELL + "def main():\n    readings.append(Reading())\n    readings.append(Sample())\n\ndef loop():\n    pass\n",
        message="List 'readings' holds Reading values, not Sample.",
    )


def test_append_to_a_value_that_is_not_a_list_is_rejected(error):
    error(
        """
        class Reading:
            value: int

        def main():
            value = 1
            value.append(Reading())

        def loop():
            pass
        """,
        message="'value' is not a list, so it cannot be appended to.",
    )


def test_append_without_a_value_is_rejected(error):
    error(
        APPEND_SHELL + "def main():\n    readings.append()\n\ndef loop():\n    pass\n",
        message="append() takes exactly 1 argument but 0 were given.",
    )


def test_the_result_of_append_cannot_be_used(error):
    error(
        APPEND_SHELL + "def main():\n    size = readings.append(Reading())\n\ndef loop():\n    pass\n",
        message="append() has to be used as a statement.",
        hint="readings.append(Reading())",
    )


def test_a_list_declared_inside_a_block_cannot_be_appended_to(error):
    error(
        """
        class Reading:
            value: int

        def main():
            if True:
                readings = []
            readings.append(Reading())

        def loop():
            pass
        """,
        message="Array 'readings' must get its values where it is declared.",
    )


APPEND_FLOW = "append() cannot be used in runtime control flow because the list capacity is set at compile time."
APPEND_OUTSIDE = "append() can only be used in main() because the list capacity is set at compile time."


def test_append_in_straight_line_main_is_accepted(result):
    compiled = result(
        APPEND_SHELL
        + "def main():\n    readings.append(Reading())\n    readings.append(Reading())\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.globals["readings"].append_count == 2


def test_append_in_main_around_control_flow_is_accepted(result):
    compiled = result(
        APPEND_SHELL
        + "def main():\n"
        "    readings.append(Reading())\n"
        "    on = True\n"
        "    if on:\n"
        "        on = False\n"
        "    readings.append(Reading())\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.globals["readings"].append_count == 2


def test_append_in_loop_is_rejected(error):
    error(
        APPEND_SHELL + "def main():\n    pass\n\ndef loop():\n    readings.append(Reading())\n",
        message=APPEND_OUTSIDE,
        hint="Move the append() calls into main().",
    )


def test_append_in_an_if_is_rejected(error):
    error(
        APPEND_SHELL + "def main():\n    if True:\n        readings.append(Reading())\n\ndef loop():\n    pass\n",
        message=APPEND_FLOW,
        hint="Call append() once for every value in main().",
    )


def test_append_in_an_elif_is_rejected(error):
    error(
        APPEND_SHELL
        + "def main():\n    if True:\n        pass\n    elif False:\n        readings.append(Reading())\n\ndef loop():\n    pass\n",
        message=APPEND_FLOW,
    )


def test_append_in_an_else_is_rejected(error):
    error(
        APPEND_SHELL + "def main():\n    if True:\n        pass\n    else:\n        readings.append(Reading())\n\ndef loop():\n    pass\n",
        message=APPEND_FLOW,
    )


def test_append_in_a_while_is_rejected(error):
    error(
        APPEND_SHELL
        + "def main():\n    while False:\n        readings.append(Reading())\n\ndef loop():\n    pass\n",
        message=APPEND_FLOW,
    )


def test_append_in_a_for_is_rejected(error):
    error(
        APPEND_SHELL + "def main():\n    for i in range(3):\n        readings.append(Reading())\n\ndef loop():\n    pass\n",
        message=APPEND_FLOW,
    )


def test_append_in_nested_runtime_flow_is_rejected(error):
    error(
        APPEND_SHELL
        + "def main():\n    for i in range(3):\n        while False:\n            readings.append(Reading())\n\ndef loop():\n    pass\n",
        message=APPEND_FLOW,
    )


def test_append_in_a_function_is_rejected(error):
    error(
        APPEND_SHELL
        + "def store():\n    readings.append(Reading())\n\ndef main():\n    store()\n\ndef loop():\n    pass\n",
        message=APPEND_OUTSIDE,
    )


def test_append_in_a_method_is_rejected(error):
    error(
        APPEND_SHELL
        + "class Sensor:\n    def store(self):\n        readings.append(Reading())\n\ndef main():\n    sensor = Sensor()\n\ndef loop():\n    pass\n",
        message=APPEND_OUTSIDE,
    )


POP_SHELL = """
class Reading:
    value: int
    bright: bool

class Sample:
    first: Reading

readings = [Reading(), Reading()]
"""
POP_FLOW = "pop() cannot be used in runtime control flow because the list length changes at compile time."
POP_OUTSIDE = "pop() can only be used in main() because the list length changes at compile time."


def test_pop_used_as_a_statement_is_accepted(result):
    compiled = result(POP_SHELL + "def main():\n    readings.pop()\n\ndef loop():\n    pass\n")
    assert compiled.context.globals["readings"].pop_count == 1


def test_a_popped_value_has_the_element_type(result):
    compiled = result(POP_SHELL + "def main():\n    reading = readings.pop()\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["reading"].cpp_type == "Reading"


def test_a_popped_struct_can_be_read_afterwards(result):
    compiled = result(
        POP_SHELL + "def main():\n    reading = readings.pop()\n    value = reading.value\n    bright = reading.bright\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["value"].cpp_type == "int"
    assert compiled.context.setup_info.locals["bright"].cpp_type == "bool"


def test_a_popped_struct_field_is_checked(error):
    error(
        POP_SHELL + "def main():\n    reading = readings.pop()\n    value = reading.missing\n\ndef loop():\n    pass\n",
        message="Class 'Reading' has no attribute 'missing'.",
    )


def test_a_popped_nested_struct_keeps_its_type(result):
    compiled = result(
        """
        class Reading:
            value: int

        class Sample:
            first: Reading

        samples = [Sample(), Sample()]

        def main():
            sample = samples.pop()
            first = sample.first

        def loop():
            pass
        """
    )
    assert compiled.context.setup_info.locals["sample"].cpp_type == "Sample"
    assert compiled.context.setup_info.locals["first"].cpp_type == "Reading"


def test_every_pop_is_counted(result):
    compiled = result(POP_SHELL + "def main():\n    readings.pop()\n    readings.pop()\n\ndef loop():\n    pass\n")
    assert compiled.context.globals["readings"].pop_count == 2


def test_pop_after_an_append_is_accepted(result):
    compiled = result(
        """
        class Reading:
            value: int

        readings = []

        def main():
            readings.append(Reading())
            reading = readings.pop()

        def loop():
            pass
        """
    )
    assert compiled.context.setup_info.locals["reading"].cpp_type == "Reading"
    assert compiled.context.globals["readings"].pop_count == 1


def test_a_local_list_can_be_popped_from(result):
    compiled = result(
        """
        class Reading:
            value: int

        def main():
            readings = [Reading(), Reading()]
            size = len(readings)
            reading = readings.pop()

        def loop():
            pass
        """
    )
    readings = compiled.context.setup_info.locals["readings"]
    assert readings.pop_count == 1
    assert compiled.context.setup_info.locals["reading"].cpp_type == "Reading"
    assert compiled.context.setup_info.locals["size"].cpp_type == "int"


def test_pop_from_an_empty_list_is_rejected(error):
    error(
        "readings = []\n\ndef main():\n    readings.pop()\n\ndef loop():\n    pass\n",
        message="pop() cannot remove a value because 'readings' may be empty.",
        hint="Append a value before popping one.",
    )


def test_pop_before_an_append_is_rejected(error):
    error(
        """
        class Reading:
            value: int

        readings = []

        def main():
            readings.pop()
            readings.append(Reading())

        def loop():
            pass
        """,
        message="pop() cannot remove a value because 'readings' may be empty.",
    )


def test_more_pops_than_values_are_rejected(error):
    error(
        POP_SHELL + "def main():\n    readings.pop()\n    readings.pop()\n    readings.pop()\n\ndef loop():\n    pass\n",
        message="pop() cannot remove a value because 'readings' may be empty.",
    )


def test_pop_with_an_argument_is_rejected(error):
    error(
        POP_SHELL + "def main():\n    readings.pop(0)\n\ndef loop():\n    pass\n",
        message="pop() takes exactly 0 arguments but 1 was given.",
    )


def test_pop_from_a_value_that_is_not_a_list_is_rejected(error):
    error(
        "def main():\n    value = 1\n    value.pop()\n\ndef loop():\n    pass\n",
        message="'value' is not a list, so no value can be popped from it.",
    )


def test_pop_in_loop_is_rejected(error):
    error(
        POP_SHELL + "def main():\n    pass\n\ndef loop():\n    readings.pop()\n",
        message=POP_OUTSIDE,
        hint="Move the pop() calls into main().",
    )


def test_pop_in_runtime_control_flow_is_rejected(error):
    error(
        POP_SHELL
        + "def main():\n    for i in range(3):\n        if True:\n            readings.pop()\n\ndef loop():\n    pass\n",
        message=POP_FLOW,
        hint="Call pop() once for every value in main().",
    )


INSERT_FLOW = "insert() cannot be used in runtime control flow because the list length changes at compile time."
INSERT_OUTSIDE = "insert() can only be used in main() because the list length changes at compile time."
INSERT_RANGE = "The index for insert() must be between 0 and 2."


def test_a_value_can_be_inserted_into_a_struct_list(result):
    compiled = result(POP_SHELL + "def main():\n    readings.insert(0, Reading())\n\ndef loop():\n    pass\n")
    assert compiled.context.globals["readings"].insert_count == 1
    assert compiled.context.globals["readings"].cpp_type == "Reading"


def test_a_struct_variable_can_be_inserted(result):
    compiled = result(
        POP_SHELL + "def main():\n    reading = Reading()\n    readings.insert(1, reading)\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.globals["readings"].insert_count == 1
    assert compiled.context.setup_info.locals["reading"].cpp_type == "Reading"


def test_an_incompatible_primitive_cannot_be_inserted(error):
    error(
        POP_SHELL + "def main():\n    readings.insert(0, 123)\n\ndef loop():\n    pass\n",
        message="List 'readings' holds Reading values, not int.",
    )


def test_another_struct_cannot_be_inserted(error):
    error(
        POP_SHELL + "def main():\n    readings.insert(0, Sample())\n\ndef loop():\n    pass\n",
        message="List 'readings' holds Reading values, not Sample.",
    )


def test_a_non_integer_insert_index_is_rejected(error):
    error(
        POP_SHELL + "def main():\n    readings.insert('first', Reading())\n\ndef loop():\n    pass\n",
        message="The index passed to insert() must be an integer.",
    )


def test_a_negative_insert_index_is_rejected(error):
    error(
        POP_SHELL + "def main():\n    readings.insert(-1, Reading())\n\ndef loop():\n    pass\n",
        message=INSERT_RANGE,
        hint="Values are shifted right, so the index cannot be past the end of the list.",
    )


def test_an_insert_index_past_the_end_is_rejected(error):
    error(
        POP_SHELL + "def main():\n    readings.insert(3, Reading())\n\ndef loop():\n    pass\n",
        message=INSERT_RANGE,
    )


def test_an_insert_index_that_is_not_constant_is_rejected(error):
    error(
        POP_SHELL
        + "def main():\n    where = 1\n    readings.insert(where, Reading())\n\ndef loop():\n    pass\n",
        message="The index passed to insert() must be a constant integer.",
        hint="The list length is known at compile time, so insert() needs a fixed index.",
    )


def test_insert_into_an_empty_list_is_accepted(result):
    compiled = result(
        """
        class Reading:
            value: int

        readings = []

        def main():
            readings.insert(0, Reading())
            reading = readings.pop()

        def loop():
            pass
        """
    )
    assert compiled.context.globals["readings"].insert_count == 1
    assert compiled.context.setup_info.locals["reading"].cpp_type == "Reading"


def test_insert_after_an_append_is_accepted(result):
    compiled = result(
        """
        class Reading:
            value: int

        readings = []

        def main():
            readings.append(Reading())
            readings.insert(1, Reading())

        def loop():
            pass
        """
    )
    assert compiled.context.globals["readings"].insert_count == 1
    assert compiled.context.globals["readings"].append_count == 1


def test_insert_after_a_pop_is_accepted(result):
    compiled = result(POP_SHELL + "def main():\n    readings.pop()\n    readings.insert(1, Reading())\n\ndef loop():\n    pass\n")
    assert compiled.context.globals["readings"].pop_count == 1
    assert compiled.context.globals["readings"].insert_count == 1


def test_more_pops_than_values_after_inserts_are_rejected(error):
    error(
        POP_SHELL
        + "def main():\n    readings.insert(0, Reading())\n    readings.pop()\n    readings.pop()\n    readings.pop()\n    readings.pop()\n\ndef loop():\n    pass\n",
        message="pop() cannot remove a value because 'readings' may be empty.",
    )


def test_every_insert_is_counted(result):
    compiled = result(
        POP_SHELL
        + "def main():\n    readings.insert(0, Reading())\n    readings.insert(2, Reading())\n    readings.insert(4, Reading())\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.globals["readings"].insert_count == 3


def test_a_local_list_can_be_inserted_into(result):
    compiled = result(
        """
        class Reading:
            value: int

        def main():
            readings = [Reading(), Reading()]
            readings.insert(0, Reading())
            size = len(readings)

        def loop():
            pass
        """
    )
    readings = compiled.context.setup_info.locals["readings"]
    assert readings.insert_count == 1
    assert compiled.context.setup_info.locals["size"].cpp_type == "int"


def test_a_struct_with_a_struct_field_can_be_inserted(result):
    compiled = result(
        """
        class Reading:
            value: int

        class Sample:
            first: Reading

        samples = [Sample()]

        def main():
            samples.insert(0, Sample())
            sample = samples.pop()
            first = sample.first

        def loop():
            pass
        """
    )
    assert compiled.context.globals["samples"].insert_count == 1
    assert compiled.context.setup_info.locals["sample"].cpp_type == "Sample"
    assert compiled.context.setup_info.locals["first"].cpp_type == "Reading"


def test_insert_needs_an_index_and_a_value(error):
    error(
        POP_SHELL + "def main():\n    readings.insert(0)\n\ndef loop():\n    pass\n",
        message="insert() takes exactly 2 arguments but 1 was given.",
    )


def test_insert_into_a_value_that_is_not_a_list_is_rejected(error):
    error(
        "def main():\n    value = 1\n    value.insert(0, 2)\n\ndef loop():\n    pass\n",
        message="'value' is not a list, so nothing can be inserted into it.",
    )


def test_the_result_of_insert_cannot_be_used(error):
    error(
        POP_SHELL + "def main():\n    size = readings.insert(0, Reading())\n\ndef loop():\n    pass\n",
        message="insert() has to be used as a statement.",
        hint="readings.insert(0, Reading())",
    )


def test_insert_in_loop_is_rejected(error):
    error(
        POP_SHELL + "def main():\n    pass\n\ndef loop():\n    readings.insert(0, Reading())\n",
        message=INSERT_OUTSIDE,
        hint="Move the insert() calls into main().",
    )


def test_insert_in_runtime_control_flow_is_rejected(error):
    error(
        POP_SHELL
        + "def main():\n    for i in range(3):\n        readings.insert(0, Reading())\n\ndef loop():\n    pass\n",
        message=INSERT_FLOW,
        hint="Call insert() once for every value in main().",
    )


CLEAR_FLOW = "clear() cannot be used in runtime control flow because the list length changes at compile time."
CLEAR_OUTSIDE = "clear() can only be used in main() because the list length changes at compile time."


def test_a_list_can_be_cleared(result):
    compiled = result(POP_SHELL + "def main():\n    readings.clear()\n\ndef loop():\n    pass\n")
    assert compiled.context.globals["readings"].clear_growth == 0
    assert compiled.context.globals["readings"].has_count


def test_a_list_of_structs_can_be_cleared(result):
    compiled = result(POP_SHELL + "def main():\n    readings.clear()\n    size = len(readings)\n\ndef loop():\n    pass\n")
    assert compiled.context.globals["readings"].array_len == 2
    assert compiled.context.globals["readings"].guaranteed_count == 0


def test_a_local_list_can_be_cleared(result):
    compiled = result(
        "def main():\n    readings = [1, 2, 3]\n    readings.clear()\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["readings"].clear_growth == 0


def test_clearing_an_empty_list_is_accepted(result):
    compiled = result(
        """
        class Reading:
            value: int

        readings = []

        def main():
            readings.append(Reading())
            readings.clear()

        def loop():
            pass
        """
    )
    assert compiled.context.globals["readings"].append_count == 1
    assert compiled.context.globals["readings"].guaranteed_count == 0


def test_clearing_after_an_append_is_accepted(result):
    compiled = result(POP_SHELL + "def main():\n    readings.append(Reading())\n    readings.clear()\n\ndef loop():\n    pass\n")
    assert compiled.context.globals["readings"].append_count == 1
    assert compiled.context.globals["readings"].guaranteed_count == 0


def test_clearing_after_an_insert_is_accepted(result):
    compiled = result(POP_SHELL + "def main():\n    readings.insert(0, Reading())\n    readings.clear()\n\ndef loop():\n    pass\n")
    assert compiled.context.globals["readings"].insert_count == 1
    assert compiled.context.globals["readings"].guaranteed_count == 0


def test_clearing_after_a_pop_is_accepted(result):
    compiled = result(POP_SHELL + "def main():\n    readings.pop()\n    readings.clear()\n\ndef loop():\n    pass\n")
    assert compiled.context.globals["readings"].pop_count == 1
    assert compiled.context.globals["readings"].guaranteed_count == 0


def test_more_clears_are_allowed(result):
    compiled = result(
        POP_SHELL + "def main():\n    readings.clear()\n    readings.clear()\n    readings.append(Reading())\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.globals["readings"].guaranteed_count == 1


def test_a_pop_after_a_clear_is_rejected(error):
    error(
        POP_SHELL + "def main():\n    readings.clear()\n    readings.pop()\n\ndef loop():\n    pass\n",
        message="pop() cannot remove a value because 'readings' may be empty.",
        hint="Append a value before popping one.",
    )


def test_an_append_after_a_clear_can_be_popped(result):
    compiled = result(
        POP_SHELL + "def main():\n    readings.clear()\n    readings.append(Reading())\n    reading = readings.pop()\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["reading"].cpp_type == "Reading"
    assert compiled.context.globals["readings"].guaranteed_count == 0


def test_a_second_pop_after_an_append_and_a_clear_is_rejected(error):
    error(
        POP_SHELL
        + "def main():\n    readings.clear()\n    readings.append(Reading())\n    readings.pop()\n    readings.pop()\n\ndef loop():\n    pass\n",
        message="pop() cannot remove a value because 'readings' may be empty.",
    )


def test_an_insert_after_a_clear_is_accepted(result):
    compiled = result(
        POP_SHELL + "def main():\n    readings.clear()\n    readings.insert(0, Reading())\n    reading = readings.pop()\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.globals["readings"].insert_count == 1
    assert compiled.context.setup_info.locals["reading"].cpp_type == "Reading"


def test_an_insert_after_a_clear_past_the_end_is_rejected(error):
    error(
        POP_SHELL + "def main():\n    readings.clear()\n    readings.insert(1, Reading())\n\ndef loop():\n    pass\n",
        message="The index for insert() must be between 0 and 0.",
    )


def test_clear_takes_no_arguments(error):
    error(
        POP_SHELL + "def main():\n    readings.clear(0)\n\ndef loop():\n    pass\n",
        message="clear() takes exactly 0 arguments but 1 was given.",
    )


def test_clear_on_a_value_that_is_not_a_list_is_rejected(error):
    error(
        "def main():\n    count = 5\n    count.clear()\n\ndef loop():\n    pass\n",
        message="'count' is not a list, so it cannot be cleared.",
    )


def test_clear_used_as_a_value_is_rejected(error):
    error(
        POP_SHELL + "def main():\n    size = readings.clear()\n\ndef loop():\n    pass\n",
        message="clear() has to be used as a statement.",
        hint="readings.clear()",
    )


def test_clear_in_loop_is_rejected(error):
    error(
        POP_SHELL + "def main():\n    pass\n\ndef loop():\n    readings.clear()\n",
        message=CLEAR_OUTSIDE,
        hint="Move the clear() calls into main().",
    )


def test_clear_in_runtime_control_flow_is_rejected(error):
    error(
        POP_SHELL
        + "def main():\n    for i in range(3):\n        if True:\n            readings.clear()\n\ndef loop():\n    pass\n",
        message=CLEAR_FLOW,
        hint="Call clear() once for every time you need to reset the list in main().",
    )


def test_clear_in_a_helper_function_is_rejected(error):
    error(
        POP_SHELL + "def reset():\n    readings.clear()\n\ndef main():\n    pass\n\ndef loop():\n    pass\n",
        message=CLEAR_OUTSIDE,
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

    A type such as ``long`` is understood by C++ but not by controllerpy's type
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
        "def main():\n    text = 'a' - 'b'\n\ndef loop():\n    pass\n",
        message="Only '+' can be used to build a string.",
        hint="str()",
    )


def test_string_multiplication_is_rejected(error):
    error(
        "def main():\n    text = 'a' * 3\n\ndef loop():\n    pass\n",
        message="Only '+' can be used to build a string.",
        hint="str()",
    )


def test_adding_a_struct_to_a_string_is_rejected(error):
    error(
        """
        class Reading:
            value: int

        def main():
            label: str = 'hi'
            reading = Reading()
            text = label + reading

        def loop():
            pass
        """,
        message="Operators cannot be used with objects of type 'Reading'.",
    )


def test_adding_two_literals_is_string_concatenation(result):
    compiled = result("def main():\n    text = 'a' + 'b'\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_adding_a_string_and_a_string_is_accepted(result):
    compiled = result("def main():\n    label: str = 'hi'\n    text = label + '!'\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_adding_a_literal_and_a_string_is_accepted(result):
    compiled = result("def main():\n    label: str = 'hi'\n    text = 'hi ' + label\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_adding_a_string_and_an_int_is_accepted(result):
    compiled = result("def main():\n    label: str = 'hi'\n    text = label + 7\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_adding_a_string_and_a_float_is_accepted(result):
    compiled = result("def main():\n    label: str = 'hi'\n    text = label + 1.5\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_adding_a_string_and_a_bool_is_accepted(result):
    compiled = result("def main():\n    label: str = 'hi'\n    text = label + True\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_adding_an_int_and_a_string_is_accepted(result):
    compiled = result("def main():\n    label: str = 'hi'\n    text = 7 + label\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_adding_a_float_and_a_string_is_accepted(result):
    compiled = result("def main():\n    label: str = 'hi'\n    text = 1.5 + label\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_adding_a_bool_and_a_string_is_accepted(result):
    compiled = result("def main():\n    label: str = 'hi'\n    text = True + label\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_chained_string_concatenation_is_accepted(result):
    compiled = result("def main():\n    text = 'a' + str(1) + 'b' + str(2)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_concatenation_can_be_printed(result):
    compiled = result(
        "def main():\n    serial_print('value: ' + str(42))\n    serial_println('value: ' + str(42))\n\ndef loop():\n    pass\n"
    )
    assert 'Serial.print(String("value: ") + String(42));' in compiled.cpp
    assert 'Serial.println(String("value: ") + String(42));' in compiled.cpp


def test_concatenation_can_be_returned(result):
    compiled = result(
        """
        def label_for(level: int) -> str:
            return 'level=' + str(level)

        def main():
            text = label_for(3)

        def loop():
            pass
        """
    )
    assert compiled.context.functions["label_for"].return_type == "String"
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_concatenation_fills_a_struct_string_field(result):
    compiled = result(
        """
        class Reading:
            label: str
            level: int

        def main():
            reading = Reading()
            reading.label = 'L' + str(reading.level)

        def loop():
            pass
        """
    )
    assert compiled.context.classes["Reading"].fields["label"].cpp_type == "String"


def test_concatenation_in_a_global_initializer_is_accepted(result):
    compiled = result("banner = 'ready: ' + str(3)\n" + SHELL)
    assert compiled.context.globals["banner"].cpp_type == "String"


def test_numeric_addition_stays_numeric(result):
    compiled = result(
        "def main():\n    total = 10 + 20\n    ratio = 1.5 + 2.5\n    step = total + 1\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["total"].cpp_type == "int"
    assert compiled.context.setup_info.locals["ratio"].cpp_type == "float"
    assert compiled.context.setup_info.locals["step"].cpp_type == "int"


def test_bool_concatenation_still_uses_the_python_spelling(result):
    compiled = result("def main():\n    text = str(True) + '!'\n\ndef loop():\n    pass\n")
    assert 'String(true ? "True" : "False") + String("!")' in compiled.cpp


def test_concatenation_inside_runtime_control_flow_is_accepted(result):
    compiled = result(
        "def main():\n    count = 0\n    while count < 3:\n        serial_println('n=' + str(count))\n        count += 1\n\ndef loop():\n    pass\n"
    )
    assert 'Serial.println(String("n=") + String(count));' in compiled.cpp


def test_concatenation_cannot_be_used_as_a_condition_only_by_mistake(result):
    compiled = result("def main():\n    text = 'a' + str(1)\n    other = 'b' + str(2)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"
    assert compiled.context.setup_info.locals["other"].cpp_type == "String"


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


def test_augmented_assignment_on_a_string_is_allowed(program):
    cpp = program(
        """
        def main():
            text = 'a'
            text += 'b'

        def loop():
            pass
        """
    )
    assert "String text = \"a\";" in cpp
    assert "text += \"b\";" in cpp


def test_unsupported_augmented_assignment_is_rejected(error):
    error(
        "def main():\n    value = 2\n    value @= 2\n\ndef loop():\n    pass\n",
        message="Unsupported augmented assignment: MatMult",
    )


def test_str_of_an_int_is_the_string_type(result):
    compiled = result("counter = 7\n\ndef main():\n    text = str(counter)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_str_of_a_float_is_the_string_type(result):
    compiled = result("def main():\n    text = str(1.5)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_str_of_a_bool_is_the_string_type(result):
    compiled = result("def main():\n    text = str(True)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_str_of_a_string_literal_is_the_string_type(result):
    compiled = result("def main():\n    text = str('hi')\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_str_of_an_annotated_string_is_the_string_type(result):
    compiled = result("def main():\n    label: str = 'hi'\n    text = str(label)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_str_result_can_be_assigned_to_an_annotated_string(result):
    compiled = result("def main():\n    text: str = str(7)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_str_result_can_fill_a_struct_string_field(result):
    compiled = result(
        """
        class Reading:
            label: str
            level: int

        def main():
            reading = Reading()
            reading.label = str(reading.level)

        def loop():
            pass
        """
    )
    assert compiled.context.classes["Reading"].fields["label"].cpp_type == "String"


def test_str_result_can_be_printed(result):
    compiled = result(
        "def main():\n    serial_print(str(7))\n    serial_println(str(True))\n\ndef loop():\n    pass\n"
    )
    assert "Serial.print(String(7));" in compiled.cpp
    assert 'Serial.println(String(true ? "True" : "False"));' in compiled.cpp


def test_str_can_be_nested(result):
    compiled = result("def main():\n    text = str(str(7))\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_str_of_an_api_call_is_accepted(result):
    compiled = result("def main():\n    text = str(analog_read(0))\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_str_in_runtime_control_flow_is_accepted(result):
    compiled = result(
        "def main():\n    count = 0\n    while count < 3:\n        serial_println(str(count))\n        count += 1\n\ndef loop():\n    pass\n"
    )
    assert "Serial.println(String(count));" in compiled.cpp


def test_str_without_arguments_is_rejected(error):
    error(
        "def main():\n    str()\n\ndef loop():\n    pass\n",
        message="str() takes exactly 1 argument but 0 were given.",
    )


def test_str_with_two_arguments_is_rejected(error):
    error(
        "def main():\n    str(1, 2)\n\ndef loop():\n    pass\n",
        message="str() takes exactly 1 argument but 2 were given.",
    )


def test_str_of_a_struct_is_rejected(error):
    error(
        """
        class Reading:
            value: int

        def main():
            reading = Reading()
            text = str(reading)

        def loop():
            pass
        """,
        message="str() cannot convert a Reading value.",
        hint="str() supports int, float, bool, and string values.",
    )


def test_str_of_a_list_is_rejected(error):
    error(
        "def main():\n    values = [1, 2, 3]\n    text = str(values)\n\ndef loop():\n    pass\n",
        message="Array 'values' cannot be used as a value.",
    )


def test_str_of_an_arduino_object_is_rejected(error):
    error(
        "def main():\n    text = str(Serial)\n\ndef loop():\n    pass\n",
        message="str() cannot convert a Serial value.",
        hint="str() supports int, float, bool, and string values.",
    )


def test_str_bare_name_is_rejected(error):
    error(
        "def main():\n    str\n\ndef loop():\n    pass\n",
        message="'str' must be called: str(value)",
    )


def test_len_of_a_string_is_an_int(result):
    compiled = result("text = 'Hello'\n\ndef main():\n    length = len(text)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["length"].cpp_type == "int"


def test_len_of_a_mutated_string_is_an_int(result):
    compiled = result(
        "text = 'Hello'\n\ndef main():\n    text += '!'\n    length = len(text)\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["length"].cpp_type == "int"


def test_len_of_an_annotated_string_is_an_int(result):
    compiled = result("def main():\n    text: str = 'Hello'\n    length = len(text)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["length"].cpp_type == "int"


def test_len_of_a_converted_string_is_an_int(result):
    compiled = result("text = str(7)\n\ndef main():\n    length = len(text)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["length"].cpp_type == "int"


def test_len_of_a_string_turns_a_fixed_string_into_an_arduino_string(result):
    compiled = result("text = 'Hello'\n\ndef main():\n    length = len(text)\n\ndef loop():\n    pass\n")
    assert compiled.context.globals["text"].cpp_type == "String"


def test_len_of_a_list_is_still_an_int(result):
    compiled = result("values = [1, 2, 3]\n\ndef main():\n    size = len(values)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["size"].cpp_type == "int"


def test_len_without_an_argument_is_rejected(error):
    error(
        "def main():\n    size = len()\n\ndef loop():\n    pass\n",
        message="len() takes exactly 1 argument but 0 were given.",
    )


def test_len_of_a_string_expression_is_rejected(error):
    error(
        "def main():\n    text: str = 'Hello'\n    size = len(text + '!')\n\ndef loop():\n    pass\n",
        message="len() is only supported for arrays created from a list literal.",
        hint="len(text)",
    )


def test_replace_turns_a_fixed_string_into_a_mutable_arduino_string(result):
    compiled = result("text = 'Hello World'\n\ndef main():\n    text.replace('World', 'Py')\n\ndef loop():\n    pass\n")
    var = compiled.context.globals["text"]
    assert var.cpp_type == "String"
    assert var.is_const is False


def test_replace_of_a_local_string_is_accepted(result):
    compiled = result("def main():\n    text: str = 'Hello'\n    text.replace('a', 'b')\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_replace_is_allowed_inside_runtime_control_flow(result):
    compiled = result(
        "def main():\n    text = 'Hello'\n    while 1 < 0:\n        text.replace('a', 'b')\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_replace_of_a_struct_field_is_rejected(error):
    error(
        """
        class Box:
            label: str

        def main():
            box = Box()
            box.label.replace('a', 'b')

        def loop():
            pass
        """,
        message="Cannot call method 'replace' on this value.",
    )


def test_replace_with_one_argument_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.replace('World')\n\ndef loop():\n    pass\n",
        message="String.replace() takes exactly 2 arguments but 1 was given.",
    )


def test_replace_with_three_arguments_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.replace('a', 'b', 'c')\n\ndef loop():\n    pass\n",
        message="String.replace() takes exactly 2 arguments but 3 were given.",
    )


def test_replace_of_a_number_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.replace(1, 2)\n\ndef loop():\n    pass\n",
        message="Argument 1 of String.replace() must be String, not int.",
    )


def test_replace_used_as_a_value_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    other = text.replace('a', 'b')\n\ndef loop():\n    pass\n",
        message="replace() has to be used as a statement.",
        hint="String.replace() changes the string in place.",
    )


def test_an_unknown_string_method_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.upppercase()\n\ndef loop():\n    pass\n",
        message="String has no method 'upppercase'.",
        hint="replace()",
    )


def test_substring_turns_a_fixed_string_into_an_arduino_string_without_mutating_it(result):
    compiled = result(
        "text = 'Hello World'\n\ndef main():\n    text.substring(0, 5)\n\ndef loop():\n    pass\n"
    )
    var = compiled.context.globals["text"]
    assert var.cpp_type == "String"
    assert var.is_const is True


def test_substring_of_a_local_string_is_accepted(result):
    compiled = result("def main():\n    text = 'Hello'\n    text.substring(1)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_substring_is_allowed_inside_runtime_control_flow(result):
    compiled = result(
        "def main():\n    text = 'Hello'\n    while 1 < 0:\n        text.substring(0, 2)\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_substring_without_an_argument_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.substring()\n\ndef loop():\n    pass\n",
        message="String.substring() takes 1 to 2 arguments but 0 were given.",
    )


def test_substring_with_three_arguments_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.substring(0, 1, 2)\n\ndef loop():\n    pass\n",
        message="String.substring() takes 1 to 2 arguments but 3 were given.",
    )


def test_substring_of_a_string_index_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.substring('a', 2)\n\ndef loop():\n    pass\n",
        message="Argument 1 of String.substring() must be int, not const char*.",
    )


def test_substring_of_a_float_index_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.substring(0, 1.5)\n\ndef loop():\n    pass\n",
        message="Argument 2 of String.substring() must be int, not float.",
    )


def test_substring_of_one_index_used_as_a_value_is_the_string_type(result):
    compiled = result("def main():\n    text = 'Hello World'\n    tail = text.substring(5)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["tail"].cpp_type == "String"


def test_substring_of_two_indexes_used_as_a_value_is_the_string_type(result):
    compiled = result("def main():\n    text = 'Hello World'\n    head = text.substring(0, 5)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["head"].cpp_type == "String"


def test_substring_used_as_a_value_does_not_mutate_the_receiver(result):
    compiled = result("def main():\n    text = 'Hello World'\n    part = text.substring(0, 2)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["part"].cpp_type == "String"
    receiver = compiled.context.setup_info.locals["text"]
    assert receiver.is_const is False
    assert receiver.write_count == 1


def test_substring_of_a_fixed_global_keeps_the_global_unchanged(result):
    compiled = result("text = 'Hello World'\n\ndef main():\n    head = text.substring(0, 5)\n\ndef loop():\n    pass\n")
    var = compiled.context.globals["text"]
    assert var.cpp_type == "String"
    assert var.is_const is True
    assert var.write_count == 1


def test_two_substring_results_can_come_from_one_string(result):
    compiled = result(
        "def main():\n    line = 'Hello World'\n    tail = line.substring(6)\n    head = line.substring(0, 5)\n\ndef loop():\n    pass\n"
    )
    locals_ = compiled.context.setup_info.locals
    assert locals_["tail"].cpp_type == "String"
    assert locals_["head"].cpp_type == "String"


def test_remove_turns_a_fixed_string_into_a_mutable_arduino_string(result):
    compiled = result("text = 'Hello World'\n\ndef main():\n    text.remove(5, 3)\n\ndef loop():\n    pass\n")
    var = compiled.context.globals["text"]
    assert var.cpp_type == "String"
    assert var.is_const is False


def test_remove_of_a_local_string_is_accepted(result):
    compiled = result("def main():\n    text = 'Hello'\n    text.remove(0)\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_remove_is_allowed_inside_runtime_control_flow(result):
    compiled = result(
        "def main():\n    text = 'Hello'\n    while 1 < 0:\n        text.remove(0)\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_remove_without_an_argument_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.remove()\n\ndef loop():\n    pass\n",
        message="String.remove() takes 1 to 2 arguments but 0 were given.",
    )


def test_remove_with_three_arguments_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.remove(0, 1, 2)\n\ndef loop():\n    pass\n",
        message="String.remove() takes 1 to 2 arguments but 3 were given.",
    )


def test_remove_of_a_string_index_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.remove('a')\n\ndef loop():\n    pass\n",
        message="Argument 1 of String.remove() must be int, not const char*.",
    )


def test_remove_of_a_float_index_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.remove(1.5, 1)\n\ndef loop():\n    pass\n",
        message="Argument 1 of String.remove() must be int, not float.",
    )


def test_remove_used_as_a_value_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    left = text.remove(0, 1)\n\ndef loop():\n    pass\n",
        message="remove() has to be used as a statement.",
        hint="String.remove() changes the string in place.",
    )


def test_clear_turns_a_fixed_string_into_a_mutable_arduino_string(result):
    compiled = result("text = 'Hello'\n\ndef main():\n    text.clear()\n\ndef loop():\n    pass\n")
    var = compiled.context.globals["text"]
    assert var.cpp_type == "String"
    assert var.is_const is False


def test_clear_of_a_local_string_is_accepted(result):
    compiled = result("def main():\n    text = 'Hello'\n    text.clear()\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_clear_is_allowed_inside_runtime_control_flow(result):
    compiled = result(
        "def main():\n    text = 'Hello'\n    while 1 < 0:\n        text.clear()\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_clear_with_an_argument_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.clear(1)\n\ndef loop():\n    pass\n",
        message="String.clear() takes exactly 0 arguments but 1 was given.",
    )


def test_clearing_a_string_used_as_a_value_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    empty = text.clear()\n\ndef loop():\n    pass\n",
        message="clear() has to be used as a statement.",
        hint="String.clear() changes the string in place.",
    )


def test_a_string_clear_does_not_disturb_a_list_clear(result):
    compiled = result(
        "def main():\n    text = 'Hello'\n    text.clear()\n    values = [1, 2]\n    values.clear()\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"
    assert compiled.context.setup_info.locals["values"].is_array is True


def test_insert_turns_a_fixed_string_into_a_mutable_arduino_string(result):
    compiled = result("text = 'Hello'\n\ndef main():\n    text.insert(0, ', ')\n\ndef loop():\n    pass\n")
    var = compiled.context.globals["text"]
    assert var.cpp_type == "String"
    assert var.is_const is False


def test_insert_of_a_local_string_is_accepted(result):
    compiled = result("def main():\n    text = 'Hello'\n    text.insert(5, '!')\n\ndef loop():\n    pass\n")
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_insert_is_allowed_inside_runtime_control_flow(result):
    compiled = result(
        "def main():\n    text = 'Hello'\n    while 1 < 0:\n        text.insert(0, '>')\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"


def test_insert_with_one_argument_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.insert(0)\n\ndef loop():\n    pass\n",
        message="String.insert() takes exactly 2 arguments but 1 was given.",
    )


def test_insert_of_a_string_index_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.insert('a', 'b')\n\ndef loop():\n    pass\n",
        message="Argument 1 of String.insert() must be int, not const char*.",
    )


def test_insert_of_a_number_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    text.insert(0, 7)\n\ndef loop():\n    pass\n",
        message="Argument 2 of String.insert() must be String, not int.",
    )


def test_insert_used_as_a_value_is_rejected(error):
    error(
        "def main():\n    text = 'Hello'\n    other = text.insert(0, 'a')\n\ndef loop():\n    pass\n",
        message="insert() has to be used as a statement.",
        hint="String.insert() changes the string in place.",
    )


def test_a_string_insert_does_not_disturb_a_list_insert(result):
    compiled = result(
        "def main():\n    text = 'Hello'\n    text.insert(0, '>')\n    values = [1, 2]\n    values.insert(0, 9)\n\ndef loop():\n    pass\n"
    )
    assert compiled.context.setup_info.locals["text"].cpp_type == "String"
    assert compiled.context.setup_info.locals["values"].is_array is True



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

    imported = importlib.import_module(f"controllerpy.compiler.validator.{module}")
    function = getattr(imported, REPORTING_FUNCTIONS[module])
    annotations = {getattr(hint, "__name__", str(hint)) for hint in get_type_hints(function).values()}

    assert "ErrorReporter" in annotations
    assert "CompileContext" not in annotations
