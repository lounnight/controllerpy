# controllerpy

Write Arduino programs in a Python-like subset. `controllerpy` parses real Python
source with Python's `ast` module, validates it, and transpiles it into native
Arduino C++ that you can read, review and commit. When you are happy with the
result, it can compile and upload the sketch with `arduino-cli`.

> `controllerpy` was previously called **MicroPy** (and, before that, **ArduinoPy**) -
> the compiler, the API and the generated code are the same, only the name changed.

```python
# main.py
LED = 13
BUTTON = 7

def main():
    pin_mode(LED, OUTPUT)
    pin_mode(BUTTON, INPUT_PULLUP)

def loop():
    if digital_read(BUTTON) == LOW:
        digital_write(LED, HIGH)
    else:
        digital_write(LED, LOW)

    delay(50)
```

```bash
controllerpy build main.py
```

```cpp
// build/main.ino
const int LED = 13;
const int BUTTON = 7;

void setup() {
    pinMode(LED, OUTPUT);
    pinMode(BUTTON, INPUT_PULLUP);
}

void loop() {
    if (digitalRead(BUTTON) == LOW) {
        digitalWrite(LED, HIGH);
    } else {
        digitalWrite(LED, LOW);
    }

    delay(50);
}
```

## Installation

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'   # .[dev] adds pytest
```

Only the standard library is required at runtime. `arduino-cli` is optional -
it is needed for `controllerpy compile` and `controllerpy upload` only.

If you prefer not to install anything, run the CLI from a checkout. `src/` is
the package itself, so the module is started from the repository root:

```bash
python3 -m src build main.py
```

## Quick start

```bash
controllerpy init                                  # IDE setup: controllerpy_api.pyi + pyrightconfig.json
controllerpy build main.py                          # build/main.ino
controllerpy check main.py                          # parse + validate only
controllerpy clean                                  # remove generated files
controllerpy compile main.py --board arduino:avr:uno
controllerpy upload  main.py --board uno --port /dev/ttyACM0
controllerpy ports                                  # which boards are attached?
controllerpy boards                                 # which boards are supported?
controllerpy stubs                                  # controllerpy_api.pyi only (legacy; prefer init)
```

### Command reference

| Command | What it does | Needs `arduino-cli` |
| --- | --- | --- |
| `init [-f/--force]` | writes `controllerpy_api.pyi`, `pyrightconfig.json` and `main.py` (see *IDE and type-checker support*) | no |
| `build SOURCE` | transpiles to `<output>/<name>.ino` (default `build/`) | no |
| `check SOURCE` | parses and validates, writes nothing | no |
| `clean` | deletes `--output-dir` | no |
| `compile SOURCE --board B` | `build` + writes the sketch folder + `arduino-cli compile` | yes |
| `upload SOURCE --board B --port P` | `compile` + `arduino-cli upload` | yes |
| `ports` | `arduino-cli board list` | yes |
| `boards` | lists supported (and planned) boards | no |
| `stubs` | writes `controllerpy_api.pyi` only (legacy; prefer `init`) | no |

Common options: `-o/--output-dir`, `-b/--board` (FQBN or alias such as `uno`),
`-v/--verbose`, `--arduino-cli PATH`, `--port`, `--debug`, `--version`. `--debug`
is a global option and may be written before or after the command, so
`controllerpy --debug build main.py`, `controllerpy build --debug main.py` and
`controllerpy build main.py --debug` are the same thing.

`-o` takes a **directory** for every command except `stubs`, which writes a
single **file** and therefore spells its option `--output-file`:

```bash
controllerpy build main.py -o out      # out/main.ino
controllerpy stubs --output-file api/controllerpy_api.pyi   # api/controllerpy_api.pyi
controllerpy stubs -o api.pyi          # the same, and still the same
```

`stubs` keeps `-o` and `--output` as aliases of `--output-file`; the path is
always the file to write, never a directory.

Exit codes: `0` success, `1` source/compiler error, `2` usage error (for
example a missing `--port`), `3` arduino-cli missing or failed, `70` internal
error.

### Reading the output

Every command speaks the same visual language, so a run can be skimmed without
reading it. A line starts with a symbol that says what kind of line it is,
anything that qualifies that line is indented under it, and a result with more
than one thing to report ends in an aligned block of facts:

| Symbol | Meaning |
| --- | --- |
| `→` | something is happening right now |
| `✓` | it worked |
| `!` | a warning - the command carried on, but look at this |
| `✗` | it failed |

```bash
$ controllerpy build main.py
  → Compiling main.py
  ✓ Build complete

    Output  build/main.ino (42 lines)
