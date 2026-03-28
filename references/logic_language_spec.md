# SPEC for `.lp` Logic Program

This document defines the required syntax and semantics for logic program files with postfix `.lp`.
LLM outputs that target this format must follow these rules.

# Function
- A `function` or `func` or `f` represents a 1-1 mapping from a `function` to another `function`.
- Written form `function: in_arg => out_arg` represents all possible `functions` that takes in_arg and output out_arg, under certain `conditions`.

- When 2 written `function` has same name, they are same function.

# Symbol
- `symbol` is identical to `function`
So a `function` represents a 1-1 mapping from a `symbol` to another `symbol`

# intrinsic symbols
- `null`, `true`, `false`, `bool`
- `condition-function`, `=`, `≠`, `&&`
- `~`
- `tuple`
- `set`, `∩`, `∈`
- `set_cond`, `∀`, `∃`
- `class`

# condition-function
- A `condition-function` or `cond` is a `function` that maps a symbol to `true`/`false`: `cond: in_sym => bool_sym`
- `true_cond: sym => bool_sym`, for all `sym`, `true_cond(sym) = true`
- `false_cond: sym => bool_sym`, for all `sym`, `false_cond(sym) = false`
- `=` is a `cond`, `=: (sym1, sym2) => bool_sym`, `bool_sym = true` iff `sym1` and `sym2` represent same symbol
- `≠` is a `cond`: `≠: (sym1, sym2) => bool_sym`. `bool_sym = false` iff `sym1 = sym2`
- `!` is a `cond`: 
  - `!: bool_sym1 => bool_sym2`. `bool_sym2 = true` iff `bool_sym1 = false`
  - `!: cond1 => cond2`, For any `sym`, `cond2(sym) = !cond1(sym)`
- `&&` is a `cond`: `&&: {bool_sym1, bool_sym2} => bool_sym3`. `bool_sym3 = true` iff `bool_sym1 = true` and `bool_sym2 = true`.

# inheritance(~)
- `~` represents a `cond`: `~: (sym1, sym2) => bool_sym`
- `bool~true = true`, `bool~false = true`
- When writing a `symbol-name` as a function in_arg/out_arg, and the `symbol-name` is already declared in previous statements, it instead declares `symbol` that inherits the `symbol-name`.
  - E.g.
    ```text
    A
    f: A => A1
    ```
    `f` declare a mapping that maps `A~in_arg` to `A~out_arg`

# tuple
- A `tuple` represents a function `tuple: id => sym`

- Written form `(a, b)` represents: 
  - `tuple~(a,b)`, 
  - `(a, b)(0) = a`, `(a, b)(1) = b`
  - For `n ≠ 0 or 1` => `(a, b) = null`

- When a `function`'s in-arg and out-arg are tuples, it's written as:
`function: (in_arg1, in_arg2) => (out_arg1, out_arg2)`

- When calling a `function` with tuple as in-arg, we can ignore the duplicate `()`: `f(a, b) = f((a, b))`

# set
- A `set` is identical to `cond`: `set: sym => bool_sym`, `set = cond`. So `set` share same usage patterns as `cond`.

- `∈` represents a `cond`: `∈: {sym, set1} => bool_sym`, that `sym ∈ set1 = set1(sym)`

- `∩` represents a `function`: `∩: (set1, set2) => set3`, `set~set1`, `set~set2`, `set3(sym) = set1(sym) && set2(sym)`

- `full_set = true_cond`, `set~full_set`
  - Written form `{*} = full_set`

- `empty_set = false_cond`, `set~full_set`
  - Written form: `{} = false_set`

- Written form `{a, b}`: 
  - `set~{a, b}`
  - `{a, b}(a) = true`, `{a, b}(b) = true`
  - For `sym ≠ a or b`, `{a, b}(sym) = false`

- When a literal set is a single in-arg for a function, it can ignore the `()`. E.g. `f({1, 2}) = f{1, 2}`

