---
name: logic-language
description: Parse, compile, and diagnose logic-language module text (postfix as .lp) and semantics.
---

# Overview
logic-language is a soft-typed HOL-like knowledge representation language. It represents all named entities as `sym` and expresses roles such as functions, predicates, sets, values, and user concepts through ordinary inheritance facts using `~`.

Source modules combine bound symbols, premises, and targets to describe logical propositions and set abstractions, while readable forms such as function declarations, class declarations, fields, literals, and image sets compile into a canonical module AST.

The AST is intended as a precise intermediate logic form that can support human-readable knowledge encoding and later validation through reified SMT/FOL or typed-HOL backends.

## Semantics

### Describe the `logic-system`
- the `logic-system` is soft-typed, single-symbol-domain High-order-logic.

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

### Describe `module`
- a `module` is the parsed artifact translated from `module-text`.
- `logic(module)` translates `module` to a written-form expression in the `logic-system`.
    - `logic(module)` is defined by the concrete kind of `module`, currently `set-module` or `quantified-module`.

- introduce `set-module`/`SM`.
    - It includes
        - `syms`
        - `PSs`: premise-statements, if empty, default as `true`
        - `TSs`: target-statements
        - `bound-syms = {syms}` as local binders introduced by current `SM`
        - `all-bound-syms = bound-syms ∪ (&&PSs).all-bound-syms ∪ (&&TSs).all-bound-syms`
        - `free-syms = (&&PSs -> &&TSs).free-syms - bound-syms`
    - `logic(SM) = {syms | &&PSs -> &&TSs}`
    - `SM.syms` must be non-empty. `SM("{| sym | TS}")` is valid, `SM("{| TS}")` is invalid
    - if `syms = (sym)`, `logic(SM) = λ sym. &&PSs -> &&TSs`
    - if `syms = (sym1, sym2, ...)`, `logic(SM) = λ t. &&PSs -> &&TSs` where `t` denotes the tuple `(sym1, sym2, ...)`

- introduce `quantified-module`/`QM`.
    - It includes
        - `quantifier`
        - `syms`
        - `PSs`: premise-statements, if empty, default as `true`
        - `TSs`: target-statements
        - `bound-syms = {syms}` as local binders introduced by current `QM`
        - `all-bound-syms = bound-syms ∪ (&&PSs).all-bound-syms ∪ (&&TSs).all-bound-syms`
        - `free-syms = (&&PSs -> &&TSs).free-syms - bound-syms`
    - `logic(QM) = quantifier{syms | &&PSs -> &&TSs}`
    - `QM.PSs` can be empty. `QM("quantifier{| TS1, TS2}") = QM("quantifier{TS1, TS2}") = TS1 && TS2`
    - `QM.TSs` must be non-empty. `QM("\all{| TS}") = QM("\all{TS}") = TS`
    - e.g. `M(QMT("∀{| sym1, sym2 | PS1, PS2 | TS1}")) = QM` with `quantifier=∀`, `syms=(sym1, sym2)`, `PSs=(PS1, PS2)`, `TSs=(TS1)`

- more precisely, `bound-syms`, `all-bound-syms`, and `free-syms` are determined from free/bound symbol occurrences in `logic(module)`.

- `logic(module-list)` is defined only when every `module ∈ module-list` is statement-valued.
    - `logic(module-list) = &&{| module ∈ module-list | logic(module)}`

- Formal definition is in `semantic_logic/module_AST.lp`

### Describe `module-signature`
- introduce `module-signature` as the module-file-level validation environment for modules parsed from a `module-file`.
- The `module-signature` includes
  - `intrinsic-syms`: `Tuple`, `Set`, `Function`, `Predicate`, `Value`, `true`, `false`, `Bool`, `Symbol`, `Char`, `String`, `List`
  - `function-syms`
  - `built-in-forms` includes form categories accepted by `module-text`.
    - literal forms: set-comprehension, tuple-comprehension, set-literals, tuple-literals, numeric-literals
    - operator forms: numeric operators, comparison operators, membership operators, subset operators, indexing, range
    - module-text forms: imports, sections, comments, branches, function declarations, class declarations, image-set syntax
