

for the logic language skill in this repo, I want to ground the logic-language to a formal logic system. my initial idea is to represent it as high-order-logic, with only function and predicate.

# describe the `logic-system`
- the `logic-system` is standard typed higher-order logic (HOL).

- the `logic-system` uses the usual HOL written forms for:
    - symbols
    - function application
    - predicate application
    - lambda abstraction
    - logical connectives
    - quantifiers
    - equality
    - tuples

- in this project, object-symbols, function-symbols, and predicate-symbols are all treated uniformly as `sym`.

- `bound-syms`, `all-bound-syms`, and `free-syms` follow the usual HOL syntactic meaning.

- primitive `set` is not part of the core `logic-system`.
    - a set over type `A` is represented by a predicate of type `A -> bool`
    - `{x | P(x)}` is sugar for `λ x. P(x)`
    - `x ∈ S` is sugar for `S(x)`
    - `x ∈ {y | P(y)}` reduces to `P(x)`
    - `{x1, x2, ... | P(x1, x2, ...)}` is a tuple-predicate. Formally it is `λ t. P(x1, x2, ...)` where `t` denotes the tuple `(x1, x2, ...)`

- this document does not redefine HOL in detail. It uses the `logic-system` only as the target written form for translating `logic-language` modules.

# Describe `module`
- a `module` is the parsed artifact translated from `module-text`.
- `logic(module)` translates `module` to a written-form expression in the `logic-system`.
    - `logic(module)` is defined by the concrete kind of `module`, currently `set-module` or `quantified-module`.

- introduce `set-module`/`SM`.
    - It includes
        - `syms`
        - `PSs`
        - `bound-syms = {syms}` as local binders introduced by current `SM`
        - `all-bound-syms = bound-syms ∪ (^PSs).all-bound-syms`
        - `free-syms = (^PSs).free-syms - bound-syms`
    - `logic(SM) = {syms | ^PSs -> ^TSs}`
    - `SM.syms` must be non-empty. `SM("{| sym}")` is valid, `SM("{| PS}")` is invalid
    - if `syms = (sym)`, `logic(SM) = λ sym. ^PSs`
    - if `syms = (sym1, sym2, ...)`, `logic(SM) = λ t. ^PSs` where `t` denotes the tuple `(sym1, sym2, ...)`
    - as set-style sugar, `logic(SM)` may also be written as `{syms | ^PSs}`

- introduce `quantified-module`/`QM`.
    - It includes
        - `quantifier`
        - `syms`
        - `PSs`
        - `TSs`
        - `bound-syms = {syms}` as local binders introduced by current `QM`
        - `all-bound-syms = bound-syms ∪ (^PSs).all-bound-syms ∪ (^TSs).all-bound-syms`
        - `free-syms = (^PSs -> ^TSs).free-syms - bound-syms`
    - `logic(QM) = quantifier{syms | ^PSs -> ^TSs}`
    - `QM.PSs` can be empty. `QM("quantifier{| TS1, TS2}") = QM("quantifier{TS1, TS2}") = TS1^TS2`
    - `QM.TSs` must be non-empty. `QM("\all{| sym}") = QM("\all{| sym | true}")`
    - e.g. `M(QMT("∀{| sym1, sym2 | PS1, PS2 | TS1}")) = {QM}` with `quantifier=∀`, `syms=(sym1, sym2)`, `PSs=(PS1, PS2)`, `TSs=(TS1)`

- more precisely, `bound-syms`, `all-bound-syms`, and `free-syms` are determined from free/bound symbol occurrences in `logic(module)`.

- `logic(modules)` is defined only when every `module ∈ modules` is statement-valued.
    - `logic(modules) = ^{| module ∈ modules | logic(module)}`

- if `sym` is in a `module`, it shouldn't appear in any of its `nested-modules`