- Written form: `{ | cond }` represents: `set~{| cond}`, `{| cond} = cond`.
  - E.g. `{| sym > 0 }` represents a `set'` that:
    - `set~set'`
    -  `set'(sym) = (sym > 0)`
-  Written form: `{| sym }`
  - `{| sym } = empty_set` if `sym = false`
  - `{| sym } = full_set` if `sym = true`
  - `{| sym } = sym` if `cond~sym`. i.e. `sym` represents a `cond`, which is identical to `set`
  - `{| sym } = full_set` if `!bool~sym` and `!cond~sym`

-  Written form: `{| cond2 | cond1}` represents a `set'` that is the `∩` of 2 sets: `{| cond2 | cond1} = cond2' ∩ cond1'`, where `cond2'` and `cond1'` have same predicates as `cond2` and `cond1`, but in-args are aggrated from in-args of both `cond2` and `cond1`
   - `,` is identical to `|`, but inner-order is reversed. e.g. `{x, y, z} = {| z | y | x}`
   -  E.g. `{| sym2 > 0 | sym1 > 0 | sym1, sym2 }` represents:
      -  Expand `,` to: `{sym2 > 0 | sym1 > 0 | sym2 | sym1}`
      -  Derive `in_args` from right-to-left: `(sym1, sym2)`
      -  Derive to 4 sets:
         - `set1 = {| sym1 > 0}: (sym1, sym2) => bool_sym`
         - `set2 = {| sym2 > 0}: (sym1, sym2) => bool_sym`
         - `set3 = {| sym2}: {sym1, sym2} => bool_sym = full_set`
         - `set4 = {| sym1}: {sym1, sym2} => bool_sym = full_set`
      - `set' = set1 ∩ set2 ∩ set3 ∩ set4`. i.e. `set'(sym1, sym2) = true` iff `sym1 > 0, sym2 > 0`
    - E.g. if `integer~x, integer~y`, `{| y < 3 | y > 0 | x = 0 | x, y } = {(0, 1), (0, 2)}`
    - Written form can be expand to multi-lines, read from bottom-up.
      - E.g. `{| cond3 | cond2 | cond1}` = 
        ```text
            {
                | cond3
                | cond2
                | cond1
            }
        ```
    - Theorem: Different ordering of `conds` represents same set: `{| cond2 | cond1} = {| cond1 | cond2}`

- `apply: (set, f) => set1`, it maps every `sym ∈ set` through `f` into `set1`
  - For all `sym`: `apply(set, f)(sym) = { | sym'' = f(sym') | sym' ∈ set }`
- Written form: `{f | cond}` is a `mapped_set`. It represents a `set'` that derives from `{| cond }` applied on `f`.
  - For any `sym`, `{f | cond}(sym) = ({| sym = f(sym') | sym' ∈ {| cond} } ≠ {})`
  - The symbols used in `f` must appear in `conds`. Otherwise it is invalid.
  - E.g. if `integer~x`, `{ x + 1 | x < 3 | x > 0 | x } = {2, 3}`
  - Written form can expand to multi-lines, read from **bottom-up**.
    - E.g. `{f | cond4 | cond3 | cond1, cond2}` = 
        ```text
            { f
                | cond4
                | cond3
                | cond2
                | cond1
            }
        ```

# ∀/∃ cond
- `∀` and `∃` are `set_conds`, which are `cond` that takes a `set` as in_arg.
- 
- `∃` is a `cond`: `∃: set => bool_sym`. `∃(set) = (set ≠ {})`
  - `set~∃`. `∃` represents a `set` that stores all non-empty sets.
  - E.g. if `integer~x`, `∃{| x < 3 | x > 0} = ∃{1, 2} = true`

- `∀` is a `cond`: 
  - `∀: set => bool_sym`. `∀(set) = (false ∉ set)`
    - `set~∀`, `∀` represents a `set` that doesn't contain `false`.
    - E.g. if `integer~x`, `∀{ x > 0 | x > 1} = ∀{true} = true`, `∀{ x < 3 | x > 0} = ∀{true, false} = false`, `∀{} = true`
  - `∀: (target_cond, premise_cond) => bool_sym`