```

```bash
$ controllerpy upload main.py --board uno -p /dev/ttyACM0
  → Compiling main.py for Arduino Uno
  → Uploading to /dev/ttyACM0
  ✓ Upload complete

    Sketch  build/main
    Board   Arduino Uno
    Port    /dev/ttyACM0
    Output  build/main.ino
```

The labels in a block like that are dimmed and the values are not, so the paths,
boards and ports are what the eye lands on. The success line says the job is
done; the block says what it was done to.

Colours follow the same rule: cyan for work in progress, green for success,
yellow for a warning, red for a failure, dim for everything secondary. Colour is
only ever decoration - every line means the same thing without it. It is switched
off automatically when the output is redirected into a file or a pipe, when
`NO_COLOR` is set (any non-empty value, as [no-color.org](https://no-color.org)
defines it), or when `TERM=dumb`, so scripts and CI always get plain text.
`FORCE_COLOR=1` turns colour on for a stream that is not a terminal.

Add `-v` to see the `arduino-cli` command that ran, in the left margin like a
shell would show it, with the tool's own output indented underneath.

### Where files are written

```text
build/
├── main.ino          # exactly the generated C++ (controllerpy build)
├── main/
│   └── main.ino      # the same code as an Arduino sketch
└── arduino/
    └── main/         # arduino-cli build artifacts
```

## Language reference

`controllerpy` accepts a deliberately small, explicit subset of Python. Anything
outside it is reported as an error with a file, line and column - the compiler
never silently skips code.

### Entry points

`main()` becomes `setup()` and `loop()` becomes `loop()`. Both are required and
must be defined exactly once, at the top level, without parameters:

```text
main.py:12:1

Missing required function: loop()
```

### Statements

`Assign`, `AnnAssign`, `AugAssign` (`+= -= *= /= //= %= &= |= ^= <<= >>= **=`),
`Expr`, `If` / `elif` / `else`, `While`, `For ... in range(...)`, `FunctionDef`,
`Return`, `Break`, `Continue`, `Pass`, `ClassDef`.

### Expressions and operators

| Python | C++ | Notes |
| --- | --- | --- |
| `a + b`, `a - b`, `a * b`, `a / b`, `a % b` | same | `/` on integers follows C semantics |
| `a // b` | `a / b` for ints, `floor(a / b)` for floats | |
| `a % b` (floats) | `fmod(a, b)` | |
| `a ** b` | `pow(a, b)` | assigning to an int truncates |
| `a & b`, `a \| b`, `a ^ b`, `a << b`, `a >> b` | same | integers only |
| `== != < > <= >=` | same | `0 < x < 10` becomes `0 < x && x < 10` |
| `and`, `or`, `not` | `&&`, `\|\|`, `!` | grouping kept and extended where needed |
| `a if cond else b` | `cond ? a : b` | |
| `-a`, `+a`, `~a` | same | |
| `len(array)`, `array[i]` | `sizeof(...)` / `array[i]` | arrays from list literals |
| `abs`, `min`, `max`, `constrain`, `pow`, `sqrt`, `floor`, `ceil`, `round` | same | Arduino/C++ math helpers |

Comparisons may be chained, but a chained comparison may not contain a
function call (it would be evaluated twice).