# Describe `module-signature`
- introduce `module-signature` as the module-file-level validation environment for modules parsed from a `module-file`.
- The `module-signature` includes
  - `intrinsic-syms`: `tuple`, `set`, `function`, `value`, `null`, `true`, `false`, `bool`
  - `function-syms`
  - `built-in-forms` includes form categories accepted by `module-text`.
    - literal forms: set-comprehension, tuple-comprehension, set-literals, tuple-literals, numeric-literals
    - operator forms: numeric operators, comparison operators, membership operators, subset operators, indexing, range
    - module-text forms: imports, sections, comments, branches, function declarations, class declarations, image-set syntax
- if a `intrinsic-sym` appears in `module.syms`, it is omitted. e.g. `M("| value, sym | PS | TS") = M("| sym | PS | TS")`

# Describe `module-text`
- introduce `module-text` as the written syntax of `logic-language`.
    - `M(module-text)` translates `module-text` to a deduplicated unordered set of `module`s
    - `M("...") = M("...")` denotes reduction between equivalent surface forms.

- introduce `nested-module-text`/`NMT` as a `module-text` written inside a `module-text`, with indentation added by 1 level. All rules applied on `module-text` applies to `nested-module-text`.

- introduce `set-module-text`/`SMT` as a `module-text` whose parsed `module` is a `set-module`/`SM`.
    - `M(SMT) = {SM}`
    - `SMT` is always wrapped by `{}`
    - `SMT` parses sections in this order:
        - first section = `syms`
        - all later sections = `PSs`
    - `SMT` requires non-empty `syms`
    - e.g. `SMT("{| sym1, sym2 | PS1, PS2}")` is an `SMT`

- introduce `quantified-module-text`/`QMT` as a `module-text` whose parsed `module` is a `quantified-module`/`QM`.
    - `M(QMT) = {QM}`
    - `QMT` parses sections in this order:
        - first section = `syms`
        - last section = `TSs`
        - middle sections = `PSs`
    - `QMT` requires final non-empty `TSs`
    - `QMT` may have empty `syms`
    - e.g. `QMT("∀{| sym1, sym2 | PS1, PS2 | TS1}")` is a `QMT`
    - e.g. `M("∀{TS1, TS2}") = M("TS1 ^ TS2")`
    - e.g. `M("∀{| PS | TS}") = M("PS => TS")`

- introduce `tuple` as an intrinsic sym in `module-text`.
    M("| sym1, sym2, sym3 | (sym1, sym2) = sym3 | TS") = M("
    | sym1, sym2, sym3
    tuple~(sym1, sym2) 
    | (sym1, sym2) = sym3 
    TS
    "
    )

- introduce `value` as an intrinsic sym in `module-text`.
    - numeric literals of supported syntax implicitly have an adjacent wrapper fact `value~literal`.

- introduce `set` as an intrinsic sym in `module-text`.
    M("| sym | sym = {sym' | P(sym')} | TS") = M(
    "
    | sym
    set ~ {sym' | P(sym')}
    | sym = {sym' | P(sym')}
    TS
    "
    )

- introduce `function` as an intrinsic sym in `module-text`.
    - `function-declaration` adds its function name implicitly add `function~sym`
    M("sym: sym1 => sym2") = M(
    "
    function~sym
    sym: sym1 => sym2
    "
    )

- a `module-text` includes text-replacement rules for translation. Below are `M("...") = M("...")` rules that translate `module-text` to more reduced `normal-module-text`

- non-braced `module-text` is implicitly wrapped by `∀`
    `M("| sym | PS | TS") = M("∀{| sym | PS | TS}")`
    `M("∃ | sym | PS | TS") = M("∃{| sym | PS | TS}")`


- `SMT` with only `syms` is universal-set sugar
    `M("{| syms}") = M("{| syms | true}")`

- multi-line `module-text` can be inlined
    M(
    "
    ∀{
    | sym
    | PS
    TS
    }
    "
    ) = M("∀{| sym | PS | TS}")
    M(
    "
    {
    | sym
    | PS
    }
    "
    ) = M("{| sym | PS}")
    
    M(
    "
    \all{|
        sym
        | PS
        |TS
    }
    "
    ) is invalid, in multi-line form `|` should accompany a term