- Written form: `∀{target_cond | premise_cond} = ∀(target_cond, premise_cond)`

- Written form of `∀{target_cond | premise_cond}` can expand to multi-lines without `{}`, read from **top-down**:
  - Each line after `∀` should be indented
  - E.g. 
    ```text
    ∀{ target_cond | cond2 | cond1 }` = 
    ∀
        | cond1
        | cond2
        target_cond
    ```
  - `,` in `target_cond` splits a `set_cond` into multiple `sub_set_conds`.
    - E.g. `∀{ target_cond1, target_cond2 | cond } = ∀{target_cond1 | cond} && ∀{target_cond2 | target_cond1 | cond}`
    - Note: it's not identical to `&&`, the second `sub_set_cond` introduces `| target_cond1`
  - multiple `target_cond` can appear alternately between `premise_cond`:
    - E.g.
        ```text
        ∀
            | cond1
            target_cond1, target_cond2
            | cond2
            target_cond3
        =
        ∀
            | cond1
            | cond2
            target_cond1
        &&
        ∀
            | cond1
            | cond2
            | target_cond1
            target_cond2
        &&
        ∀
            | cond1
            | cond2
            | target_cond1
            | target_cond2
            | cond3
            target_cond3
        ```
  - A `set_cond` expression can be branched with `|-`. It is identical to multiple splited `set_conds`, each represent a branch.
    - E.g.
        ```text
        ∀
            | cond1
                |- branch_cond1
                    | cond2
                    target_cond1
                |- branch_cond2
                    | cond3
                    target_cond2
            target_cond3
        =

        ∀
            | cond1
            | branch_cond1
            | cond2
            target_cond1
            target_cond3
        &&
        ∀
            | cond1
            | branch_cond2
            | cond3
            target_cond2
            target_cond3
        =

        ∀
            | cond1
            | branch_cond1
            | cond2
            target_cond1
        &&
        ∀
            | cond1
            | branch_cond1
            | cond2
            | target_cond1
            target_cond3
        &&
        ∀
            | cond1
            | branch_cond2
            | cond3
            target_cond2
        &&
        ∀
            | cond1
            | branch_cond2
            | cond3
            | target_cond2
            target_cond3
        ```
  - All the condition semantics described above can be nested together to generate a condition.

    E.g.
    ```text
    ∀
    | cond1
        |- branch_cond1
            | cond2
            target_cond1
                |- branch_cond1_1
                    target_cond1_1
                |- branch_cond1_2
                    target_cond1_2
        |- branch_cond2
            | cond3
    target_cond2
    ```
    To fully decompose the `set_cond`, first decompose `branch-conds` to split into multiple `sub_set_conds`. Second, for each `sub_set_cond`, decompose `target_cond` to split into `sub_sub_set_conds`. Finally gather all `sub_sub_set_conds` as the decomposed result.

- Theorem
  - `∃{| cond2 | cond1} = !∀{ !cond2 | cond1} = !∀{ !cond1 | cond2 }`
  - `!∃{| cond2 | cond1} = ∀{ !cond2 | cond1 } = ∀{ cond1 | cond2 }`
  - `∀{target_cond | premise_cond | ∀{target_cond | premise_cond}} = true`
  - `∀{ x > 2 | x > 3} = true`
  - `∀{ x > 1| x > 2} = true`

# syntax sugar: cond nested in function
- A `cond` can be nested inside a `function`. The `function`'s in_arg and out_arg will be implicit `premise_conds`.
  - E.g.
  ```text
    add: (v1, v2) => v
        ∀{ v = add(v1, v1) | v1 = v2 }
    ```
    is identical to
    ```text
    add: (v1, v2) => v

    ∀ { v = add(v1, v1)
        | v1 = v2
        | v1, v2, v = add(v1, v2)}
    ```
- The `out_arg` of `function` must satisfy all `conds` defined on it.
- The nested `conds` is represented same as expanded-layout condition. 
  - E.g.
    ```text
    add: (v1, v2) => v
        v = v1 + v2
        ∀{ v = add(v1, v1) | v1 = v2 }
    ```
    is identical to a function declaration + nested `conds`:
    ```text
    add: (v1, v2) => v

    ∀
        | v1, v2, v = add(v1, v2)
        v = v1 + v2
        ∀{ v = add(v1, v1) | v1 = v2 }
    ```

- A function can be declared multiple times with same name in the program. The function should satisfy all the conditions.
  - E.g.
    ```text
    add: (v1, v2) => v
        v = v1 + v2
    add: (v1, v2) => v
        ∀{ v = add(v1, v1) | v1 = v2 }
    ```
    is identical to:
    ```text
    add: (v1, v2) => v
        v = v1 + v2
        ∀{ v = add(v1, v1) | v1 = v2 }
    ```

- Function prerequisites on `input_args` should be written as `| cond`. This means the declaration only applies under the current prerequisite. If there is another definition of the same function with a different prerequisite, the two definitions remain compatible.
  - E.g.
    ```
    get_mid: (v1, v2) => v
        | v1 < v2
        v = (v1 + v2) / 2

    get_mid: (v1, v2) => v
        | v1 > v2
        v = get_mid(v2, v1)
    ```
    if `v1 < v2` and `v1 > v2` are not pre-requisite-conds, there will be `cond`:
    ```
    ∀{ v1 > v2, v1 < v2
        | v1, v2, v = get_mid(v1, v2)
    } = false
    ```

# class
- `class` is same as `symbol`
- ``


# proof of program
- A program is proved iff all expanded statements are `true`.
  E.g.
  ```text
  ∀{ x > 2 | x > 0 }
  ```
  is a `wrong` program because `∀{ x > 2 | x > 0 } = false`

### 1.4 Inheritance
There is an intrinsic inheritance function `~: (parent_symbol, sub_symbol) => bool`
It itself is undefined, but it is used to define conditions that the sub-item satisfies all conditions on parent-item.
It satisfies:
`∀{ sym~sym | sym }`
`∀{ sym1~sym3 | sym1~sym2, sym2~sym3 | sym1, sym2, sym3 }`
`∀{ !∀{sym2~sym1} | sym1~sym2 | sym1, sym2, sym1 ≠ sym2 }`

E.g.
```
val
one
val~one
add: (sym1, sym2) => sym3
    | val~sym1
    | one~sym2
    val~sym3
    sym3 = sym1 + 1