Grouping parentheses are kept: a parenthesised sub-expression stays
parenthesised in the C++ (`(a + b) * c` does not become `a + b * c`), and
parentheses the translation needs are added where Python's grouping would
otherwise be lost.

### Variables and types

```python
LED = 13                  # const int LED = 13;
counter = 0               # int counter = 0;
enabled = True            # const bool enabled = true;
name = "hello"            # const char* name = "hello";
label: str = "hello"      # String label = "hello";
temperature = 25.5        # const float temperature = 25.5;
reading: int              # int reading;
values = [1, 2, 3]        # const int values[3] = {1, 2, 3};
status = Led(13)          # Led status(13);
```

* Types are inferred from the assigned values; `int`/`float`/`bool`/`String`
  are supported, as are your own classes and Arduino library objects.
* A top-level variable becomes `const` when it is assigned exactly once and the
  value is not a call and not an object.
* A variable assigned in one place as `int` and in another as `float` is
  promoted to `float`; incompatible types are an error.
* Parameters are typed from annotations first, then from the argument types seen
  at every call site; unknown parameters default to `int`.
* Return types come from the `-> T` annotation when present, otherwise from the
  `return` statements (resolved through a small fixpoint pass, so helpers may be
  defined after the code that calls them).
* Top-level names behave like C++ globals: assigning to one inside a function
  updates the global instead of creating a local (this is the one deliberate
deviation from Python's scoping rules, and it is what makes Arduino counters
work without a `global` statement).
* C++ keywords and Arduino function names are renamed with a trailing
  underscore (`explicit` -> `explicit_`, a local `delay` -> `delay_`), while
  reusing the name of an Arduino constant or object (`Serial`, `HIGH`) is
  rejected.

### Arduino API

| controllerpy | Arduino C++ |
| --- | --- |
| `pin_mode(pin, mode)` | `pinMode(pin, mode)` |
| `digital_write(pin, value)` | `digitalWrite(pin, value)` |
| `digital_read(pin)` | `digitalRead(pin)` |
| `analog_read(pin)` | `analogRead(pin)` |
| `analog_write(pin, value)` | `analogWrite(pin, value)` |
| `delay(ms)` | `delay(ms)` |
| `delay_microseconds(us)` | `delayMicroseconds(us)` |
| `millis()` / `micros()` | `millis()` / `micros()` |
| `pulseIn(pin, state[, timeout])` | `pulseIn(pin, state[, timeout])` |
| `tone(pin, frequency[, duration])` / `noTone(pin)` | `tone(pin, frequency[, duration])` / `noTone(pin)` |
| `serial_begin(baud)` | `Serial.begin(baud)` |
| `serial_print(value)` / `serial_println(value)` | `Serial.print(...)` / `Serial.println(...)` |
| `serial_available()` / `serial_read()` | `Serial.available()` / `Serial.read()` |
| `serial_flush()` / `serial_end()` | `Serial.flush()` / `Serial.end()` |

Constants (`HIGH`, `LOW`, `INPUT`, `OUTPUT`, `INPUT_PULLUP`, `INPUT_PULLDOWN`,
`CHANGE`, `RISING`, `FALLING`, `A0`...`A5`, `LED_BUILTIN`) are never turned into
numbers - they stay Arduino identifiers in the generated code. `Serial.begin(...)`
and other C++ style calls also work unchanged.

`pulseIn(pin, state[, timeout])` measures the duration of a `HIGH` or `LOW`
pulse on a pin in microseconds; the optional `timeout` defaults to 1000000.

`tone(pin, frequency[, duration])` plays a square wave of `frequency` hertz on a
pin; the optional `duration` stops it after that many milliseconds, and
`noTone(pin)` stops it early.

### Classes

```python
class Led:
    def __init__(self, pin):
        self.pin = pin
        pin_mode(pin, OUTPUT)

    def on(self):
        digital_write(self.pin, HIGH)

    def off(self):
        digital_write(self.pin, LOW)

status = Led(13)
```

