# logic-language

[English](#logic-language) | [中文（展开页末说明）](#chinese) | [MIT License](LICENSE)

**Express algorithm logic, program rules, and knowledge as precise, readable specifications.**

logic-language uses `.lp` files to organize ideas into explicit variables, conditions, definitions, and relationships. Describe the behavior you want, ask an AI to turn it into a program, and review the implementation against that description. When learning, use the same notation to connect concepts, record assumptions, and refine your understanding with examples and counterexamples.

The bundled compiler checks LP and produces a canonical logic AST. The examples show how to use that representation in an AI-assisted workflow.

[Quick start](#quick-start) · [LP and programming languages](#lp-and-programming-languages) · [Basic structures](#basic-structures) · [Classes](#classes-and-methods) · [Complete example](#from-an-informal-request-to-a-program) · [AI workflow](#working-with-ai) · [Learning](#learning-with-lp) · [Types](#type-system) · [Logic](#from-lp-to-logic) · [VS Code](#install-the-vs-code-extension)

## Quick start

Use Python 3.11 or newer. From the directory containing this README:

```sh
python -m pip install -r requirements.txt
python scripts/module_check.py --file examples/increment.lp --pretty
```

The bundled [increment.lp](examples/increment.lp) contains:

```lp
Value
increment: _value => _out_value
    _out_value = _value + 1
```

Successful checking prints:

```json
{
  "summary": {
    "error_count": 0,
    "warning_count": 0
  },
  "entries": []
}
```

`Value` declares a class. The input and output names resolve to it; the body specifies their relationship. To inspect the compiled form and run all examples, see [Tools and validation](#tools-and-validation). Editor setup is in [VS Code installation](#install-the-vs-code-extension).

## LP and programming languages

A common imperative programming language (PL) describes computation through **states, transitions, and control flow**: assignments change state, branches select transitions, and loops repeat them. Its implementation specifies an execution procedure.

**LP is declarative:** it describes what must hold under stated assumptions. The same function can accumulate preconditions, postconditions, computation dependencies, and logical properties, helping the specification follow several complementary parts of your reasoning.

| Aspect | Imperative program | LP |
| --- | --- | --- |
| Main question | What executes, and in what order? | What must hold, and under which conditions? |
| Variables and equality | Storage changes through assignments. | Scoped symbols participate in relationships; bindings name terms. |
| Function description | An executable procedure. | Several descriptions jointly constrain one function. |

For example, two descriptions of the same function can explain a computation and give a conditional guarantee:

```lp
Value
quadruple: _value => _out_value
    | _twice_value = _value + _value
    _out_value = _twice_value + _twice_value

quadruple: _value => _out_value
    | _value >= 0
    _out_value >= 0
```

The [complete contract](examples/contracts/quadruple.lp) also describes negative inputs and order preservation. These constraints accumulate; they are not redefinitions or dispatch rules. All applicable conditions impose their requirements together, regardless of source order. Conflicting requirements make the specification inconsistent; the current checker does not automatically detect every such conflict.

With ordinary integer arithmetic, an implementation can satisfy those relationships using another computation procedure:

```python
def quadruple(value):
    return value * 4
```

Intermediate dependencies need not become instructions in that exact order. Stateful behavior can likewise be specified through relationships between before and after states. An implementation determines how the transitions execute.

## Basic structures

| Form | Reading |
| --- | --- |
| `∀{\| _x \| p(_x) \| q(_x)}` | Every `_x` satisfying `p` must satisfy `q`. |
| `∃{\| _x \| p(_x), q(_x)}` | There is an `_x` satisfying both conditions. |
| `{\| _x \| p(_x), q(_x)}` | The set of objects satisfying both conditions. |
| A set body ending in `=> f(_x)` | An image-set: transform each qualifying source object. |
| `f: _input => _output` | Name a function's inputs and outputs, then constrain their relationship. |
| `Class ~ _x` | `_x` inherits `Class`. |

The leftmost section introduces variables, the rightmost contains targets, and intervening sections contain premises. Commas join conditions in a section with conjunction. In multiline bodies, binders and premises start with `|`; targets do not. Braces or indentation express nesting.

**Premises always use implication, including in existential statements and sets.** To require a witness satisfying both `p` and `q`, use `∃{| _x | p(_x), q(_x)}`. To filter a set, put every required condition in its target conjunction. `∃{| _x | p(_x) | q(_x)}` and `{| _x | p(_x) | q(_x)}` instead use `p → q`, which is true when `p` is false.

Local variables start with `_`, class names start with a capital letter, and callable names use lower snake case. A nested binder cannot reuse an ancestor's bound name. Imports use `$import path/to/file.lp`. Text forms `\all`, `\exists`, and `\in` normalize to `∀`, `∃`, and `∈`. Parenthesize arithmetic grouping: the current arithmetic parser groups infix operations left to right.

## Classes and methods

A Class groups a concept's fields and operations. A standalone capitalized name declares it; member lines start with `::`. The runnable [Point example](examples/classes/point.lp) describes coordinates and a derived coordinate:

```lp
Value
Point
    ::x_value
    ::y_value
    ::shifted_x: (_point, _delta_value) => _out_value
        _out_value = _point.x_value + _delta_value
```

`::x_value` and `::y_value` declare fields whose results inherit `Value`. The method explicitly takes `_point` as its first parameter, so name inference adds `Point ~ _point`; `_delta_value` is the additional input. It returns a computed coordinate. The implementation chooses object construction and storage layout.

| Surface form | Ordinary function form |
| --- | --- |
| `Point::x_value` | `x_value: _point => _x_value` |
| `Point::shifted_x: (_point, _delta_value) => _out_value` | `shifted_x: (_point, _delta_value) => _out_value` |
| `_point.x_value` | `x_value(_point)` |
| `_point.shifted_x(_delta_value)` | `shifted_x(_point, _delta_value)` |

The indented class block groups these declarations in the current scope. A method's receiver must be explicit; `Point::` does not insert it into a method signature. The owner prefix is erased during expansion, so member names become ordinary callable symbols rather than separate class namespaces. `Point` must be declared before using `Point::...`; an inheritance fact alone does not declare a class.

See [From LP to logic](#from-lp-to-logic) for the quantified constraints behind these forms, and the [Python example](examples/classes/point.py) for one implementation.

## From an informal request to a program

Suppose the request is: **“Return the IDs of active adult users.”** A natural-language document can leave several decisions implicit:

| Question | Explicit decision in this example |
| --- | --- |
| Who is an adult? | Age 18 or above, including 18. |
| What does active mean? | The record's Boolean `active` field is true. |
| Can an ID appear twice? | The result is a set, so duplicate IDs collapse. |
| Is the result ordered? | No order is required. |
| What happens with no qualifying users? | The result is empty. |

Assume finite input records with an integer `age`, a Boolean `active` field, and a hashable `id`. The runnable [eligible_ids.lp](examples/data_processing/eligible_ids.lp) declares the vocabulary and specifies:

```lp
User
Value
Id
Predicate

active: _user => _is_active
Predicate ~ active
age: _user => _value
user_id: _user => _id

eligible_ids: _users => _ids
    _ids = {
        | _user
        User ~ _user
        _user ∈ _users
        active(_user)
        age(_user) >= 18
        => user_id(_user)
    }
```

`active`, `age`, and `user_id` denote the corresponding record fields. The source conditions are conjoined; the image-set contains exactly the qualifying IDs. The class and collection naming rules are explained in [Type system](#type-system).

An AI can implement this contract as:

```python
def eligible_ids(users):
    return {
        user["id"]
        for user in users
        if user["active"] and user["age"] >= 18
    }
```

| LP requirement | Implementation and validation |
| --- | --- |
| `_user ∈ _users` | Iterate over input records. |
| `active(_user)` | Check the flag; include an inactive adult in the tests. |
| `age(_user) >= 18` | Test ages 17 and 18. |
| `=> user_id(_user)` | Project IDs; verify every result has a qualifying source witness. |
| Set output | Test repeated IDs and empty input. |

Run the example and the checks:

```sh
python examples/data_processing/eligible_ids.py
python examples/check_examples.py
```

The demo prints `[1]`; it sorts the set only for display. The checks verify source diagnostics and representative program behavior. A program's record layout, field interpretations, and error handling remain explicit implementation assumptions.

## Working with AI

Use this prompt with a specification:

> Read SKILL.md before interpreting this LP. Explain the variables, premises, targets, and domain assumptions. Identify unspecified behavior and ask about decisions needed for implementation.
>
> Implement it in [language]. Map each LP requirement to code, tests, or a proof obligation. List added assumptions and handling for inputs outside the specified domain. Run the LP checks and relevant program tests. Report any remaining diagnostics or counterexamples, and do not silently change the specification to fit the code.

Maintain the LP alongside its implementation. When requirements change, update the affected clauses and their corresponding code and checks.

The bundled [examples](examples/README.md) are executable starting points:

| Domain | LP | Program |
| --- | --- | --- |
| Multiple contracts | [quadruple.lp](examples/contracts/quadruple.lp) | [Python](examples/contracts/quadruple.py) |
| Algorithms | [minimum.lp](examples/algorithms/minimum.lp) | [Python](examples/algorithms/minimum.py) |
| Data processing | [eligible_ids.lp](examples/data_processing/eligible_ids.lp) | [Python](examples/data_processing/eligible_ids.py) |
| Classes and methods | [point.lp](examples/classes/point.lp) | [Python](examples/classes/point.py) |
| Access rules | [can_read.lp](examples/access_control/can_read.lp) | [Python](examples/access_control/can_read.py) |
| Knowledge relationships | [function_properties.lp](examples/learning/function_properties.lp) | [Python](examples/learning/function_properties.py) |

## Learning with LP

Learning can build one evolving knowledge file: introduce definitions, track assumptions and sources, then use examples and counterexamples to connect concepts.

For `f(x) = x²`, ask an AI to explore how the domain and codomain affect injectivity and surjectivity:

1. Over the integers, `1` and `−1` show that `f` is not injective.
2. Restrict the domain to nonnegative integers: `f` becomes injective.
3. Keep all nonnegative integers as the codomain: `2` has no preimage, so `f` is not surjective.
4. Define the codomain as the image `f(D)`: the function is surjective onto that image by construction.

The [learning example](examples/learning/function_properties.lp) defines mapping, injectivity, and surjectivity as Boolean properties. Its [program](examples/learning/function_properties.py) demonstrates finite domains; finite tests do not prove the corresponding claims over infinite domains.

> Help me learn [topic] by maintaining an LP knowledge file. Introduce vocabulary and scope first. For each concept, provide LP, a plain-language explanation, its logical interpretation, and examples or counterexamples. Distinguish definitions, assumptions, established results, and unverified conjectures, and record sources.
>
> When I add information, reuse terminology, show changes and dependencies, and identify conflicts with earlier assumptions. Keep explanations in comments or accompanying prose. Run the source checks, explain diagnostics, and do not label an unproved claim as a theorem.

Keep the file under version control. Comments and section labels record context; they do not establish proof status.

## Type system

LP uses **soft typing over one symbol domain**. Values, functions, predicates, and user concepts are symbols; ordinary inheritance facts express their classifications. A symbol can have several classifications, and classes are not automatically disjoint.

```lp
Value
double: _value => _out_value
    _out_value = _value + _value
```

Here `_value` and `_out_value` resolve to the visible class `Value`. **Input classifications are premises; output classifications are obligations.** The declaration requires a `Value` input and guarantees a `Value` output; checking source structure does not prove that guarantee.

With `Student` declared, `_student` resolves to `Student`, `_students` denotes a set whose members inherit `Student`, and `_student_list` denotes a tuple whose members inherit `Student`. Names beginning with `is_`, such as `_is_ready`, receive `Bool` classification. **Name inference affects the contract:** adding a visible class can change existing inference. Use neutral names and explicit inheritance when you need a stable classification.

For example, explicit classification can restrict a rule:

```lp
Person
∀{| _x | Person ~ _x | can_enroll(_x)}
```

`Person ~ _x` means `_x` inherits `Person`; `Person ~ Student` means `Student` inherits `Person`. Class declarations, inheritance axioms, lookup rules, and the editor's `class`/`func`/`pred`/`pure` roles are covered in the bilingual [type-system guide](docs/type-system.md).

## From LP to logic

These formulas explain semantics, not current compiler output. They omit auxiliary classification facts and bindings and assume the stated domain interpretation. LP uses a soft-typed, HOL-like representation; suitable first-order fragments can be written as FOL, while function objects and general set objects require explicit encodings and axioms.

<details>
<summary>Function, Class, field, and method: surface syntax → core logic → FOL</summary>

These are syntax sugars for ordinary symbols, inheritance facts, bindings, and quantified statements. The current compiler emits an AST; the FOL below is a possible reified first-order interpretation of these examples. It uses `Inherits(c, x)` for classification and `app1(f, x)` / `app2(f, x, y)` for application. Class and callable names are constants in this encoding. Assume `Value` has the intended ordinary arithmetic interpretation; auxiliary literal facts and generated temporaries are omitted.

**Function declaration and body.** A signature contributes a callable classification and a quantified output guarantee. The body contributes another quantified constraint with its own premises:

```lp
Value
increment: _value => _out_value
    | _value >= 0
    _out_value = _value + 1
```

A compact expansion into ordinary LP forms is:

```lp
Value
Function ~ increment
∀{| _value, _out_value | Value ~ _value, _out_value = increment(_value) | Value ~ _out_value}
∀{| _value, _out_value | Value ~ _value, _out_value = increment(_value), _value >= 0 | _out_value = _value + 1}
```

Its principal first-order facts and constraints are:

```text
Inherits(Symbol, Value)
Inherits(Function, increment)
∀x,y. (Inherits(Value, x) ∧ y = app1(increment, x)) → Inherits(Value, y)
∀x,y. (Inherits(Value, x) ∧ y = app1(increment, x) ∧ x ≥ 0) → y = x + 1
```

The signature's output classification applies to `Value` inputs; the body's arithmetic requirement additionally needs `x ≥ 0`. For other inputs, this body does not specify that arithmetic relationship. Multiple bodies add constraints to the same callable.

**Class declaration.** `Point` registers a visible class in the front end and emits the ordinary fact `Symbol ~ Point`, represented here by `Inherits(Symbol, Point)`. It does not introduce a separate primitive class construct in the final logic AST. Declaration visibility remains a source-level rule.

**Field declaration.** With `Value` and `Point` visible, `Point::x_value` expands to `x_value: _point => _x_value`. This adds:

```text
Inherits(Function, x_value)
∀p,v. (Inherits(Point, p) ∧ v = app1(x_value, p)) → Inherits(Value, v)
```

The field is thus a function of its receiver. `_point.x_value` rewrites to `x_value(_point)`. A class field equation such as `Point::x_value = 0` additionally requires `∀p. Inherits(Point, p) → app1(x_value, p) = 0`: it constrains every point's field, rather than describing a constructor default.

**Method declaration and call.** The Point block above expands to these ordinary function declarations:

```lp
Value
Point
x_value: _point => _x_value
y_value: _point => _y_value
shifted_x: (_point, _delta_value) => _out_value
    _out_value = x_value(_point) + _delta_value
```

The method's principal constraints combine its output guarantee and body:

```text
Inherits(Function, shifted_x)
∀p,d,r. (Inherits(Point, p) ∧ Inherits(Value, d) ∧ r = app2(shifted_x, p, d)) →
        (Inherits(Value, r) ∧ r = app1(x_value, p) + d)
```

A call `_point.shifted_x(_delta_value)` becomes `shifted_x(_point, _delta_value)`, represented by `app2(shifted_x, p, d)`. The receiver is the first argument, and the field read is a unary application. After removing `::`, `.`, and declaration arrows, the meaning is expressed through classification, application, equality, and quantification.

Inspect the compiler's full expansion, including generated symbols:

```sh
python scripts/expand_module.py examples/classes/point.lp
```

</details>

<details>
<summary>Quantified-stmt, set-stmt, and image-set translations</summary>

**Quantified statements** express universal rules or existential witnesses:

```lp
∀{| _x | human(_x) | mortal(_x)}
∃{| _x | human(_x), philosopher(_x)}
```

```text
∀x. Human(x) → Mortal(x)
∃x. Human(x) ∧ Philosopher(x)
```

**Set statements** define a predicate for membership:

```lp
{| _x | _x ∈ numbers, _x > 0}
```

Naming the predicate `Positive` gives:

```text
∀x. Positive(x) ↔ (Numbers(x) ∧ x > 0)
```

**Image-sets** introduce a qualifying source witness for each output:

```lp
{
    | _x
    _x ∈ numbers
    _x > 0
    => _x * _x
}
```

```text
∀y. Squares(y) ↔ ∃x. Numbers(x) ∧ x > 0 ∧ y = x × x
```

The compiler expands an image-set into a set with an existential witness. For `{−2, 1, 2, 3}`, the output is `{1, 4, 9}`. Duplicate outputs collapse, and no order is specified. Passing a set as an object requires an encoding such as `Member(set, x)` in FOL.

</details>

The bilingual [semantics guide](docs/semantics.md) includes fuller explanations and implication counterexamples. Generic snippets omit vocabulary declarations; use the files under `examples/` for checks without diagnostics. Explicit set premises produce `set_stmt_premise` warnings. The multiline image-set form avoids the current diagnostic mismatch for analogous inline filters.

## Install the VS Code extension

The extension provides syntax highlighting, diagnostics, symbol navigation, and import assistance. Build a local VSIX with Node.js 20+ and npm; use it with VS Code 1.85+ and the Python environment from Quick start:

```sh
cd tools/vscode
npm ci
npx vsce package --allow-missing-repository --out logic-language.vsix
code --install-extension ./logic-language.vsix
cd ../..
```

Alternatively choose **Extensions → … → Install from VSIX…**. The current extension finds the Python backend at `<workspace>/skills/logic-language/scripts/`; open the parent workspace containing that path. A standalone checkout currently needs that layout. The default interpreter is `py` on Windows and `python3` elsewhere; override it with `logicLanguage.pythonPath` if needed.

See the [extension guide](tools/vscode/README.md) for the workspace layout, Python settings, activation checks, and troubleshooting.

## Project status

| Capability | Status |
| --- | --- |
| Parse, desugar, check, and compile LP to JSON AST | Implemented. |
| Print canonical LP from AST; editor assistance | Implemented. |
| Explain LP, generate programs and tests, extend knowledge | AI-assisted workflow demonstrated by examples. |
| General FOL/SMT export and automated correctness proofs | Not implemented by the bundled tools. |

Checks validate supported source and AST conventions; tests examine selected executions. Neither alone proves a program or a knowledge claim correct. FOL encoding does not automatically preserve unrestricted HOL semantics or make reasoning decidable.

## Tools and validation

Run commands from the project root:

```sh
python scripts/compile_module.py examples/increment.lp --pretty
python scripts/expand_module.py examples/increment.lp
python scripts/compile_module.py examples/increment.lp --debug-stages
python examples/check_examples.py
```

The compiler has two stages: a front end producing a desugared source AST, and a back end producing the final object AST. [SKILL.md](SKILL.md) provides detailed language and AI instructions; [grammar.ebnf](grammar.ebnf) describes module structure; [semantic_logic/](semantic_logic/) describes AST concepts in LP.

Compiler development checks:

```sh
python scripts/compile_pipeline/smoke_test.py
python scripts/validate_golden_tests.py golden_tests.md
python scripts/module_check.py --file standard_library.lp --pretty
```

[Golden tests](golden_tests.md) review canonical expansion. The [standard library](standard_library.lp) must have zero errors; its explicit set premises can produce implication warnings that should be reviewed, not suppressed.

## License

The project and bundled VS Code extension are licensed under the [MIT License](LICENSE).

<a id="chinese"></a>

<details>
<summary>中文说明 / Read in Chinese</summary>

**一种轻量逻辑描述语言，用于将算法逻辑、程序规则和知识概念表述为严谨、易读的规格。**

logic-language 使用 `.lp` 文件，将想法组织为明确的变量、条件、定义和关系。你可以描述期望行为，让 AI 转化为程序，再对照描述审查实现。学习时，也可以使用同一套表示连接概念、记录假设，并通过例子和反例持续修正理解。

附带的编译器检查 LP 并生成规范化逻辑 AST；示例展示如何将这套表示用于 AI 辅助工作流。

[快速开始](#快速开始) · [LP 与程序语言](#lp-与程序语言) · [基本结构](#基本结构) · [类与方法](#类与方法) · [完整示例](#从模糊需求到程序) · [AI 工作流](#与-ai-协作) · [学习](#使用-lp-学习知识) · [类型](#类型系统) · [逻辑](#从-lp-理解逻辑) · [VS Code](#安装-vs-code-扩展)

## 快速开始

使用 Python 3.11 或更新版本。在本 README 所在目录执行：

```sh
python -m pip install -r requirements.txt
python scripts/module_check.py --file examples/increment.lp --pretty
```

附带的 [increment.lp](examples/increment.lp) 包含：

```lp
Value
increment: _value => _out_value
    _out_value = _value + 1
```

检查成功时输出：

```json
{
  "summary": {
    "error_count": 0,
    "warning_count": 0
  },
  "entries": []
}
```

`Value` 声明类，输入和输出名称会匹配该类，函数体规定二者的关系。查看编译结果和运行全部示例的方法见[工具与验证](#工具与验证)，编辑器配置见 [VS Code 安装](#安装-vs-code-扩展)。

## LP 与程序语言

常见命令式程序语言（PL）通过**状态、状态转移和控制流**描述计算：赋值改变状态，分支选择转移，循环重复转移。实现规定具体的执行过程。

**LP 采用声明式描述：**说明在什么假设下，哪些关系必须成立。同一个函数可以累积前置条件、后置条件、计算依赖和逻辑性质，使规格能够同时表达多个互补的思考角度。

| 方面 | 命令式程序 | LP |
| --- | --- | --- |
| 主要问题 | 执行什么，以什么顺序执行？ | 什么必须成立，在什么条件下成立？ |
| 变量与等式 | 通过赋值改变存储内容。 | 有作用域的符号参与逻辑关系，绑定为表达式命名。 |
| 函数描述 | 一个可执行过程。 | 多组描述共同约束同一个函数。 |

例如，同一个函数的两组描述可以分别给出计算依赖和条件保证：

```lp
Value
quadruple: _value => _out_value
    | _twice_value = _value + _value
    _out_value = _twice_value + _twice_value

quadruple: _value => _out_value
    | _value >= 0
    _out_value >= 0
```

[完整契约](examples/contracts/quadruple.lp) 还描述负输入和顺序保持性质。这些约束共同生效，不是函数覆盖或分派规则；所有适用条件的要求同时成立，不依赖源码顺序。相互矛盾的要求意味着规格不一致，当前检查器不会自动检测所有此类冲突。

采用普通整数算术时，实现可以使用另一种计算过程满足这些关系：

```python
def quadruple(value):
    return value * 4
```

中间依赖不必转化为完全相同顺序的指令。有状态行为也可以用前后状态之间的关系表述，再由实现决定如何执行状态转移。

## 基本结构

| 形式 | 如何理解 |
| --- | --- |
| `∀{\| _x \| p(_x) \| q(_x)}` | 所有满足 `p` 的 `_x` 必须满足 `q`。 |
| `∃{\| _x \| p(_x), q(_x)}` | 存在同时满足两个条件的 `_x`。 |
| `{\| _x \| p(_x), q(_x)}` | 同时满足两个条件的对象组成的集合。 |
| 集合体以 `=> f(_x)` 结尾 | Image-set（像集）：映射每个合格的源对象。 |
| `f: _input => _output` | 命名函数输入与输出，再约束二者的关系。 |
| `Class ~ _x` | `_x` 继承 `Class`。 |

最左侧段引入变量，最右侧段包含目标，中间段包含前提。同一段内用逗号连接的条件表示合取。多行体中，绑定变量和前提以 `|` 开头，目标不带该前缀。花括号或缩进表达嵌套。

**前提始终采用蕴含语义，存在量词和集合也是如此。** 若要求见证对象同时满足 `p` 与 `q`，使用 `∃{| _x | p(_x), q(_x)}`。筛选集合时，应将所有必要条件放在目标合取中。`∃{| _x | p(_x) | q(_x)}` 和 `{| _x | p(_x) | q(_x)}` 使用的是 `p → q`，当 `p` 为假时也成立。

局部变量以 `_` 开头，类名以大写字母开头，可调用符号使用小写蛇形命名。嵌套绑定变量不能复用祖先作用域中的绑定名称。导入使用 `$import path/to/file.lp`；文本形式 `\all`、`\exists` 和 `\in` 分别规范化为 `∀`、`∃` 和 `∈`。算术分组应加括号明确表达，当前算术解析器按从左到右的顺序分组。

## 类与方法

Class 将概念的字段与操作组织在一起。独立的大写名称声明类，成员行以 `::` 开头。可运行的 [Point 示例](examples/classes/point.lp)描述坐标和一个派生坐标：

```lp
Value
Point
    ::x_value
    ::y_value
    ::shifted_x: (_point, _delta_value) => _out_value
        _out_value = _point.x_value + _delta_value
```

`::x_value` 与 `::y_value` 声明字段，结果继承 `Value`。方法显式将 `_point` 写为第一参数，因此名称推断添加 `Point ~ _point`；`_delta_value` 是额外输入。方法返回计算得到的坐标，具体对象构造与存储布局由实现选择。

| 表面形式 | 普通函数形式 |
| --- | --- |
| `Point::x_value` | `x_value: _point => _x_value` |
| `Point::shifted_x: (_point, _delta_value) => _out_value` | `shifted_x: (_point, _delta_value) => _out_value` |
| `_point.x_value` | `x_value(_point)` |
| `_point.shifted_x(_delta_value)` | `shifted_x(_point, _delta_value)` |

缩进的类体将这些声明组织在当前作用域中。方法接收者必须显式列出，`Point::` 不会将它插入方法参数表。展开后，所属类前缀被移除，成员名称成为普通可调用符号，不形成独立的类命名空间。使用 `Point::...` 前必须声明 `Point`，单独的继承事实不会声明类。

这些形式背后的量化约束见[从 LP 理解逻辑](#从-lp-理解逻辑)，[Python 示例](examples/classes/point.py)展示一种实现。

## 从模糊需求到程序

假设需求是：**“返回成年活跃用户的 ID。”** 自然语言文档可能没有明确以下选择：

| 问题 | 本例的明确约定 |
| --- | --- |
| 成年如何定义？ | 年龄大于或等于 18，包含 18 岁。 |
| 活跃如何定义？ | 记录中的布尔字段 `active` 为真。 |
| ID 可以重复吗？ | 结果是集合，重复 ID 合并。 |
| 结果有序吗？ | 不要求顺序。 |
| 没有符合条件的用户时怎样？ | 返回空集合。 |

约定输入为有限记录集合，`age` 为整数，`active` 为布尔值，`id` 可哈希。可运行的 [eligible_ids.lp](examples/data_processing/eligible_ids.lp) 声明词汇并规定：

```lp
User
Value
Id
Predicate

active: _user => _is_active
Predicate ~ active
age: _user => _value
user_id: _user => _id

eligible_ids: _users => _ids
    _ids = {
        | _user
        User ~ _user
        _user ∈ _users
        active(_user)
        age(_user) >= 18
        => user_id(_user)
    }
```

`active`、`age` 和 `user_id` 对应记录中的字段。源条件同时成立，像集恰好包含合格用户的 ID。类与集合名称的推断规则见[类型系统](#类型系统)。

AI 可以将契约实现为：

```python
def eligible_ids(users):
    return {
        user["id"]
        for user in users
        if user["active"] and user["age"] >= 18
    }
```

| LP 要求 | 实现与验证 |
| --- | --- |
| `_user ∈ _users` | 遍历输入记录。 |
| `active(_user)` | 检查活跃标志，测试包含非活跃成年人。 |
| `age(_user) >= 18` | 测试 17 岁与 18 岁边界。 |
| `=> user_id(_user)` | 提取 ID，检查每个结果都有合格的源见证。 |
| 集合输出 | 测试重复 ID 与空输入。 |

运行示例和检查：

```sh
python examples/data_processing/eligible_ids.py
python examples/check_examples.py
```

演示输出 `[1]`，排序仅用于显示。检查覆盖源文本诊断和代表性的程序行为。记录布局、字段解释及异常处理仍属于需要明确说明的实现假设。

## 与 AI 协作

可以将以下提示词与规格一起交给 AI：

> 解释 LP 前先阅读 SKILL.md。说明变量、前提、目标和输入域假设，指出尚未指定的行为，并询问实现所需的决策。
>
> 使用【程序语言】实现规格。逐条将 LP 要求对应到代码、测试或证明义务。列出新增假设和规格适用域之外输入的处理方式。运行 LP 检查和相关程序测试，报告剩余诊断或反例，不要为了适应代码而悄悄修改规格。

将 LP 与实现一起维护。需求变化时，同步更新相关条款、代码与检查。

附带的[示例](examples/README.md)可作为直接运行的起点：

| 领域 | LP | 程序 |
| --- | --- | --- |
| 多组契约 | [quadruple.lp](examples/contracts/quadruple.lp) | [Python](examples/contracts/quadruple.py) |
| 算法 | [minimum.lp](examples/algorithms/minimum.lp) | [Python](examples/algorithms/minimum.py) |
| 数据处理 | [eligible_ids.lp](examples/data_processing/eligible_ids.lp) | [Python](examples/data_processing/eligible_ids.py) |
| 类与方法 | [point.lp](examples/classes/point.lp) | [Python](examples/classes/point.py) |
| 权限规则 | [can_read.lp](examples/access_control/can_read.lp) | [Python](examples/access_control/can_read.py) |
| 知识关系 | [function_properties.lp](examples/learning/function_properties.lp) | [Python](examples/learning/function_properties.py) |

## 使用 LP 学习知识

学习可以围绕同一个知识文件逐步积累：引入定义，记录假设与来源，再用例子和反例连接概念。

对于 `f(x) = x²`，可以让 AI 探索定义域与陪域如何影响单射和满射：

1. 定义域为整数时，`1` 与 `−1` 说明 `f` 不是单射。
2. 将定义域限制为非负整数，`f` 成为单射。
3. 陪域仍为所有非负整数时，`2` 没有原像，所以 `f` 不是满射。
4. 将陪域定义为像集 `f(D)`，则按构造，函数是到该像集的满射。

[学习示例](examples/learning/function_properties.lp)将映射、单射和满射定义为布尔性质。[对应程序](examples/learning/function_properties.py)演示有限输入域；有限测试不能证明无限输入域上的相应结论。

> 请帮助我学习【主题】，并维护一个 LP 知识文件。先引入词汇和范围。针对每个概念，提供 LP、自然语言解释、逻辑含义，以及例子或反例。区分定义、假设、已确立的结论和未验证猜想，并记录来源。
>
> 当我补充信息时，复用已有术语，展示修改和依赖关系，指出与旧假设的冲突。解释放在注释或配套文字中。运行源文本检查，解释诊断，不要将未证明的陈述标记为定理。

将文件纳入版本控制。注释和章节标签记录上下文，不代表证明状态。

## 类型系统

LP 采用**单一符号域上的软类型系统**。值、函数、谓词和用户概念都以符号表示，普通继承事实表达分类。一个符号可以有多个分类，不同类之间也不会自动互斥。

```lp
Value
double: _value => _out_value
    _out_value = _value + _value
```

这里 `_value` 和 `_out_value` 匹配可见类 `Value`。**输入分类是前提，输出分类是义务。** 声明要求输入具有 `Value` 分类，并保证输出具有该分类；源文本结构检查不证明这一保证。

声明 `Student` 后，`_student` 匹配 `Student`，`_students` 表示成员继承 `Student` 的集合，`_student_list` 表示成员继承 `Student` 的元组。以 `is_` 开头的名称，如 `_is_ready`，获得 `Bool` 分类。**名称推断影响契约：**新增一个可见类，可能改变原有推断。需要稳定分类时，应采用中性名称和显式继承。

例如，可以用显式分类限制规则：

```lp
Person
∀{| _x | Person ~ _x | can_enroll(_x)}
```

`Person ~ _x` 表示 `_x` 继承 `Person`；`Person ~ Student` 表示 `Student` 继承 `Person`。类声明、继承公理、名称查找规则，以及编辑器的 `class`／`func`／`pred`／`pure` 角色见双语[类型系统指南](docs/type-system.md)。

## 从 LP 理解逻辑

这些公式解释语义，并非当前编译器输出。它们省略辅助分类事实和绑定，并假设相应的输入域解释。LP 使用软类型、类似 HOL 的表示；适当的一阶片段可以写为 FOL，而函数对象和一般集合对象需要显式编码与公理。

<details>
<summary>展开 function、Class、field 与 method：表面语法 → 核心逻辑 → FOL</summary>

这些形式都是普通符号、继承事实、绑定和量化语句的语法糖。当前编译器输出 AST；下面的 FOL 是这些示例可采用的一种实体化一阶解释。使用 `Inherits(c, x)` 表示分类，`app1(f, x)`／`app2(f, x, y)` 表示应用；类名和可调用符号名在此编码中都是常量。假设 `Value` 具有预期的普通算术解释，省略辅助字面量事实和生成的临时变量。

**函数声明与函数体。** 签名贡献可调用符号分类和量化的输出保证；函数体贡献另一条具有自身前提的量化约束：

```lp
Value
increment: _value => _out_value
    | _value >= 0
    _out_value = _value + 1
```

展开为普通 LP 形式，可以简写为：

```lp
Value
Function ~ increment
∀{| _value, _out_value | Value ~ _value, _out_value = increment(_value) | Value ~ _out_value}
∀{| _value, _out_value | Value ~ _value, _out_value = increment(_value), _value >= 0 | _out_value = _value + 1}
```

主要的一阶事实和约束为：

```text
Inherits(Symbol, Value)
Inherits(Function, increment)
∀x,y. (Inherits(Value, x) ∧ y = app1(increment, x)) → Inherits(Value, y)
∀x,y. (Inherits(Value, x) ∧ y = app1(increment, x) ∧ x ≥ 0) → y = x + 1
```

签名的输出分类适用于 `Value` 输入，函数体的算术要求还需要 `x ≥ 0`。其他输入下，该函数体没有规定这一算术关系。多个函数体继续为同一个可调用符号增加约束。

**类声明。** `Point` 在前端注册可见类，并生成普通事实 `Symbol ~ Point`，此处写为 `Inherits(Symbol, Point)`。它不会在最终逻辑 AST 中引入独立的原始类结构；声明可见性仍是源文本规则。

**字段声明。** 当 `Value` 和 `Point` 可见时，`Point::x_value` 展开为 `x_value: _point => _x_value`，贡献：

```text
Inherits(Function, x_value)
∀p,v. (Inherits(Point, p) ∧ v = app1(x_value, p)) → Inherits(Value, v)
```

字段因此是接收者上的函数，`_point.x_value` 改写为 `x_value(_point)`。若写类字段等式 `Point::x_value = 0`，还会要求 `∀p. Inherits(Point, p) → app1(x_value, p) = 0`：它约束所有点的该字段，不是描述构造器默认值。

**方法声明与调用。** 上面的 Point 类体展开为普通函数声明：

```lp
Value
Point
x_value: _point => _x_value
y_value: _point => _y_value
shifted_x: (_point, _delta_value) => _out_value
    _out_value = x_value(_point) + _delta_value
```

合并方法的输出保证和函数体，主要约束为：

```text
Inherits(Function, shifted_x)
∀p,d,r. (Inherits(Point, p) ∧ Inherits(Value, d) ∧ r = app2(shifted_x, p, d)) →
        (Inherits(Value, r) ∧ r = app1(x_value, p) + d)
```

调用 `_point.shifted_x(_delta_value)` 变为 `shifted_x(_point, _delta_value)`，此处写为 `app2(shifted_x, p, d)`。接收者是第一参数，字段读取是一元应用。移除 `::`、`.` 和声明箭头后，其含义由分类、应用、等式和量词表达。

查看编译器包含生成符号的完整展开：

```sh
python scripts/expand_module.py examples/classes/point.lp
```

</details>

<details>
<summary>展开 quantified-stmt、set-stmt 和 image-set 转写示例</summary>

**Quantified-stmt** 表达全称规则或存在见证：

```lp
∀{| _x | human(_x) | mortal(_x)}
∃{| _x | human(_x), philosopher(_x)}
```

```text
∀x. Human(x) → Mortal(x)
∃x. Human(x) ∧ Philosopher(x)
```

**Set-stmt** 定义成员谓词：

```lp
{| _x | _x ∈ numbers, _x > 0}
```

将谓词命名为 `Positive`：

```text
∀x. Positive(x) ↔ (Numbers(x) ∧ x > 0)
```

**Image-set** 为每个输出引入合格的源见证：

```lp
{
    | _x
    _x ∈ numbers
    _x > 0
    => _x * _x
}
```

```text
∀y. Squares(y) ↔ ∃x. Numbers(x) ∧ x > 0 ∧ y = x × x
```

编译器将 image-set 展开为包含存在见证的集合。输入为 `{−2, 1, 2, 3}` 时，输出为 `{1, 4, 9}`。重复输出合并，不规定顺序。若将集合本身作为对象传递，在 FOL 中需要诸如 `Member(set, x)` 的编码。

</details>

双语[语义指南](docs/semantics.md)包含完整解释和蕴含反例。泛用片段省略了词汇声明；若要无诊断运行，请使用 `examples/` 中的文件。显式集合前提会产生 `set_stmt_premise` 警告。多行 image-set 形式可以避开当前对应内联筛选形式的诊断不一致问题。

## 安装 VS Code 扩展

扩展提供语法高亮、诊断、符号跳转和导入辅助。使用 Node.js 20+ 和 npm 打包本地 VSIX，运行扩展需要 VS Code 1.85+ 及快速开始中的 Python 环境：

```sh
cd tools/vscode
npm ci
npx vsce package --allow-missing-repository --out logic-language.vsix
code --install-extension ./logic-language.vsix
cd ../..
```

也可以选择 **扩展 → … → 从 VSIX 安装**。当前扩展从 `<workspace>/skills/logic-language/scripts/` 查找 Python 后端，应打开包含该路径的父工作区。独立检出的项目目前也需要这一布局。默认解释器在 Windows 上为 `py`，其他平台为 `python3`；需要时可通过 `logicLanguage.pythonPath` 修改。

工作区布局、Python 设置、启用检查与故障排查见[扩展指南](tools/vscode/README.md)。

## 当前能力

| 能力 | 状态 |
| --- | --- |
| 解析、展开、检查 LP，并编译为 JSON AST | 已实现。 |
| 从 AST 打印规范化 LP，提供编辑器辅助 | 已实现。 |
| 解释 LP、生成程序和测试、扩展知识 | 示例展示的 AI 辅助工作流。 |
| 通用 FOL/SMT 导出与自动正确性证明 | 附带工具尚未实现。 |

检查验证受支持的源文本和 AST 约定，测试检查选定的执行情况。二者都不能单独证明程序或知识断言正确。FOL 编码也不自动保证保留无限制 HOL 的完整语义或使推理可判定。

## 工具与验证

从项目根目录执行：

```sh
python scripts/compile_module.py examples/increment.lp --pretty
python scripts/expand_module.py examples/increment.lp
python scripts/compile_module.py examples/increment.lp --debug-stages
python examples/check_examples.py
```

编译器包含两个阶段：前端生成展开后的源 AST，后端生成最终对象 AST。[SKILL.md](SKILL.md)提供详细语言与 AI 使用说明，[grammar.ebnf](grammar.ebnf)描述模块结构，[semantic_logic/](semantic_logic/)用 LP 描述 AST 概念。

编译器开发检查：

```sh
python scripts/compile_pipeline/smoke_test.py
python scripts/validate_golden_tests.py golden_tests.md
python scripts/module_check.py --file standard_library.lp --pretty
```

[Golden tests](golden_tests.md)用于审查规范化展开。[标准库](standard_library.lp)必须没有错误；其中显式集合前提的蕴含警告应予以审查，而不应抑制。

## 许可证

项目及附带的 VS Code 扩展采用 [MIT 许可证](LICENSE)。

</details>