```
It declares 2 symbols `val` and `one`, and `val~one`. And defined `add` function with inheritance conditions.

#### 1.4.1 Cyclic Inheritance
When `sym1~sym2` and `sym2~sym1` we use `sym1~sym2~sym1` or `sym1 = sym2`. It means the 2 symbols are identical.
It satisfies:
`∀{ sym2~sym3 | sym1~sym3 | sym3 | sym1 = sym2 }` 
`∀{ sym3~sym2 | sym3~sym1 | sym3 | sym1 = sym2 }` 

If multiple symbols are identical, when call it `identical-symbol-group`.

### 1.5 Classes

`class` is formally defined intrinsically same as `symbol`, just with some special conventions or syntax-sugars in function-declarations and function-usages.

#### 1.5.1 Symbol Naming Convention on Class
In function declaration or condition-statements, when the symbol-name is named as `{prefix}{class}` or `{class}{digits}`, it implicitly contains a condition that symbol inherits this class.

E.g. 
`f: (class1, class2) => class3` is identical to
```text
f: (class1, class2) => class3:
    | class~class1
    | class~class2
    class~class3
```
Which means when the input_args are all inheriting `class`, then output_arg also inherits `class`.

If name `class` is used as argument in function-declaration, it is refering to a symbol inheriting this `class`, instead of `class`-symbol itself. Then within this function-scope all conditions referencing `class` is indicating this argument instead of `class`-symbol.
E.g.
```
A
function: A1 => A
    A~A1