- if a `intrinsic-sym` appears in `module.syms`, it is omitted. e.g. `M("| value, sym | PS | TS") = M("| sym | PS | TS")`

### Source Naming Convention
- Class symbols should start with a capital letter, e.g. `Stmt`, `Sym_type`.
- Function, predicate, method, and field symbols should use lower snake case and should not start with `_`, e.g. `get_sym_type`, `call_sym`.
- Local pure variables should start with `_`, including declaration inputs/outputs, method receivers, quantifier/set binders, premise binders, and temporary body variables.
- Global pure constants may use lower snake case without `_` when explicitly class-typed and not used as callable heads, e.g. `class_sym_type`, `true`, `false`.
- Member references rename only the receiver variable; public field names stay unchanged. For example, `stmt.sub_stmts` should be written as `_stmt.sub_stmts`.

## Module Text
- introduce `module-text` as the written syntax of `logic-language`.
    - `M(module-text)` translates `module-text` to a module
    - `M("...") = M("...")` denotes reduction between equivalent surface forms.

- introduce `nested-module-text`/`NMT` as a `module-text` written inside a `module-text`, with indentation added by 1 level. All rules applied on `module-text` applies to `nested-module-text`.

- introduce `set-module-text`/`SMT` as a `module-text` whose parsed `module` is a `set-module`/`SM`.
    - `M(SMT) = SM`
    - `SMT` is always wrapped by `{}`
    - `SMT` parses sections by priority:
        - right-to-left section = `TSs`
        - left-to-right section = `syms`
        - remaining middle sections = `PSs`
    - `SMT` requires non-empty `syms`
    - e.g. `SMT("{| sym1, sym3 | PS1, PS2 | TS1, TS2}")` is an `SMT`

- introduce `quantified-module-text`/`QMT` as a `module-text` whose parsed `module` is a `quantified-module`/`QM`.
    - `M(QMT) = QM`
    - `QMT` parses sections by priority:
        - right-to-left section = `TSs`
        - left-to-right section = `syms`
        - remaining middle sections = `PSs`
    - `QMT` requires final non-empty `TSs`
    - `QMT` may have empty `syms`
    - e.g. `QMT("∀{| sym1, sym2 | PS1, PS2 | TS1}")` is a `QMT`
    - e.g. `M("∀{TS1, TS2}") = M("TS1 && TS2")`
    - e.g. `M("∀{| sym | TS}") = M("∀{| sym | true | TS}")`

- introduce `~` as intrinsic `binary-operator` on all `sym`
    - `a ~ b` means `b` inherits `a`
    - `~` is reflexive
        `∀{| x | x ~ x}`
    - `~` is transitive
        `∀{| x, y, z | x ~ y, y ~ z | x ~ z}`
    - e.g. `∀{| x, y, z | x~y, y~z | x~z}` is a canonical surface axiom expressing transitivity
    - the standard library provides the canonical reflexivity axiom
        `∀{| ^sym | ^sym ~ ^sym}`
    - `~` does not by itself introduce separate primitive syntactic categories for object-sym, function-sym, predicate-sym, or class-sym
    - those roles are determined by declaration form, usage position, and translation to the target `logic-system`

- introduce `Tuple` intrinsic-sym
    - `Set ~ Tuple`
    - `(sym1, sym2, ...)` is a tuple-literal.
    - `[sym1, sym2, ...]` is identical to `(sym1, sym2, ...)`
    - tuple-literals are ordinary HOL tuple expressions.
    - tuple-literal equality is ordinary HOL tuple equality.
    - tuple-literal equality lowers component-wise.
      `M("(sym1, sym2) = (sym1', sym2')") = M("sym1 = sym1', sym2 = sym2'")`
    - if a declared symbol is equated with a tuple-literal, the symbol is classified as `Tuple`.
        M("sym = (sym1, sym2)") =
        M("
        Tuple ~ sym
        sym.size = 2
        sym[0] = sym1
        sym[1] = sym2
        ")

- introduce `Value` as an intrinsic sym in `module-text`.
    - numeric literals of supported syntax implicitly have an adjacent wrapper fact `Value ~ literal`.

- introduce `Set` as an intrinsic sym in `module-text`.
    `Set = Predicate`
    M("| sym | sym = {sym' | P(sym')} | TS") = M(
    "
    | sym
    Set ~ {sym' | P(sym')}
    | sym = {sym' | P(sym')}
    TS
    "
    )

