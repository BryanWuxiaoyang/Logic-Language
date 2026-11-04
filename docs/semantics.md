# LP semantics

[README](../README.md) | [中文](#chinese)

Run command examples from the project root.

The following translations omit auxiliary classification facts and generated bindings. They assume the named vocabulary has its stated interpretation, including ordinary arithmetic and a universal `Symbol` domain.

### Quantified statements: rules and existence

“All humans are mortal”:

```lp
∀{| _x | human(_x) | mortal(_x)}
```

```text
∀x. Human(x) → Mortal(x)
```

“There is a human who is a philosopher”:

```lp
∃{| _x | human(_x), philosopher(_x)}
```

```text
∃x. Human(x) ∧ Philosopher(x)
```

**Premises mean implication, including under an existential quantifier.** The different statement below means `∃x. Human(x) → Philosopher(x)`:

```lp
∃{| _x | human(_x) | philosopher(_x)}
```

A nonhuman object can satisfy that implication. To require a witness satisfying both conditions, put both in the target conjunction, as in the preceding example.

### Set statements: define membership

```lp
{
    | _x
    _x ∈ numbers
    _x > 0
}
```

This denotes the positive members of `numbers`. A set is interpreted as a predicate; the abstraction is conceptually `λx. Numbers(x) ∧ x > 0`. If we name its membership predicate `Positive`, its first-order characterization is:

```text
∀x. Positive(x) ↔ (Numbers(x) ∧ x > 0)
```

When a set itself is passed as an object, a FOL backend would need an encoding such as `Member(set, x)` and additional axioms.

**A set premise is not a filter.** This expression has membership condition `x > 0 → x < 10`:

```lp
{| _x | _x > 0 | _x < 10}
```

It therefore also admits objects for which `x > 0` is false. To require both bounds, write:

```lp
{| _x | _x > 0, _x < 10}
```

The checker warns about explicit set premises with `set_stmt_premise`; it does not change their meaning.

### Image-set: filter, then transform

```lp
{
    | _x
    _x ∈ numbers
    _x > 0
    => _x * _x
}
```

Read this as “the squares of the positive members of `numbers`.” If the result predicate is `Squares`:

```text
∀y. Squares(y) ↔
    ∃x. Numbers(x) ∧ x > 0 ∧ y = x × x
```

An output belongs to the result exactly when some qualifying source object maps to it. The compiler expands an image-set into a set with an existential witness; it is not a separate core AST kind. Source variables remain inside the existential, and the outer set binds the output.

For input `{−2, 1, 2, 3}`, the result is `{1, 4, 9}`. Repeated outputs are one set member, and sets do not promise an order. These examples use the multiline form to keep filters visibly in the target section. The current checker can emit premise warnings for the analogous inline image-set form even when expansion puts those conditions in the target conjunction.

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

<a id="chinese"></a>

<details>
<summary>中文说明 / Read in Chinese</summary>

命令示例从项目根目录执行。

以下转写省略辅助分类事实和生成的绑定，假设命名词汇具有说明中的解释，包括普通算术，以及覆盖所有对象的 `Symbol` 域。

### quantified-stmt：规则与存在性

“所有人都会死亡”：

```lp
∀{| _x | human(_x) | mortal(_x)}
```

```text
∀x. Human(x) → Mortal(x)
```

“存在一位人类哲学家”：

```lp
∃{| _x | human(_x), philosopher(_x)}
```

```text
∃x. Human(x) ∧ Philosopher(x)
```

**前提表示蕴含，在存在量词下也是如此。** 下面这个不同的语句表示 `∃x. Human(x) → Philosopher(x)`：

```lp
∃{| _x | human(_x) | philosopher(_x)}
```

一个非人类对象就可能满足这个蕴含。若要求见证对象同时满足两个条件，应像前面的例子一样，将两个条件都放在目标合取中。

### set-stmt：定义成员条件

```lp
{
    | _x
    _x ∈ numbers
    _x > 0
}
```

它表示 `numbers` 中的正数。集合被解释为谓词，这个抽象可以理解为 `λx. Numbers(x) ∧ x > 0`。若将其成员谓词命名为 `Positive`，对应的一阶刻画为：

```text
∀x. Positive(x) ↔ (Numbers(x) ∧ x > 0)
```

如果集合本身作为对象传递，FOL 后端还需要诸如 `Member(set, x)` 的编码及补充公理。

**集合前提不表示筛选。** 下面的成员条件是 `x > 0 → x < 10`：

```lp
{| _x | _x > 0 | _x < 10}
```

因此，`x > 0` 为假的对象也满足这个条件。若要求同时满足上下界，应写成：

```lp
{| _x | _x > 0, _x < 10}
```

检查器会对显式集合前提给出 `set_stmt_premise` 警告，但不会改变其含义。

### image-set：筛选后映射

```lp
{
    | _x
    _x ∈ numbers
    _x > 0
    => _x * _x
}
```

理解为：“取 `numbers` 中正数的平方，形成输出集合。” 若将结果谓词命名为 `Squares`：

```text
∀y. Squares(y) ↔
    ∃x. Numbers(x) ∧ x > 0 ∧ y = x × x
```

输出值属于结果集合，当且仅当存在一个合格的源对象映射到它。编译器会将 image-set 展开为包含存在见证的集合，它不是独立的核心 AST 类型。源变量保留在存在量词内部，外层集合绑定输出。

输入为 `{−2, 1, 2, 3}` 时，输出为 `{1, 4, 9}`。重复输出只形成一个集合成员，集合不承诺顺序。这里采用多行形式，使筛选条件明确位于目标段。对于对应的内联映射集合形式，当前检查器可能给出前提警告，即使展开已将这些条件放入目标合取。

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

</details>