```
is identical to
```
A
function: sym1 => sym
    | A~sym1
    A~sym
    sym~sym1
```
`A~A1` is identical to `sym~sym1`, which is not as expected.
Therefore we should use `class` as argument only if within the scope there is no direct use of `class`, e.g. `class~symbol`. Otherwise it will not be interpreted as class-symbol inheritance, instead of symbol-symbol inheritance.

- Note: function-declaration can't take declared-symbol as argument.

If name `class` is used as argument in a condition-statement, it is refering to `class` itself instead of a symbol inheriting `class`. 
E.g. 
Given 
```
A
B
A~B
```
Then
`∀{ B~A1 | A1 = B1 | B1 }` is different from `∀{ B~A | A = B | B }`. 
`∀{ B~A1 | A1 = B1 | B1 }` is identical to
```
∀{ B~A1
    | A1 = B1
    | B~B1
    ｜ A, B, A~B
}
```
It defines conditions on symbols inheriting `B`.

`∀{ B~A | A = B | B }` is identical to
```
∀{ B~A
    | A = B
    | B
    | A, B, A~B
}
```
It defines conditions on `class`-symbols themselves. And this statement is always `true` because `A=B` implies `B~A`.

#### 1.5.2 Class Member Functions

A class can have member functions.
E.g.
`class::f: (class1, in_arg) => out_arg`

Member functions are formally defined as a function with its first input_arg as  `class1`. So it implicitly contain the premise-condition that first symbol inherits `class`.
E.g.
`class::f: (class1, in_arg) => out_arg`
is identical to:
```text
f: (symbol, in_arg) => out_arg
    | class~symbol
```

A method's name is formally defined as `member-function-name` itself, not `class::member-function`. Therefore if 2 classes both has method `f` and same arity, then the 2 methods are same. I.e. `classA::f = classB::f`.

- By defining so, sub-class can be put as first-argument in paren-class's methods. Dynamic dispatching on inheritance is achieved.

Member-function can be declared in class-scope:
E.g.
```text
class
    ::f1: (class, in_arg) => out_arg
    ::f2: (class, in_arg) => out_arg
```
It declared `class`, `class::f1`, `class::f2`.

When calling member-function on a symbol `symbol` with `class~symbol`, `symbol.f(in_arg)` is identical to `class::f(symbol, in_arg)`

When a symbol inherits `class`, `symbol.f` is a function:
```text
    ∀{ sym.f(in_args) = class::f(sym, in_args)
        | in_args
        sym.f: in_args => out_args
        | class~sym
    }
```

#### 1.5.3 Class Member Field
A class can have fields
`class::field: class => field`
or simply
`class::field` if the field's class is clear

field is formally defined as a member function.

#### 1.5.4 Class Inheritance

Because `class` is `symbol`, classes can also inherits each other.

E.g.
```text
A
f: A1 => bool
    bool = true
A~B
∀{ f(symbol) = true
    | B~symbol
    | symbol }
```
can be expanded to identical form:
```text
A
f: symbol => bool
    | A~symbol
    bool = true
B
A~B
∀{ f(symbol) = true
    A~symbol
    | B~symbol
    | symbol }
```

If sub-class declares a member-function with the same name and signature as parent-class, then the 2 member-functions are the same function.
E.g.
```text
A~B
A::f: (A, v) => v1
    v1 > v
B::f: (B, v) => v1
    v1 = v + 1
```
`A::f` and `B::f` are the same function, becuase they both have same name 'f', 2 in_args, and 1 out_arg. The conditions applied on 2 member-functions are merged in this single funciton. It is identical to
```text
f: (symbol, v) => v1
    ∀
        |- A~symbol
            v1 > v
        |- B~symbol
            v1 = v + 1