- introduce `\in` and `\notin` as membership operators.
    - `set` is a predicate-object, so membership is predicate application.
    - `M("x \in set") = M("set(x)")`
    - `M("x \notin set") = M("!set(x)")`
    - after latex-translation, the same rules apply to `x ∈ set` and `x ∉ set`.

- introduce `Function` as an intrinsic sym in `module-text`.
    - `function-declaration` adds its function name as an ordinary inheritance fact `Function ~ sym`
    - if the declaration output is exactly `bool`, it is a `predicate-declaration` and adds `Predicate ~ sym` instead.
    M("sym: sym1 => sym2") = M(
    "
    Function ~ sym
    sym: sym1 => sym2
    "
    )
    - premise declaration sugar is allowed anywhere a premise statement is allowed:
      `M("| f: in => out") = M("| Function ~ f | ∀{| in, out | out = f(in)}")`
    - with an indented declaration body, the generated body module is also a premise statement of the parent module.

- introduce `Symbol` as an intrinsic sym in `module-text`
    - the standard library provides the canonical universal symbol axiom
        `∀{| ^sym | Symbol ~ ^sym}`
    - compiler-generated `Symbol ~ sym` facts may be omitted when the same module-stmt premise section already contains another inheritance fact `source ~ sym`
    - Induction: all `syms` in `module` will have at least `Symbol` as an inheritance-source sym when the standard library axiom is in scope, except generated `^...` syms
    - `^` is reserved for generated-sym source. It is valid only as the first character of a generated sym-name. `__...` has no generated-symbol semantics.

- a `module-text` includes text-replacement rules for translation. Below are `M("...") = M("...")` rules that translate `module-text` to more reduced `normal-module-text`

- non-braced `module-text` is implicitly wrapped by `∀`
    `M("| sym | PS | TS") = M("∀{| sym | PS | TS}")`
    `M("∃ | sym | PS | TS") = M("∃{| sym | PS | TS}")`


- `SMT` requires both `syms` and `TSs`
    `M("{| syms}")` is invalid because the only section is parsed as `TSs`, leaving `syms` empty.

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

- introduce `set-literal`
    - `{sym1, sym2, ...}` is a set-literal.
    - a set-literal denotes the predicate that holds exactly on the listed elements.
    - if a declared symbol is equated with a set-literal, the symbol is classified as `Set`.
      `M("sym = {sym1, sym2}") = M("∀{| x | Set ~ sym, sym.size = 2, sym(x) = (x = sym1 ∨ x = sym2)}")`

- introduce `Char` intrinsic-sym
    - `char-literal` is single characters wrapped in `''`, e.g. 'a'/'b'/'c'/...
    `M("sym = 'a'") = M(sym = 'a', Char ~ sym)`

- introduce `String` intrinsic-sym
    - `String` is a list of chars.
    `M("sym = \"abc\"") = M("
    String ~ sym
    sym.size = 3
    sym[0] = 'a'
    sym[1] = 'b'
    sym[2] = 'c'
    "
    )`


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

- `module-text`'s nested `syms` must not reuse ancestor `syms`
    - `M("| x | ∀{| x | x = x} | TS1")` is invalid because the inner `x` conflicts with the ancestor `x`.
    - names are not freshened to aliases.
    - This applies to `SMT`, `QMT`, `function-declaration`, and any nested `module-text`.

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
    in multi-line form, when statement starts with `|` it is either a `sym` or `PS`, otherwise it is `TS`
    a standalone plain `sym` line without `|` is a class declaration, not a binder declaration. Binders must be written with `| sym`.
    a standalone plain class declaration must be a capital-head symbol such as `Val`; standalone lowercase symbols and standalone operator symbols are invalid.

