"""The Arduino library registry: the data model a library is described with.

These tests exercise the registry on its own - what a library entry can say and
how a name is looked up in it.  Which libraries are listed, and what the
compiler does with them, is covered by the validator and generator tests.
"""

from __future__ import annotations

import dataclasses

from micropy.compiler.validator.libraries import (
    LIBRARIES,
    ApiClass,
    ApiMethod,
    Library,
    library_for,
    supported_libraries,
)


def a_method() -> ApiMethod:
    return ApiMethod("attach", 1, 1)


def a_class() -> ApiClass:
    return ApiClass("Widget", "Widget", methods=(a_method(),))


def a_library() -> Library:
    return Library("Widget", "Widget.h", "Widget", "widget", (a_class(),))


# ------------------------------------------------------------------- methods
def test_a_method_that_keeps_its_name_needs_no_cpp_name():
    assert a_method().cpp_method == "attach"


def test_a_method_can_be_mapped_to_a_differently_named_cpp_call():
    renamed = ApiMethod("write_angle", 1, 1, "void", "write")

    assert renamed.py_name == "write_angle"
    assert renamed.cpp_method == "write"


def test_a_method_records_its_arity_and_return_type():
    method = ApiMethod("read", 0, 0, "int")

    assert (method.min_args, method.max_args, method.returns) == (0, 0, "int")


def test_a_method_returns_nothing_unless_it_says_otherwise():
    assert a_method().returns == "void"


# -------------------------------------------------------------------- classes
def test_a_class_looks_a_method_up_by_its_python_name():
    cls = a_class()

    # The very method the class was built with, not a copy of it.
    assert cls.method("attach") is cls.methods[0]


def test_a_class_reports_an_unknown_method_as_missing():
    assert a_class().method("detach") is None


def test_a_class_constructor_takes_no_arguments_by_default():
    cls = a_class()

    assert (cls.ctor_min_args, cls.ctor_max_args) == (0, 0)


def test_a_class_can_describe_a_constructor_that_takes_arguments():
    cls = ApiClass("Widget", "Widget", ctor_min_args=1, ctor_max_args=2)

    assert (cls.ctor_min_args, cls.ctor_max_args) == (1, 2)
    assert cls.methods == ()


def test_a_class_keeps_its_python_name_and_its_cpp_type_apart():
    cls = ApiClass("Widget", "WidgetT")

    assert (cls.name, cls.cpp_type) == ("Widget", "WidgetT")


# ------------------------------------------------------------------ libraries
def test_a_library_describes_what_it_contributes_to_the_cpp():
    library = a_library()

    assert library.name == "Widget"
    assert library.header == "Widget.h"
    assert library.cpp_type == "Widget"
    assert library.module == "widget"
    assert library.classes == (a_class(),)


def test_a_library_looks_a_class_up_by_name():
    assert a_library().class_named("Widget") == a_class()


def test_a_library_reports_an_unknown_class_as_missing():
    assert a_library().class_named("Gadget") is None


def test_a_library_keeps_its_module_name_as_metadata_only():
    # The module name is recorded, not honoured: an import is resolved through
    # LIBRARIES, so the entry cannot make `from widget import Widget` work.
    assert a_library().module == "widget"
    assert "widget" not in LIBRARIES


def test_a_library_needs_nothing_but_a_name_and_a_header():
    library = Library("Gadget", "Gadget.h")

    assert library.cpp_type is None
    assert library.module is None
    assert library.classes == ()
    assert library.class_named("Gadget") is None


def test_a_library_is_a_value_that_cannot_be_changed_after_it_is_registered():
    library = a_library()

    try:
        library.header = "Other.h"
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover - the assignment above always raises
        raise AssertionError("a registered library must not be mutable")

    assert library.header == "Widget.h"


# ---------------------------------------------------------------- the table
def test_library_for_finds_a_listed_library_and_reports_the_rest_as_missing():
    assert library_for("Servo") is LIBRARIES["Servo"]
    assert library_for("Widget") is None


def test_supported_libraries_is_a_copy_of_the_table():
    listed = supported_libraries()
    listed.pop("Servo")

    assert "Servo" in LIBRARIES
    assert library_for("Servo") is not None


# --------------------------------------------------------------------- Servo
def servo() -> ApiClass:
    return library_for("Servo").class_named("Servo")


def test_servo_is_registered_with_its_header_and_cpp_type():
    library = library_for("Servo")

    assert library.name == "Servo"
    assert library.header == "Servo.h"
    assert library.cpp_type == "Servo"


def test_servo_keeps_its_module_name_as_metadata_only():
    # Recorded, not honoured: `from servo import Servo` stays unsupported.
    assert library_for("Servo").module == "servo"
    assert "servo" not in LIBRARIES


def test_servo_provides_the_servo_class():
    cls = servo()

    assert cls.name == "Servo"
    assert cls.cpp_type == "Servo"


def test_servo_is_created_without_arguments():
    assert (servo().ctor_min_args, servo().ctor_max_args) == (0, 0)


def test_servo_offers_exactly_the_four_documented_methods():
    assert [method.py_name for method in servo().methods] == [
        "attach",
        "detach",
        "write",
        "read",
    ]


def test_servo_attach_takes_a_pin_and_optional_min_and_max():
    attach = servo().method("attach")

    # The three arities the Arduino API documents, as one method.
    assert (attach.min_args, attach.max_args) == (1, 3)
    assert attach.returns == "int"


def test_servo_detach_takes_nothing_and_returns_nothing():
    detach = servo().method("detach")

    assert (detach.min_args, detach.max_args, detach.returns) == (0, 0, "void")


def test_servo_write_takes_one_angle_and_returns_nothing():
    write = servo().method("write")

    assert (write.min_args, write.max_args, write.returns) == (1, 1, "void")


def test_servo_read_takes_nothing_and_returns_a_position():
    read = servo().method("read")

    assert (read.min_args, read.max_args, read.returns) == (0, 0, "int")


def test_servo_methods_are_looked_up_by_their_python_name():
    # Servo is not renamed, so every Python name is the C++ name.
    for method in servo().methods:
        assert method.cpp_method == method.py_name
        assert method.cpp_name is None


def test_servo_has_no_method_beyond_the_documented_api():
    assert servo().method("writeMicroseconds") is None