```
Because `A~B` and `B~symbol`, it can further expand to:
```text
f: (symbol, v) => v1
    ∀
        |- A~symbol
            v1 > v
        |- B~symbol
            v1 > v
            v1 = v + 1
```

Deduced from formal definition, the inherited class implicitly can feed into all member-functions from parent-class.
E.g.
```text
A
    ::val
    ::f: (A, A1) => v
        v = A.val + A1.val
A~B
    ::val
        val = 1
∀{ v = B1.val + B2.val = 2
    | v = B1.f(B2)
    | B1, B2 }
```
is identical to
```text
∀{ v = 1 + 1 = 2
    B::val(B1) = 1, B::val(B2) = 1
    v = B::val(B1) + B::val(B2)
    A::val = B::val
    v = A::val(B1) + A::val(B2)
    A~B1, A~B2
    v = B::f(B1, B2) = A::f(B1, B2)
    | v = B1.f(B2)
    | B1, B2}
```
Because `A::f = B::f` and `A::val = B::val`, we are able to formally deduce that `B1.f(B2) = B1.val + B2.val`.

- In semantics it implements OOP language features: if `A~B`, then `B` inherits all member-functions and conditions from `A`.

- A class can inherit from multiple parent-classes, inheriting all the function declarations and conditions from the parent-classes.
E.g.
```text
A::val
    val > 0
B::val
    val < 2
C
A~C
B~C
```
Then `A::val = B::val = C::val`, `∀{C.val > 0, C.val < 2}`.

#### 1.5.5 Cyclic Inheritance
Same as cyclic inheritance on symbols, when `A~B~A`, then `A` and `B` are identical classes.

E.g.
```
A
    ::val
B
    ::vals
A~B
    ::vals = {B.val}
B~A
    ::val = *A.vals
```
is identical to
```
A
    ::val = *{A.vals}
    ::vals = {A.val}

B
    ::val = *{B.val}
    ::vals = {B.val}
```
Then we say `A` and `B` are identical because they will have exactly same conditions in any functions.

- Note that because of condition inheritance rule, class-inheritance can only go from general-class to specific-class. E.g. `B::vals` can only hold 1 value, instead of arbitrary size.
E.g. 
```
val_set::val: v => bool
        bool = ∀{val = v}
```
is valid for `val` to represent a `val_set` class.
But inversely `val::val_set` is invalid because `val_set` can have arbitrary vals.

If multiple classes are identical, e.g. `A~B`, `B~A`, `B~C`, `C~B`, we say there is a identical-class-group `{A,B,C}`.

#### 1.5.6 Class Constructor
A class can have a special constructor function declared in it:
```text
A
    ::__init__: (in_arg1, in_arg2) => A1
```
So statement `A1 = A::__init(in_arg1, in_arg2)` is returning `A` symbol from `A::__init__` function.

Different from normal member-functions, the constructor's function-name is `{class}::__init__` instead of `__init__`, therefore classes' constructors are different from each other.
Otherwise, it would be identical to:
```
A::__init__: in_arg => A
B::__init__: in_arg => B

__init__: in_arg => out_arg
    A::out_arg
    B::out_arg
```
This `__init__` function will have condition that out_arg inherits both classes, which is definited not as expected.

#### 1.5.7 Class Call Function
A class can have a class-call-function as member function:

`A::__call__: (A, in_arg) => out_arg`
or
```text
A
    : (A, in_arg) => out_arg
```
It's defined same as other member-functions.

So statement `out_arg = A(in_arg)` is using function `A::__call__`.

#### 1.5.8 Condition in Class
In the class scope there can be conditions. The conditions will have this class as implicit premise_cond.
E.g.
```text
A
    ::val
    ∀{A.val = 1}
```
is identical to
```text
A
    ::val
    ∀{ A.val = 1 | A}
```

#### 1.5.9 Enum Class
There is no real-enum-classes. Instead we can declare a `class` and a set of `sub-classes` to represent enums.

E.g.
```text
type
type~type1
type~type2