```cpp
class Led {
public:
    int pin;

    Led(int pin) {
        this->pin = pin;
        pinMode(pin, OUTPUT);
    }

    void on() {
        digitalWrite(this->pin, HIGH);
    }

    void off() {
        digitalWrite(this->pin, LOW);
    }
};

Led status(13);
```

Supported: classes without inheritance, `__init__`, methods, `self`
attributes, method calls. Classes are emitted in dependency order, prototypes
are generated for every function, and objects created inside a function are
constructed where they are declared.

### Structs

A class with fields and no methods is a struct: a group of values that is
created, filled in and passed around by value.

```python
class Point:
    x: int
    y: float

def shifted(point: Point) -> Point:
    other = Point()
    other.x = point.x + 1
    other.y = point.y
    return other
```

```cpp
struct Point {
    int x;
    float y;
};

Point shifted(Point point);

Point shifted(Point point) {
    Point other;
    other.x = point.x + 1;
    other.y = point.y;
    return other;
}
```

Supported: fields declared with a type and no value, a struct as an
annotation, a parameter or a return type, a struct field or class attribute of
another struct. A struct is created without arguments (`Point()`) and its
fields are assigned afterwards; a type annotation can only name a struct that is
declared above it.

### Arduino libraries

```python
from controllerpy import Servo

servo = Servo()

def main():
    servo.attach(9)
```

becomes

```cpp
#include <Servo.h>

Servo servo;

void setup() {
    servo.attach(9);
}
```

`Servo`, `SoftwareSerial`, `LiquidCrystal`, `Wire`, `SPI` and `EEPROM` are
known. Any other import is refused with a clear message (`Python library
'requests' is not supported on Arduino.`), and the API of a library is passed
through untranslated.

### IDE and type-checker support

```bash
controllerpy init              # writes controllerpy_api.pyi, pyrightconfig.json, main.py
controllerpy init --force      # regenerate them
```

`controllerpy init` is the recommended way to configure a project. It writes:

* `controllerpy_api.pyi` - type stubs for `pin_mode`, `digital_write`, `OUTPUT`, ...
  (the same file `controllerpy stubs` writes; IDE support only, it is never uploaded
  to the board and `controllerpy` itself ignores it),
* `pyrightconfig.json` - tells Pyright/Pylance where to find the stub,
* `main.py` - re-exports the stub so the API is available in every
  program **without** `from controllerpy_api import *`:

```python
LED = 13

def main():
    pin_mode(LED, OUTPUT)

def loop():
    digital_write(LED, HIGH)
    delay(1000)
```

Older projects can keep using `controllerpy stubs` and the import line; both
commands copy the same bundled stub, so new API names reach both.

## Errors

Normal problems never produce a traceback. The failure is a `✗` line, and
everything the error knows is indented under it - the file and position first,
then what went wrong, then the advice, labelled `hint:` so its role is obvious
before you read it:

```text
  ✗ ControllerPyError

  main.py:8:5
  Unknown ArduinoPy function: foo()

    hint: Known names:
      analog_read
      analog_write
      delay
      digital_read
      ...
```

Other examples:

```text
  ✗ ControllerPyError

  main.py:1:1
  Unsupported Python feature: async function
```

```text
  ✗ ArduinoCliError

  arduino-cli was not found.

    hint: Check the path, or install the Arduino CLI:
      1. Install the Arduino CLI: https://arduino.github.io/arduino-cli/latest/installation/
      2. Install the AVR core for the Uno: arduino-cli core install arduino:avr
      3. Or point controllerpy at an existing binary:
           controllerpy compile main.py --arduino-cli /path/to/arduino-cli
           (or set the CONTROLLERPY_ARDUINO_CLI environment variable)

      'controllerpy build' and 'controllerpy check' work without arduino-cli.
```

Every word the error carries is printed: the title, the location, the message,
the hint and every hint line. Use `--debug` to see the underlying traceback when
a bug is suspected.