- `nested-module-text` is represented by wrapped `{}` or `quantifier{}`
    `M("| sym1 | ∀{| sym2 | TS2} | TS1")` has `"∀{| sym2 | TS2}"` as `nested-module-text`

- `nested-module-text` is represented by indentation in multi-line form
    M(
    "
    | sym1
        | sym2
        TS2
    TS1
    "
    or
    )
    M("
    | sym1
    ∀
        | sym2
        TS2
    ")
    Both forms reduce to a `nested-module-text` with implicit `∀` on the nested non-braced text.

- in non-braced `module-text` or `QMT`, `{sym, PS}` before final `TSs` can swap freely
    `M("| sym1 | PS1 | sym2 | PS2 | TS") = M("| sym1 | sym2 | PS1 | PS2 | TS")`

- in multi-line form, when `sym` appears in a line, it represents `| sym`
    M(
    "
    sym
    | PS
    TS
    "
    ) = M(
    "
    | sym
    | PS
    TS
    "
    )

- `module-text`'s `syms` override all `nested-module-text`s' `syms` with same name
    `M("| sym1 | ∀{| sym1, sym2 | TS2} | TS1") = M("| sym1 | ∀{| sym2 | TS2} | TS1")`
    This is important difference from most programming-languages' scoping-rule, which let nested-scope override parent-scope.
    With this rule, `nested-module-text` can add constraints onto parent-scope's syms

- a non-braced `module-text` or `QMT` that has `TS` not in final lines translates to one `module-text` with nested `QMT`s
    M("
    | sym 
    | PS1
    TS1 
    | PS2
    TS2") = M("
    | sym
    | PS1
    ∀{
        TS1
    }
    ∀{
        | PS2
        TS2
    }
    ")


- adjacent `terms` in the same section can be concatenated by `,`
    `M("| sym1 | sym2 | PS1 | PS2 | TS") = M("| sym1, sym2 | PS1, PS2 | TS")`

- in multi-line `QMT` form, adjacent final `TSs` can also be concatenated by `,`
    M(
    "
    | sym1
    | sym2
    | PS1
    | PS2
    TS1
    TS2
    "
    ) = M(
    "
    | sym1, sym2
    | PS1, PS2
    TS1, TS2
    "
    )

- when multiple same `sym` appears in the same `syms` section, deduplicate it
    `M("| sym1, sym1 | PS | TS") = M("| sym1 | PS | TS")`

- introduce `implicit-inheritance` that in `PS` and `TS`, a `sym` name can implicitly add `~` predicate-statement
    - `{class}{digit}` and `{prefix}_{class}` and `{class}_class` syms inherit `{class}`.
        M("| prefix_object1") = M("| prefix_object1 | object~prefix_object1")
    - `{prefix}_{class}_list` and `{prefix}_{class}s` inherit `tuple`. and all its elements inherit `{class}`
        M("| prefix_objects") = M("| prefix_objects | tuple~prefix_objects | \all{sym \in prefix_objects | object~sym }")

- introduce `|-`/`branch` in multi-line form.
- introduce a group of `|-` as `switch`. It translates to one `module-text` with nested `QMT`s.
        M(
        "
        | sym
        |- PS1
            | PS1'
            TS1
        |- PS2
            | PS2'
            TS2
        TS3
        ") =
        M(
        "
        | sym
        ∀{
            | PS1
            | PS1'
            TS1
            TS3
        }
        ∀{
            | PS2
            | PS2'
            TS2
            TS3
        }
        "
        )

- introduce `unary-operator` as `sym`, such as `M("-S") = M("-(S)")`

- introduce `binary-operator` as `sym`, such as `M("S1 + S2") = M("+(S1, S2)")`

- introduce `~` as a `binary-operator`

- introduce `class` as a `sym` that appears in first parameter in any `sym ~ sym1`

- selected binary-operator `PSs` can implicitly add `syms` to current `SMT`/`QMT`.
    - this rule applies only to `PSs`, not final `TSs`.
    - this rule only infers a plain sym or tuple of plain syms.
    - inferred `syms` follow the existing deduplication and outer-scope override rules.
    - `sym1 = sym2`, `sym1 > sym2`, `sym1 < sym2`, `sym1 >= sym2`, `sym1 <= sym2`, `sym1 ∈ sym2`, `sym1 ∉ sym2`, `sym1 ⊂ sym2`, `sym1 ⊄ sym2`, `sym1 ⊆ sym2`, `sym1 ⊈ sym2`, and `sym1 ≠ sym2` infer `sym1`.
    - the same rule applies before `latex-translation` to `sym1 \in sym2`, `sym1 \notin sym2`, `sym1 \subsetof sym2`, `sym1 \notsubsetof sym2`, `sym1 \includedin sym2`, `sym1 \notincludedin sym2`, and `sym1 \ne sym2`.
    - `class~sym2` infers `sym2`; `class` must already be declared or intrinsic.
    - e.g. `M("x = f(y) | P(x)") = M("| x | x = f(y) | P(x)")`
    - e.g. `M("(x, y) = f(z) | P(x, y)") = M("| x, y | (x, y) = f(z) | P(x, y)")`
    - e.g. `M("value~x | P(x)") = M("| x | value~x | P(x)")` because `value` is intrinsic.
    - e.g. `foo~x` is invalid when `foo` is not declared or intrinsic.

- introduce `function-declaration` as form `sym: (sym1~sym2, sym3~sym4, ...) => (sym5~sym6, sym7~sym8)`
    - `"sym(sym1)"` is a `function-statement`
    M(
    "
    | free-sym1, free-sym2
    sym: free-sym1~bound-sym1 => free-sym2~bound-sym2
        | PS
        TS
    "
    ) = M("
    | free-sym1, free-sym2
    ∀
        | bound-sym1, bound-sym2
        | bound-sym2 = sym(bound-sym1)
        | free-sym1 ~ bound-sym1
        | PS
        free-sym2 ~ bound-sym2
        TS
    ")

    M(
    "
    | free-sym1, free-sym2
    sym: (free-sym1~bound-sym1, free-sym2~bound-sym2) => (free-sym3~bound-sym3, free-sym4~bound-sym4)
        | PS
        TS
    "
    ) = M("
    | free-sym1, free-sym2
    ∀
        | bound-sym1, bound-sym2, bound-sym3, bound-sym4
        | (bound-sym3, bound-sym4) = sym(bound-sym1, bound-sym2)
        | free-sym1 ~ bound-sym1
        | free-sym2 ~ bound-sym2
        | PS
        free-sym3 ~ bound-sym3
        free-sym4 ~ bound-sym4
        TS
    ")
    
    - function `parameters` must be `bound-sym` in current-scope. So it cannot have same name as `syms` in outer-scopes. function `parameter-classes`(i.e. `free-sym1, free-sym2,...`) must be `free-sym`

    - Induction: `function`'s arity is not fixed, so multiple `function-declarations` for the same `sym` add quantified constraints to the same function-sym.

- introduce `function-assign`
    M("sym: (sym1, sym2) -> F(sym1, sym2)") = M(
    "
    sym: (sym1, sym2) => sym3
        sym3 = F(sym1, sym2)
    "
    )

- The `function-declaration`'s `parameter` may not explicitly write `parameter-class`. In that case, the parameter uses class-inheritance naming rules, and class-name aliasing applies in `function-declaration` only.
    - when a parameter name is exactly a class name, it implicitly translates to another name; otherwise it will not be a `bound-sym`.
    - when a param-name is `class` name, this `class` itself will not be able to be used as `free-sym` inside the `function-declaration` scope.

    `M("sym: (value, value1) => out_value") = M("sym: (value~value', value~value1) => value~out_value")`
    Note that `value'` is implicitly introduced as `bound-sym` representing `value` in `function-declaration`, so that real free-sym `value`-class can be used in nested-scope as `free-sym`

- introduce `predicate-declaration`
    `preidicate` follow same rule as `function-declaration`, but `sym(...)` is a `predicate-statement`, not `function-statement`
    M(
    "
    sym: sym1~sym1' => bool
        | PS
        bool = TS
    "
    ) = M(
    "
    \all{
        | sym1'
        | sym1~sym1'
        | PS
        TS
    }
    "
    )

- introduce `set-module-text` as identical to `SMT`
- introduce `image-set-text`
    - `image-set-text` is a derived `module-text`
    - it does not introduce a new `module` kind
    - it rewrites to `set-module-text` before parsing by `M(...)`
    - it introduces a fresh `sym` that does not appear anywhere in the source `module-text`
    - syntax:
        `{| syms | PSs => target}`
        M(
        "
        {
        | sym
        | PS
        => FS, sym
        }
        "
        ) = M("{| sym | PS => (FS, sym)}")

    - single-target `image-set-text`
        M("{| syms | PSs => target }") = M(
        "
        {
            | out
            ∃{| syms | PSs | out = target }
        }
        "
        )
        where `out` is a fresh `sym`

    - tuple-target `image-set-text`
        M("{| syms | PSs => (target1, target2, ...) }") = M(
        "
        {
            | out
            ∃{| syms | PSs | out = (target1, target2, ...) }
        }
        "
        )
        where `out` is a fresh `sym`

    - `=>` is part of surface `module-text` only. After rewrite, `image-set-text` is represented by ordinary `set-module-text`.

- introduce `class-declaration`
    M(
    "
    sym
        ::sym1
        ::sym2: sym => sym2'
        ::sym3: (sym, sym3') => sym3''
        : (sym, sym4) => sym4'
        P(sym)
    "
    ) = M("
    sym
    sym::sym1
    sym::sym2: sym => sym2'
    sym::sym3: (sym, sym3') => sym3''
    sym: (sym, sym4) => sym4'
    \all{| sym~sym' | P(sym')}
    ")

    `M("x::y") = M("y")`

    M(
    "
    sym
    sym::sym1
    sym::sym2: sym => sym2'
    sym::sym3: (sym, sym3') => sym3''
    "
    ) = M("
    sym
    sym1
    sym2: sym => sym2
    sym3: (sym, sym3') => sym3''
    ")

    Note that the indentation is not a real `nested-module-text`, it is still expanded to current-scope, with `sym` prefix
    - Induction: `::` itself has no semantics, it's just for readability for OOP programmers. in `module-text` it is omitted.
    - to mimic `class-method` behavior, make `sym::sym2`'s first-parameter as `sym` will make it work like `class-method` or `class-field`

- `~` and `class-declaration` can be inlined
    M(
    "
    sym1 ~ sym2
        ::sym3: (sym2, sym4) => sym5
    "
    ) = M(
    "
    sym1 ~ sym2
    sym2
        ::sym3: (sym2, sym4) => sym5
    "
    )

- introduce `class-field-assign`
    `M("sym::sym1 = sym2") = M("sym::sym1: sym -> sym2")`

- introduce `class-method-call`
    `M("sym1.sym2(sym3)") = M("sym2(sym1, sym3)")`

- introduce `section`: `M("@...") = M("∀")`

- introduce `comment`: `M("#...") = M("")`

- introduce comparator concatenation
    `M("sym1 < sym2 < sym3") = M("sym1 < sym2 ^ sym2 < sym3")`

- introduce `[]` as identical to `()` tuple
    `M("[x, y]") = M("(x, y)")`

- introduce `[]` as a `binary-operator`
    `M("sym1[sym2]") = M("[](sym1, sym2)")`

- introduce `list` as identical to `tuple`
    - `list::size: list => size`
    - `list::[]: (list, id) => sym`

- introduce `value` as `base-class` for all numerics

- introduce singleton-unary-operator `*set`
    - `*set` extracts the unique element from a set-valued term.
    - `logic(M("*set")) = THE sym. sym ∈ set`, where `sym` is fresh.
    - each use of `*set` adds a uniqueness assertion to current `PSs`.
    - the uniqueness assertion is written directly, without introducing a `singleton` sym:
        `∃{| sym | sym ∈ set | ∀{| sym' | sym' ∈ set | sym' = sym }}`
        where `sym` and `sym'` are fresh.
    - e.g.
        M("
        | out
        out = *S
        TS
        ") = M("
        | out
        | ∃{| sym | sym ∈ S | ∀{| sym' | sym' ∈ S | sym' = sym }}
        out = *S
        TS
        ")

- introduce `[:]` as a `ternary-operator`
    [sym1: sym2: class] := 
    *{
        class~sym1
        class~sym2
        | tuple
        | ∀
            | sym' 
            | sym1 <= sym' < sym2
            class~tuple(i)
            tuple(i) = sym' 
    }

- introduce `[:]` as a `binary-operator` when `sym-parameter`'s class can be deduced by their names
    `[sym1: sym2] := [sym1: sym2: class(sym1)]`

- introduce `latex-translation` that translates all `latex-code` into symbols
    - full rules are in `./logic-language-latex.json`

- introduce `null` as an intrinsic symbol
    `F(sym) = null` represents a `predicate-statement` on `sym` that `sym` doesn't satisfy any input-constraint declared on `F` 
    M(
    "
    F: sym1_c~sym1 => sym2_c~sym2
        | sym1 = sym3
    F: sym1_c'~sym1 => sym2_c'~sym2
        | sym1 = sym4
    | sym'
    F(sym') = null
    "      
    ) = M(
    "
    F: sym1_c~sym1 => sym2_c~sym2
        | sym1 = sym3
    F: sym1_c'~sym1 => sym2_c'~sym2
        | sym1 = sym4
    | sym'
    !((sym1_c~sym1 ^ sym1 = sym3) || (sym1_c'~sym1 ^ sym1 = sym4))
    "
    )

# Describe module-file
- introduce `module-file`. Each `.lp` is a `module-file`.
- introduce `module-import`
    - `$import file-path` macro-expands to the `module-text` stored inside `file-path` with current indent-level
    - every `module-file` implicitly imports `standard_library.lp` in this folder

- introduce `expand-imports(module-text)`
    - `expand-imports(module-text)` macro-expands all `$import` inside `module-text`

- introduce `compile-module-text`
    - `compile-module-text(module-text) = M(expand-imports(module-text))`

- introduce `module-signature(M)` that returns the valid-signature-syms from `M` parsed from `compile-module-text`
  - `module-signature(M).function-syms` are `M.free-syms` that have `function~sym`
  - `M` is invalid if any sym occurrence is not signature-syms
    `M("| sym1 | sym2: in => out | P(sym1, sym2, value)")` is valid because `sym2` is `function-declaration-sym` and `value` is `intrinsic-sym`
    `M("| sym1 | P(sym1, sym2)")` is invalid because `sym2` is not in `signature-syms`

- introduce `compile-module-file`
    - `compile-module-file(file-path) = compile-module-text(file-text(file-path))`
    - `compile-module-file(file-path)` returns a deduplicated unordered `module-set`
    - `compile-module-file(file-path)` is valid only when every `module ∈ compile-module-file(file-path)` is a `QM`
    - `compile-module-file(file-path)` is valid only when every `module ∈ compile-module-file(file-path)` satisfies `module.free-syms ⊆ module-file.module-signature.free-syms`
    - therefore a `module-file` cannot have root-scope `{...}` after translation

- introduce `compile-module-files`
    - `compile-module-files(file-paths) = ⋃{| file-path ∈ file-paths | compile-module-file(file-path)}`

- introduce `module-files(folder-path)`
    - `module-files(folder-path)` is the set of `.lp` files inside `folder-path`

- introduce `compile-module-folder`
    - `compile-module-folder(folder-path) = compile-module-files(module-files(folder-path))`