A
    ::type: A => type

    ::is_type1: A => bool
        bool = ∀{A.type = type1}
```
It first declared a class named 'type'. Then declared 2 sub-classes `type1` and `type2`.

- in `bool = ∀{A.type = type1}`, Although `bool = A.type = type1` is valid. For readability, it's recommended to write as `bool = (A.type = type1)`(here `()` defines operator precedence, not `tuple`) or `bool = ∀{A.type = type1}`

### 1.6 Condition Deduction and Paradox
 TODO:

### 1.7 Comments
Comments are prefixed with '#'. It doesn't participate in the program semantic, just use a more natural way to describe the program parts.

### 1.8 Topic Headings
Topic headings are prefixed with '@'. It doesn't participate in the program semantic. It's used to organize the program for better readability. All contents inside the heading should be indented by 1 level.

### 1.9 Module Import
Other `.lp` modules can be imported by `$import {module_path}`. It's copies in all content from `{module_path}`. It will recursively introduce all classes and functions defined in `module_path`.

When accessing items in the `module_path`, we can either directly use item-name if it doesn't cause ambiguity, or use `{module_name}::{item-name}`.

### 1.10 Chained Comparison
A comparison condition can be chained.
E.g. `∀{ 0 < x < 3 ｜ x}` is identical to `∀{0 < x, x < 3 | x}`

### 1.11 Recursive Function Definition
A function condition may contain function-itself. This is a recursive definition. The condition is valid if it can be proved through induction. I.e. when sub-function satisfies all other conditions except this recursive condition, the function can be deduced to satisfy those conditions as well.

E.g.
```text
add: (v1, v2) => v
add: vals => v
    v = sum{ vals[i] | i ∈ [0: vals.size]}

    ∀
        |- vals.size = 1
            v = vals[0]
        |- vals.size > 1
            | v' = add(vals[1:])
            v = vals[0] + v'
```
In this example, `add(vals)` has a condition that is recursively defining `add`. We can deduce that when `add(vals[1:]) = sum{ vals[i] | i ∈ [0: vals.size]}`, then `add(vals)= sum{ vals[i] | i ∈ [0: vals.size]}` satisfies.

### 1.12 Indentation Rules
- All contents in a `@topic heading` is indented by 1 level.
- All conditions in a `function` or `class` declaration is indented by 1 level.
- Multi-line expanded condition is indented by 1 level.
E.g.
```text
∀
    ｜ cond1
    cond
```
- branch condition is indented by 1 level
E.g.
```text
∀
    | cond1
        |- branch_cond1
            target_cond1
        |- branch_cond2
            target_cond2
```

### 1.13 Alias Function Name
A function can have alias name or operator. The alias name is wrapped in brackets after the full name.
E.g.
```text
full_name_function(short_name_f): in_arg => out_arg
```
Then we can use both full-name or short-name to refer to this function

The operator chars can also be used as function name, and it will overload intrinsic operator.
E.g.
```text
A
    ::add(+): (A, A1) => A2
```
This function overrload '+' operator. We can use `A + A1` to refer to `A.add(A1)`.

### 1.14 Lambda Function
A function can be anonymously define inline with `->`.

The function's declaration and the condition constraining the output_arg can be defined with `->` statement.
E.g. `in_arg -> f(in_arg)` is identical to 
```text
lambda_function: in_arg => out_arg
    out_arg = f(in_arg)
```

- All lambda functions are not same with each other. I.e. assume they are given different names.

- When A lambda function is assigned to a function, it first defines the lambda function, the define a condtion indicating this `function` is identical to lambda funciton.
E.g.
```text
function: x => y
function = x -> f(x)
```
is identical to
```text
function: x => y
    y = f(x)
```

E.g.
```text
A
    ::function = (A, x) -> f(A, x)
```
is identical to
```text
A
    ::function: (A, x) => y
        y = f(A, x)