## How it works

```text
main.py
   |  parser.py     ast.parse()            Python grammar, never regex
   v
 AST
   |  validator/    subset + symbol tables  file:line:col errors, no codegen
   v
 typed AST
   |  generator/    CodeWriter + precedence aware printer
   v
  build/main.ino
   |  arduino.py     arduino-cli compile / upload (optional)
   v
 Arduino Uno
```

Every stage is a separate module and can be used on its own:

```python
from controllerpy import compile_source
from controllerpy.compiler import Compiler

result = compile_source(open("main.py").read(), filename="main.py")
print(result.cpp)          # the generated C++
print(result.summary())    # "2 globals, 1 function"

compiler = Compiler(filename="main.py")
tree = compiler.parse(source)          # stage 1
context = compiler.validate(tree)      # stage 2
cpp = compiler.generate(context)       # stage 3
```

## Project layout

```text
controllerpy/
├── pyproject.toml
├── main.py                     the acceptance example from the spec
├── compiler.py                 deprecated single-file prototype (kept)
├── examples/                   blink, button, loops, oop, serial, servo, structs
├── src/                        the controllerpy package
│   ├── cli/                    the argparse front end
│   │   ├── main.py               entry point: parse, dispatch, errors -> exit code
│   │   ├── parser.py             every command, argument and option
│   │   ├── commands/             one module per kind of command
│   │   │   ├── sketch.py            build, check, clean
│   │   │   ├── toolchain.py         compile, upload, ports
│   │   │   └── project.py           init, stubs, boards
│   │   ├── output.py             what the CLI prints: symbols, streams, layout
│   │   ├── style.py              whether colour is allowed, and the codes
│   │   ├── exit_codes.py         the exit-code contract
│   │   └── utils.py              sketch naming, build/ layout
│   ├── boards.py               board (FQBN) registry
│   ├── arduino.py              arduino-cli integration
│   ├── errors.py               ControllerPyError / ArduinoCliError
│   ├── compiler/
│   │   ├── parser.py           stage 1: source -> AST
│   │   ├── validator/          stage 2: subset checks + symbol tables
│   │   │   ├── api.py            Arduino API tables
│   │   │   ├── types.py          the C++ type system
│   │   │   ├── naming.py         C++ keywords, reserved names
│   │   │   ├── libraries.py      Arduino library registry
│   │   │   ├── symbols.py        VarInfo/FunctionInfo/ClassInfo/Scope
│   │   │   ├── context.py        CompileContext
│   │   │   ├── ast_utils.py      AST helpers + unsupported-feature policy
│   │   │   ├── collector.py      collect definitions, finalise types
│   │   │   └── analyzer.py       body analysis, type inference
│   │   ├── generator/          stage 3: AST -> C++
│   │   │   ├── generator.py        the emission passes, in order
│   │   │   ├── formatting.py       CodeWriter + cpp string literals
│   │   │   ├── operators.py       C++ operator tokens + precedence
│   │   │   ├── ordering.py        class dependency order
│   │   │   ├── expressions.py     precedence aware expression printer
│   │   │   ├── declarations.py    variables, parameters, objects
│   │   │   └── statements.py      bodies, control flow, classes
│   │   └── compiler.py         the three-stage facade
│   └── runtime/api.pyi         IDE stub (never uploaded)
└── tests/                      pytest suite + expected C++ snapshots
```

`src/` *is* the `controllerpy` package: `pyproject.toml` maps the directory to the
import name (`[tool.setuptools.package-dir] controllerpy = "src"`), so the sources
stay flat and there is no nested `controllerpy/` directory to import through.

Stage 2 is the only stage that knows what controllerpy is, so it carries the most
detail. Its modules build on each other in one direction -
`api`/`types`/`naming`/`libraries` describe the target, `symbols` records what
was found, `context` holds the result for stage 3, and `validator` + `analyzer`
are the two phases that fill it in - which is why none of them import each
other cyclically. The first group never imports `context` at all: it reports
problems through the `ErrorReporter` it is handed (`CompileContext.error`), and
`types` is passed the class names it has to resolve rather than the context to
read them from. `controllerpy.compiler` re-exports `CompileContext` and `Validator`
if you want to drive the stage yourself.