- when multiple same `sym` appears in the same `syms` section, deduplicate it
    `M("| sym1, sym1 | PS | TS") = M("| sym1 | PS | TS")`
    a `bound-sym` name must not equal any `bound-sym` in the current statement or any ancestor statement; such conflicts are invalid and are not freshened.

- introduce `implicit-inheritance` that for a bound `sym`, the compiler may add a generated `~` predicate-statement
    - Each scope has declared class syms. A class is declared by a standalone capital-head target line such as `Val`; the declaration itself emits no logical target statement.
    - Name-implicit inheritance searches declared classes from the current scope and all ancestor scopes, plus imported class declarations. Sibling nested scopes do not share local class declarations.
    - A name-implicit inheritance is applied only when the base part of the name resolves to a visible declared class sym by the naming convention below.
    - If the base part does not resolve to a visible declared class sym, the bound sym falls back to generated `Symbol ~ sym` and semantic-check reports warning `implicit_inheritance_fallback_symbol`.
    - Explicit inheritance facts such as `A ~ sym` do not declare `A`; they use `A` as an ordinary free sym.
    - A declared-sym whose normalized name starts with `is_` implicitly inherits `Bool`. Normalization for this rule strips leading `_`, trailing primes, and trailing digits; generated `^...` syms are excluded. This `Bool` rule is magic and does not require a visible `Bool` declaration.
        `is_valid`, `_is_val`, and `is_ready1` infer `Bool`; `^is_valid` does not.
    - Candidate lookup strips trailing primes and trailing digits, then tries the full remaining name and repeatedly removes the first `_` segment. Only the first character of each candidate is capitalized.
        `max_head_val1` tries `Max_head_val`, then `Head_val`, then `Val`.
    - If the normal candidate lookup finds no visible declared class and the normalized name ends with `_class`, lookup then drops the `_class` suffix and repeats the same candidate lookup as a low-priority fallback.
        `_chip_mem_class` first tries `Chip_mem_class`, `Mem_class`, and `Class`; only if none are visible, it tries `Chip_mem` and then `Mem`.
    - When multiple visible candidates match, the longest candidate wins.
    - If the current module target or premise section already contains an inheritance fact `source ~ sym`, compiler-generated premise inheritance for `sym` may be omitted so target guarantees remain canonical after disassembly.
    - `{base}{digit}` and `{prefix}_{base}` syms inherit the selected visible capital-head base.
        `list1` infers `List ~ list1` only if `List` is visible.
        `out_value` infers `Value ~ out_value` only if `Value` is visible.
    - `{prefix}_{base}_list` inherits `Tuple`, and its elements inherit the selected base, only when that base is visible.
    - `{prefix}_{base}s` inherits `Set`, and its elements inherit the selected base, only when that base is visible.
        M("| prefix_object_list") = M("| prefix_object_list | Tuple ~ prefix_object_list | \all{sym \in prefix_object_list | Object ~ sym }")
        M("| prefix_objects") = M("| prefix_objects | Set ~ prefix_objects | \all{sym \in prefix_objects | Object ~ sym }")
    - `{name}'`/`{name}''`/... is treated same as `{name}` for implicit-inheritance inference

- when `set-literal` is the only parameter in `statement`, it can ignore `()`
    `M("\union({sym1, sym2})") = M("\union{sym1, sym2}")`

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
        | ∀{
            | PS1
            | PS1'
            TS1
        }
        | ∀{
            | PS2
            | PS2'
            TS2
        }
        "
        TS3
        )

- introduce `unary-operator` as `sym`, such as `M("-S") = M("-(S)")`

- introduce `binary-operator` as `sym`, such as `M("S1 + S2") = M("+(S1, S2)")`
    - `%` is supported as a binary numeric operator: `M("a % b") = M("%(a, b)")`.
    - Arithmetic infix expressions currently group left to right, including `%`,
      `*`, `/`, `+`, and `-`; use parentheses for the intended grouping.