```

- Note that `->` declares a lambda function + an output condition on it, and `=>` only declares the function.

- If member-function is a field, we can further reduce to `class::field = val`.
E.g. 
Given `A::base_val: A => base_val`, then
```text
A::val: A => val
    val = A.base_val + 1
```
is identical to
`A::val = A -> A.base_val + 1`
is identical to
`A::val = A.base_val + 1`

### 1.15 Symbol naming conventions
The symbol-name inherently imply its inherited class.
- `{prefix}_{class}`, `{class{digit}}`, `{class}_{digit}` represent a symbol inheriting `class`.
- `{class}s` is a set/list of symbols inheriting `class`. E.g. `vals`. It can be either set or list, depending on the context.
- `{class}_list` is a list of symbols inheriting `class`
- nested naming from above rules.
- `{classA}_to_{classB}_map` or `{classA}_to_{classB}_f` is a function-mapping from classA to classB. E.g. `key_to_value_map`
- `{arbitrary_name}_f` represents a function symbol which is declared in the scope explicitly.

### 1.16 `else` condition in branch-condition
When in branch-condition `|-`, `|- else` is allowed when the remaining condition is trivial and verbose.

E.g.
```text
∀
    | x, y = -x
        |- x > 0
            y < 0
        |- x = 0
            y = 0
        |- else
            y > 0
```
is identical to
```text
∀
    | x, y = -x
        |- x > 0
            y < 0
        |- x = 0
            y = 0
        |- x < 0
            y > 0
```

### 1.17 Function as the only first-class member
In formal semantics, all items are intrinsically `functions`.
- `symbol` is intrinsically `functions`
- `set` is intrinsically `function`: `set: symbol => bool`
- `condition-functions` is a `function`: `condition-function: in_args => bool`
- `∀`/`∃` statements are `condition-functions`
- `class` is intrinsically `symbol`
- inheritance of `class~symbol` is defined upon function `~`.
- `class-member-function` is intrinsically `function`, with first-arg inheriting `class`.
- class inheritance is defined upon function `~`

### 1.18 Intrinsics
There are many intrinsic classes/functions defined in `@/references/standard_library.lp`. All `*.lp` files will implicitly import it.

#### 1.18.1 intrinsic `condition` Function
There is a intrinsic `condition({args}, "desc")` function. It describes a condition with natural language in `"desc"` that includes symbols in `{args}`.

`condition("desc")` describes a condition with `"desc"`, All available symbols in current scope are in `{args}` implicitly.

`condition` function is used to replace condition statements when condition is trivial or complicated or out-of-doman-knowledge-scope or difficult-to-write-in-plain-logic.

It's different from Comments. It has semantic meaning on the program.

E.g.
```text
add: (v1, v2) => v
    # v is the sum of v1 and v2
```
declares a function `add` but doesn't add condition constraint on it. So output `v` has no relation with inputs.

```text
add: (v1, v2) => v
    condition("v is the sum of v1 and v2")
```
is identical to
```text
add: (v1, v2) => v
    v = v1 + v2
```

#### 1.18.2 Intrinsic symbols
- `null` value
When a function's output-args doesn't satisfy any conditions, or the output-arg is explicitly set to `null`, the output-arg is `null`.
E.g.
```
f: v => v1
    |- v > 0
        v1 = v
    |- v = 0
        v1 = null
```
Then `f(-1) = null`, `f(0) = null`.

### 1.19 set as only in-arg
Syntax Sugar: If in a function-call, a set is the only in-arg, we can merge `({})` into `{}`. E.g. `max({1,2}) = max{1,2}`

## 2 Example References
- `@/references/LC-730 palindrome.lp` and `@/references/LC-730 palindrome.py` are the logic program and the translated python program.
- `@/references/SegTree.lp` and `@/references/SegTree.py` are the logic program and the translated python program.
- `@/references/DataFlowAnalysis.lp` is a program describing compiler-domain-knowledge about data-flow-framework.