Stage 3 is just as one-directional: `formatting` and `operators` hold the C++
vocabulary, `ordering` works out which classes come first, then `expressions`
prints expressions, `declarations` prints what they are stored in, `statements`
prints the bodies that hold both, and `generator.py` runs the emission passes
in the only order that produces valid C++.

The CLI is a thin front end over the three stages: `parser.py` defines what
each command accepts, `commands/` decide *which* job to do (`compile_file` for
a source, `controllerpy.arduino` for the toolchain), `output.py` renders the result
and `main.py` turns it into an exit code. It never reaches into a stage's
internals, and `commands/` never imports `main` or `parser`, so a command can
be added in one module plus one line in `parser.py`.

Presentation is split in two as well: `output.py` owns the vocabulary (which
symbol, which stream, how far to indent) and `style.py` owns the only question
colour raises, which is whether a given stream may be painted at all. Neither
knows anything about a compiler or a board, and `arduino.py` still runs
commands without printing a thing - the handler reports, `output.py` renders.

## Extending

* **New board**: add a `Board` to `BOARDS` in `boards.py` (`nano`, `mega` and
  `esp32` are already listed as planned). Nothing else changes - the generator
  only ever emits portable Arduino code.
* **New Arduino library**: add a `Library` to `LIBRARIES` in
  `compiler/validator/libraries.py` with its header and C++ type;
  `from controllerpy import YourLibrary` then works.
* **New API function**: add an `ApiFunction` to `API_FUNCTIONS` in
  `compiler/validator/api.py` (Python name, C++ name, arity, return type) -
  validation, hints and code generation all read that table.
* **New CLI command**: add a handler to the matching `cli/commands/` module and
  register it in `cli/parser.py`.

## Known limitations

* Comments are not preserved: the AST does not contain them. Source blank lines
  and paragraph structure are kept.
* Bytecode-level Python semantics (`//` on negative integers, integer overflow,
  float precision) follow C/C++ on the board.
* `**` maps to `pow()` and truncates when the result is stored in an int.
* Grouping parentheses written on one line are preserved; grouping split across
  lines is re-derived from operator precedence, which keeps the same meaning but
  may drop redundant parentheses.
* Arrays come from list or tuple literals only; they cannot be resized, passed
  to functions or returned.
* Objects created at the top level are constructed before `setup()` runs, so for
  libraries that need timers or interrupts, create the object inside `main()`.
* A `for` loop variable lives in the loop: do not reuse it after the loop.
* Locals whose first assignment sits inside an `if`/`while`/`for` block are
  declared (uninitialised) at the top of the function, because C++ scopes are
  narrower than Python's.
* No `try`/`except`, `with`, `lambda`, f-strings, comprehensions, dicts, sets,
  generators, threads or default arguments - see `UNSUPPORTED_FEATURES` in
  `compiler/validator/ast_utils.py` for the exact list.

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest          # 432 tests, including C++ snapshots
.venv/bin/controllerpy build main.py && cat build/main.ino
```

Tests compare generated C++ verbatim against the reviewed snapshots in
`tests/expected/`, so formatting changes are deliberate and reviewable. The
`arduino-cli` integration is tested with a fake executable, so no board or tool
chain is required.

## Roadmap

- [x] Improve CLI
- [x] More Arduino libraries in the registry (and a `Servo`-style API map).
- [x] Structs/lists of objects, `str` helpers and a small `String` builder.
- [ ] Add small functions
- [ ] Build a small text editor in the CLI
- [ ] More boards (Nano, Mega, ESP32) and a `--board` matrix in the test suite.
- [ ] Build GUI `IDE`

## License

MIT - see `LICENSE`.