- introduce `implicit-sym-declaration` rule
    - selected binary-operator `PSs` implicitly add `syms` to current `SMT`/`QMT`.
    - this rule applies only to `PSs`, not final `TSs`.
    - this rule only infers a plain sym or tuple of plain syms.
    - inferred `syms` follow the same deduplication and ancestor-conflict invalidity rule as explicit `syms`.
    - `sym1 = sym2`, `sym1 > sym2`, `sym1 < sym2`, `sym1 >= sym2`, `sym1 <= sym2`, `sym1 ∈ sym2`, `sym1 ∉ sym2`, `sym1 ⊂ sym2`, `sym1 ⊄ sym2`, `sym1 ⊆ sym2`, `sym1 ⊈ sym2`, and `sym1 ≠ sym2` infer `sym1`.
    - the same rule applies before `latex-translation` to `sym1 \in sym2`, `sym1 \notin sym2`, `sym1 \subsetof sym2`, `sym1 \notsubsetof sym2`, `sym1 \includedin sym2`, `sym1 \notincludedin sym2`, and `sym1 \ne sym2`.
    - `base ~ sym2` infers `sym2`; `base` must already be visible as a declared inheritance-source sym, or be a syntax-generated inheritance source.
    - e.g. `M("x = f(y) | P(x)") = M("| x | x = f(y) | P(x)")`
    - e.g. `M("(x, y) = f(z) | P(x, y)") = M("| x, y | (x, y) = f(z) | P(x, y)")`
    - e.g. `M("Value ~ x | P(x)") = M("| x | Value ~ x | P(x)")` when `Value` is visible.
    - e.g. `foo ~ x` is invalid when `foo` is not declared.

- introduce `function-declaration` as form `sym: (sym1, ...) => (sym2, ...)`
    M(
    "
    Sym
    F: (sym1, sym2) => sym3
    "
    ) = M(
    "
    Sym
    Function ~ F
    \all
        | sym1, sym2, sym3
        | Sym ~ sym1, Sym ~ sym2
        | sym3 = F(sym1, sym2)
        Sym ~ sym3
    "
    )

    M(
    "
    Sym
    F: (sym1, sym2) => (sym3, sym4)
    ") = M(
    "
    Sym
    Function ~ F
    \all
        | sym1, sym2, sym3, sym4, ^tmp_ret
        | Sym ~ sym1, Sym ~ sym2
        | ^tmp_ret = F(sym1, sym2)
        | sym3 = ^tmp_ret[0], sym4 = ^tmp_ret[1]
        Sym ~ sym3
        Sym ~ sym4
    "
    )

