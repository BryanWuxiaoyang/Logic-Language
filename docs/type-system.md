# Type system

[README](../README.md) | [中文](#chinese)

Run command examples from the project root.

LP uses **soft typing over a single symbol domain**. A value, a function, a predicate, and a user-defined concept are all represented by symbols. Classification is expressed with ordinary inheritance facts rather than a separate system of primitive static types. A symbol can have several classifications; different classes are not automatically disjoint.

### Explicit classification and inheritance

```lp
Person
∀{
    | _x
    | Person ~ _x
    can_enroll(_x)
}
```

`Person` declares a class symbol; `Person ~ _x` restricts the rule to objects inheriting `Person`. Using a first-order relation to represent inheritance, the main assertion reads:

```text
∀x. Inherits(Person, x) → CanEnroll(x)
```

The direction of `~` is parent first, inheritor second:

```lp
Person
Student
Person ~ Student
∀{| _student | enrolled(_student)}
```

Here `Student` inherits `Person`, and the binder `_student` receives a `Student` classification. With the reflexivity and transitivity axioms supplied by `standard_library.lp` in scope, a `Student` instance also inherits `Person`. These inheritance properties are logical axioms; they do not make `~` equality. Declare a class explicitly before using its name for implicit classification or class-member syntax; an inheritance fact alone does not declare it.

Common classifications include:

| Classification | Intended role |
| --- | --- |
| `Symbol` | General symbol domain. |
| `Value` | Numeric values; a particular integer or real interpretation needs additional domain assumptions. |
| `Bool` | Boolean results; the standard library classifies `true` and `false`. |
| `Function` | Callable symbols. |
| `Predicate`, `Set` | Truth-valued tests and set membership; sets are interpreted as predicates. |
| `Tuple`, `List` | Tuple and sequence forms; the standard library identifies `List` with `Tuple`. |
| `Char`, `String` | Character and string forms. |
| User classes such as `Person` | Domain concepts and their inheritance relationships. |

### Name-based inference reduces repeated annotations

When a class is visible in the current scope, an ancestor scope, or an import, the compiler can infer classifications from local names. With `Student` declared:

| Local name | Inferred classification |
| --- | --- |
| `_student`, `_student1`, `_selected_student` | `Student`. |
| `_students` | `Set`, with each member classified as `Student`. |
| `_student_list` | `Tuple`, with each member classified as `Student`. |
| `_is_ready` | `Bool`, using the built-in `is_` naming rule; no visible `Bool` declaration is required. |
| `_x` without an explicit classification | Falls back to `Symbol` when no class name matches, with an `implicit_inheritance_fallback_symbol` warning. |

The ordinary lookup strips trailing primes and digits, tries the remaining name, then removes leading underscore-separated segments to find a visible class. The longest matching candidate wins. Sibling nested scopes do not share local class declarations.

For example, this declaration requires a collection and a tuple of students, and specifies a Boolean output:

```lp
Student
inspect: (_students, _student_list) => _is_ready
    _is_ready = true
```

Name-based classification changes the logical contract; it is not merely a naming style. Adding a visible class can change the inference of an existing name. Use explicit inheritance with neutral variable names when the classification must be unambiguous, and inspect canonical source with `expand_module.py`.

### Function inputs are assumptions; output types are obligations

```lp
Value
double: _value => _out_value
    _out_value = _value + _value
```

The declaration adds `Function ~ double`. The input's inferred `Value` classification is a premise, while the output's inferred `Value` classification is a target guarantee. Combining the declaration and body, the main contract is:

```text
∀x,y. (Inherits(Value, x) ∧ y = double(x)) →
      (Inherits(Value, y) ∧ y = x + x)
```

The output classification must be established by the implementation or a proof; it is not assumed to make the contract true. For filtering a set by class, put the required classification in the target conjunction:

```lp
User
active_users = {
    | _x
    User ~ _x
    active(_x)
}
```

This requires both user classification and activity. A classification in a set's premise section has implication semantics, just like any other premise, and does not require every member to have that classification.

### Domain classifications and editor symbol roles

The editor's resolver distinguishes `class`, `func`, `pred`, and `pure` symbol roles using declarations, inheritance evidence, and use positions. These roles support highlighting, completion, and navigation; they differ from domain classifications such as `Value` or `Student`. For example, `Value` has a class role, `double` has a function role, and `_value` has a pure-symbol role while inheriting `Value`.

```sh
python scripts/resolve_sym_type.py --file example.lp --pretty
```

The checker validates supported syntax, naming, and structural conventions. It does not solve arbitrary inheritance constraints, prove that declared classes are consistent, or enforce runtime storage types. LP classifications provide logical assumptions and obligations for an AI, an implementation, or a future reasoning backend to examine.

<a id="chinese"></a>

<details>
<summary>中文说明 / Read in Chinese</summary>

命令示例从项目根目录执行。

LP 采用**单一符号域上的软类型系统**。值、函数、谓词和用户定义的概念都以符号表示。分类通过普通继承事实表达，不使用独立的原始静态类型体系。一个符号可以具有多个分类，不同类之间也不会自动互斥。

### 显式分类与继承

```lp
Person
∀{
    | _x
    | Person ~ _x
    can_enroll(_x)
}
```

`Person` 声明类符号；`Person ~ _x` 将规则限制在继承 `Person` 的对象上。用一阶关系表示继承时，主要断言为：

```text
∀x. Inherits(Person, x) → CanEnroll(x)
```

`~` 的方向是父类在前、继承者在后：

```lp
Person
Student
Person ~ Student
∀{| _student | enrolled(_student)}
```

这里 `Student` 继承 `Person`，绑定变量 `_student` 会获得 `Student` 分类。当作用域中包含 `standard_library.lp` 提供的自反性和传递性公理时，`Student` 的实例也继承 `Person`。这些继承性质是逻辑公理，并不将 `~` 变成等号。若要通过类名推断分类或使用类成员语法，应先显式声明该类；单独的继承事实不会声明类。

常见分类包括：

| 分类 | 预期作用 |
| --- | --- |
| `Symbol` | 通用符号域。 |
| `Value` | 数值；具体采用整数或实数解释，需要补充输入域假设。 |
| `Bool` | 布尔结果；标准库为 `true` 和 `false` 提供分类事实。 |
| `Function` | 可调用符号。 |
| `Predicate`、`Set` | 真值判定与集合成员关系；集合被解释为谓词。 |
| `Tuple`、`List` | 元组与序列形式；标准库将 `List` 与 `Tuple` 等同。 |
| `Char`、`String` | 字符与字符串形式。 |
| `Person` 等用户类 | 领域概念及其继承关系。 |

### 从名称推断分类，减少重复标注

当类在当前作用域、祖先作用域或导入中可见时，编译器可以根据局部名称推断分类。以已经声明的 `Student` 为例：

| 局部名称 | 推断出的分类 |
| --- | --- |
| `_student`、`_student1`、`_selected_student` | `Student`。 |
| `_students` | `Set`，且每个成员具有 `Student` 分类。 |
| `_student_list` | `Tuple`，且每个成员具有 `Student` 分类。 |
| `_is_ready` | 根据内置 `is_` 命名规则推断为 `Bool`，不要求显式声明 `Bool`。 |
| 没有显式分类的 `_x` | 找不到匹配类名时退回 `Symbol`，并产生 `implicit_inheritance_fallback_symbol` 警告。 |

普通查找会移除名称末尾的撇号和数字，先尝试剩余名称，再逐步移除下划线分隔的前缀以查找可见类。最长的匹配候选优先。相邻的嵌套作用域不共享各自的局部类声明。

例如，下面的声明要求输入为学生集合和学生元组，并规定输出具有布尔分类：

```lp
Student
inspect: (_students, _student_list) => _is_ready
    _is_ready = true
```

名称推断会改变逻辑契约，不只是命名风格。新增一个可见类，可能改变已有名称的推断结果。当分类必须明确时，建议使用中性变量名和显式继承事实，并通过 `expand_module.py` 检查规范化源文本。

### 函数输入是前提，输出类型是义务

```lp
Value
double: _value => _out_value
    _out_value = _value + _value
```

声明会添加 `Function ~ double`。输入推断出的 `Value` 分类是前提，输出推断出的 `Value` 分类是目标保证。合并声明和函数体后，主要契约为：

```text
∀x,y. (Inherits(Value, x) ∧ y = double(x)) →
      (Inherits(Value, y) ∧ y = x + x)
```

输出分类需要由实现或证明建立，不能将其直接当成假设使契约成立。若要按类筛选集合，应将要求的分类放在目标合取中：

```lp
User
active_users = {
    | _x
    User ~ _x
    active(_x)
}
```

它同时要求用户分类和活跃状态。放在集合前提段中的分类与其他前提一样采用蕴含语义，并不要求每个成员都具有该分类。

### 领域分类与编辑器的符号角色

编辑器的解析器结合声明、继承证据和使用位置，区分 `class`、`func`、`pred` 和 `pure` 符号角色。这些角色用于高亮、补全和跳转，与 `Value`、`Student` 等领域分类不同。例如，`Value` 的角色是类，`double` 的角色是函数，而 `_value` 的角色是普通符号，同时具有 `Value` 分类。

```sh
python scripts/resolve_sym_type.py --file example.lp --pretty
```

检查器验证受支持的语法、命名和结构约定，不求解任意继承约束，不证明类定义的一致性，也不强制运行时存储类型。LP 的分类为 AI、程序实现或未来推理后端提供需要审查的逻辑假设和义务。

</details>