- introduce `function-body`
    M(
    "
    Sym
    F: sym1 => sym2
        | PS
        TS
    "
    ) = M("
    Sym
    F: sym1 => sym2

    ∀
        | sym1, sym2
        | Sym ~ sym1
        | sym2 = sym(sym1)
        | PS
        TS
    ")

    M(
    "
    Sym
    F: (sym1, sym2) => (sym3, sym4)
        | PS
        TS
    "
    ) = M("
    ∀
        | sym1, sym2, sym3, sym4, ^tmp_ret
        | ^tmp_ret = sym(sym1, sym2)
        | sym3 = ^tmp_ret[0], sym4 = ^tmp_ret[1]
        | PS
        TS
    ")
    
    - function `parameters` follow the same ancestor-conflict invalidity rule as nested `module-text`.
    - when a param-name is already visible in an outer-scope, the final AST is invalid; names are not freshened.
    - function input implicit-inheritance facts are premises; function output implicit-inheritance facts are targets because they are guarantees of the function.
    - Induction: `function`'s arity is not fixed, so multiple `function-declarations` for the same `sym` add quantified constraints to the same function-sym.

- The `function-declaration`'s parameters and outputs use the same name-implicit inheritance rules and ancestor-conflict invalidity rule as nested `module-text`.
    - If a name syntactically suggests an inheritance-source sym, but that source is not visible in the current scope, then the name-implicit inheritance rule does not apply.
    - e.g. with visible `Value`, `M("sym: (value, value1) => out_value")` adds premise facts `Value ~ value` and `Value ~ value1`, and target fact `Value ~ out_value`.

- introduce `predicate-declaration`
    `predicate` is a special form of `function` which returns a output sym inheriting `Bool`. i.e. `P: sym => bool`
    `predicate` follows the same rule as `function-declaration`, but emits `Predicate ~ P`, and `P(...)` is a `predicate-statement`, not `function-statement`
    
- introduce `set-module-text` as identical to `SMT`
- introduce `image-set-text`
    - `image-set-text` is a derived `module-text`
    - it does not introduce a new `module` kind
    - it rewrites to `set-module-text` before parsing by `M(...)`
    - it introduces fresh `sym`s that do not appear anywhere in the source `module-text`
    - syntax:
        `{| syms | PSs | TSs => FS}`
        M(
        "
        {
        | syms
        | PS
        TS
        => FS
        }
        "
        ) = M("{| syms | PS | TS => FS}")
    - `image-set-text` maps every element of the source set `{| syms | PSs | TSs}` to `FS`.
        M("{| syms | PSs | TSs => FS}") = M(
        "
        {
            | out
            ∃{
                | syms
                ∀{| PSs | TSs}
                FS = out
            }
        }
        "
        )
        where `out` is fresh. The source predicate keeps its implication
        semantics; when PSs are empty, TSs are conjoined directly with `FS = out`.
    - Only `out` is bound by the outer set, even for multiple source variables
      or a tuple-valued FS. All source variables and generated auxiliaries stay
      inside the existential; they must not become output coordinates.
    - shorthand source forms such as `{| sym ∈ set => FS}` and `{| sym => FS}` are first normalized to an explicit source set before this rewrite.

    - `=>` is part of surface `module-text` only. After rewrite, `image-set-text` is represented by ordinary `set-module-text`.

- introduce `class-declaration`
    - `class-declaration` is a surface syntax form only. Semantically it is sugar that expands to ordinary function declarations and `~` facts.
    - it does not introduce a new primitive semantic kind named `class`.
    - A standalone capital-head target line such as `Class` declares `Class` as a class in the current scope and emits `Symbol ~ Class` as a target statement.
    - Standalone non-capital symbols such as `class` and standalone operator symbols such as `~` are invalid as class declarations.
    - `Class::...` and `Class` body syntax require an explicit visible `Class` declaration in the same direct module body or an imported module.
    - inheritance facts such as `A ~ Class` do not declare `Class`.

    M("Class::field") = M("field: _class => _field")
    M("Class::field = expr") = M(
    "
    Class::field
    ∀{
        | _class
        | Class ~ _class
        _class.field = expr
    }
    ")
    M("| Class::field = expr") = M(
    "
    | Class::field
    | ∀{
        | _class
        | Class ~ _class
        _class.field = expr
    }
    ")
    M("Class::func: inputs => outputs") = M("func: inputs => outputs")

    M(
    "
    Sym
        ::sym1
        ::sym2: sym => sym2'
        ::sym3: (sym, sym3') => sym3''
    "
    ) = M("
    Sym::sym1
    Sym::sym2: sym => sym2'
    Sym::sym3: (sym, sym3') => sym3''
    ")

    M(
    "
    Sym
    Sym::sym1
    Sym::sym2: sym => sym2'
    Sym::sym3: (sym, sym3') => sym3''
    "
    ) = M("
    sym1: _sym => _sym1
    sym2: sym => sym2'
    sym3: (sym, sym3') => sym3''
    ")

    Note that the indentation is not a real `nested-module-text`; it is expanded to current scope with the owner prefix applied to each `::` member.
    - `::` itself has no core semantics; it is omitted after surface expansion.
    - `Class::field = expr` is class field assignment sugar. The right-hand side can be any ordinary expression.
    - To mimic class-method behavior, make the first parameter the lower-head owner name, such as `_class` for `Class`, so name-implicit inheritance can infer `Class ~ _class`.
    - A standalone class declaration such as `Class` does not add an implicit premise binder like `| Class`.

- `~` inheritance facts do not introduce class declarations for `::` bodies.
    - `A ~ B` is only an inheritance statement.
    - To attach fields or methods to `B`, declare `B` explicitly, then use `B::field` or a `B` body.

- introduce `class-method-call` as sugar
    `M("sym1.sym2(sym3)") = M("sym2(sym1, sym3)")`
    `M("sym1.sym2") = M("sym2(sym1)")`

- introduce `section`: `M("@...") = M("∀")`; text after `@` is non-semantic section metadata and is discarded.

- introduce `comment`: `M("#...") = M("")`

- introduce comparator concatenation
    `M("sym1 < sym2 < sym3") = M("sym1 < sym2 && sym2 < sym3")`

- introduce `[]-literal` as identical to `tuple-literal`
    `M("[x, y]") = M("(x, y)")`

- introduce `[]` as a `binary-operator`
    `M("sym1[sym2]") = M("[](sym1, sym2)")`

- introduce `List` as identical to `Tuple`
    - `List::size: list => size`
    - `List::[]: (list, id) => sym`

- introduce `Value` as inheritance-source for all numerics

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

- introduce `[val1: val2]` as a `binary-operator` and `sym[val1: val2]` as a `ternary-operator`
    M("list = [val1: val2]") = M(
    "
    list = [:](val1, val2)
    "
    ) = M(
    "
    list
    List ~ list
    list.size = val2 - val1
    \all
        | val
        | val1 <= val
        | val < val2
        list[val - val1] = val
    "
    )

    M("
    list = sym[val1 : val2]
    ") = M(
    "
    list = [:](sym, val1, val2)
    "
    ) = M(
    "
    list
    List ~ list
    list.size = val2 - val1
    \all
        | val
        | val1 <= val
        | val < val2
        list[val - val1] = sym[val]
    "
    )

- introduce `latex-translation` that translates all `latex-code` into symbols
    - `\land` translates to `∧`; `\and` translates to `&&`
    - `\lor` translates to `∨`; `\or` translates to `||`
    - full rules are in `./latex-tokens.json`

- introduce `null` as a syntax-sugar
    - `F(args) = null` is a `predicate-statement`, not a normal output value.
    - it means `args` is outside every declared input domain of `F`.
    - declared input domain uses each `F` declaration's input class constraints and `PSs`; it does not use output constraints or `TSs`.
    - all declarations named `F` contribute to the domain check.
    M(
    "
    F: in_c~in => out_c~out
        | PS
        TS
    | arg
    F(arg) = null
    "
    ) = M(
    "
    F: in_c~in => out_c~out
        | PS
        TS
    | arg
    ¬∃{| in | in = arg, in_c~in, PS}
    "
    )
    M(
    "
    F: in_c~in => out_c~out
        | PS
        TS
    F: in_c'~in' => out_c'~out'
        | PS'
        TS'
    | arg
    F(arg) = null
    "
    ) = M(
    "
    F: in_c~in => out_c~out
        | PS
        TS
    F: in_c'~in' => out_c'~out'
        | PS'
        TS'
    | arg
    ¬(
        ∃{| in | in = arg, in_c~in, PS}
        ||
        ∃{| in' | in' = arg, in_c'~in', PS'}
    )
    "
    )
    M(
    "
    F: in_c~in => out_c~out
        | PS
        out = null
    "
    ) = M(
    "
    F: in_c~in => out_c~out
        | PS
        F(in) = null
    "
    )
    `null` does not imply any output class predicate such as `out_c~null`.

## Diagnostics

- `set_stmt_premise` warns on each explicit source premise in a set-stmt,
  including local value bindings and premises before an image-set's `=>`.
  Pure binders, targets, and compiler-generated premises are excluded.
  Nested sets are checked independently, with one warning per source statement.
  Set premises use implication (`PSs -> TSs`): a false premise makes the
  predicate true. Put filtering conditions in the target conjunction when that
  is the intended meaning. The warning does not rewrite or reject the source.
- `syntax_check` inputs `module-text` or `module-file` and returns syntax warnings/errors.
    - tool: `scripts/syntax_check.py`
- `semantic_check` inputs `module-text` or `module-file` and returns semantic warnings/errors.
    - semantic checking only runs when syntax checking succeeds.
    - tool: `scripts/semantic_check.py`

## Compilation
- introduce `module-file`. Each `.lp` is a `module-file`.
- introduce `module-import`
    - `$import file-path` simply replace this line with the file-text stored in `file-path`
    - `standard_library.lp` in this folder is a provided library file containing mostly useful functions and class-syms

- introduce `module_AST` as the compiler output form.
    - `compile_module` emits the root `module_stmt` JSON node by default.
    - final output uses object-AST field names such as `bound_syms`, `premise_binding_stmts`, `premise_proposition_stmts`, and `target_proposition_stmts`.
    - output contains direct AST fields only; derived recursive fields are not emitted. Source positions are stored under `source_loc`, not `loc`.

- `compile_module` is implemented as a two-stage AST compiler pipeline.
    - `stage1_front_end`: parses source text once, expands imports with source-location provenance, normalizes latex codes, and performs source-sugar desugaring into frontend AST nodes.
    - `stage2_back_end`: lowers the frontend AST into final object AST, ANF-lifts non-symbol call arguments, inserts generated bindings/classifier targets, and enforces object-AST shape.
    - All emitted symbol nodes use `source_loc`; generated symbols set `generated=true` and use the authored source symbol/expression location as their `source_loc`.

- introduce `compile_module`
    - it inputs `module-text` or `module-file` and returns `module_AST` JSON.
    - `--debug-stages` prints compact JSON summaries for all compiler stages.

- introduce `translate_AST_to_source`
    - it inputs `module_AST` JSON from stdin or file and returns canonical parseable `.lp` source text.
    - it is an AST-preserving printer, not an original-source reconstruction tool.
    - generated symbols and generated statements are printed explicitly.

## Tools
- `compile_module`
    - path: `scripts/compile_module.py`
    - input: `module-text` via stdin/`--text`, or a `module-file` path.
    - output: root `module_AST` JSON by default.
    - useful flags: `--pretty`, `--debug-stages`.

- compiler stages are internal AST-only modules, not public CLI tools.
    - `stage1_front_end` input: source module text; output: frontend `SourceFileAst`.
    - `stage2_back_end` input: frontend `SourceFileAst`; output: final object AST.

- `translate_AST_to_source`
    - path: `scripts/translate_AST_to_source.py`
    - input: `module_AST` JSON from stdin or file.
    - output: canonical parseable `.lp` source text.

- `syntax_check`
    - path: `scripts/syntax_check.py`
    - input: `module-text` via stdin/`--text`, or a `module-file` path.
    - output: JSON syntax diagnostics.

- `semantic_check`
    - path: `scripts/semantic_check.py`
    - input: `module-text` via stdin/`--text`, or a `module-file` path.
    - output: JSON semantic diagnostics.

- `module_check`
    - path: `scripts/module_check.py`
    - input: `module-text` via stdin/`--text`, or a `module-file` via `--file`.
    - output: unified JSON diagnostics from syntax, semantic, compile, and final-AST checks.
    - useful flags: `--pretty`, `--filename`, `--base-dir`.

## Compiler Validation
- `golden_tests.md` is the executable semantic-review corpus for compiler expansion.
    - path: `golden_tests.md`
    - each pair has the form:
        ```
        source-text
        =
        expected-expanded-source
        ```
    - `expected-expanded-source` should be the canonical output of `expand_module(source-text)`.
    - `expand_module` output must be closure-identical:
        `expand_module(source-text) = expand_module(expand_module(source-text))`
- `smoke_test.py` is the executable compiler regression suite.
    - path: `scripts/compile_pipeline/smoke_test.py`
    - it must pass before compiler behavior is considered valid.
- `standard_library.lp` is part of compiler validation.
    - `module_check.py --file standard_library.lp` must return zero errors.
    - Explicit set premises in the standard library receive the same
      `set_stmt_premise` warnings as user modules; do not suppress them to make
      the warning count zero. Other diagnostics require investigation.
