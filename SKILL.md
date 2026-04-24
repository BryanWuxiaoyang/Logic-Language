---
name: logic-language
description: "Generate, validate, and translate `.lp` logic programs to executable code (Python/C++). Use when tasks ask to: (1) formalize natural-language problem statements, algorithms, or knowledge into `.lp`, (2) translate an existing `.lp` program into target code while preserving logic semantics, or (3) syntax-check `.lp` files and report/fix structural errors."
---

# Logic Language

This skill introduces a logic program language, with postfix `.lp`.

Design goal:
- `logic_language` is a knowledge representation language
- `logic_language` is for human-readable core logic, not low-level implementation detail.
- Prefer concise and easy-to-understand declarations while keeping core logic correct.
- Skip border-cases handling to avoid too many branches

# Semantics
Read `references/logic_language_spec.md` before producing or reviewing `.lp` code.


# Language Position and Translation Pipeline

`logic_language` is designed to represent precise logic and sits between natural language and machine programming languages (for example, C++ and Python).

- Natural language is expressive but ambiguous.
- Logic language (`.lp`) defines functions, constraints, theorems to depict algorithm or domain knowledge in a logical and organized form.
- Programming language (C++/Python) makes the logic executable for machines.

Canonical translation pipeline:

```text
natural_language => logic_language => programming_language
```

- `natural_language => logic_language`: convert informal intent to precise definitions, constraints, and proofs.
- `logic_language => programming_language`: convert formal logical function constraints into executables.

# Functionalities

1. Analyse the `.lp' logic program.
2. Translate natural-language description of an algorithm or domain-knowledge into logic program.
3. Translate logic program into executable programming languages.

# Tranlate logic program to executable program

- Get Input Arguments
    The input arguments needed for translation are:
    - source logic program
    - output executable program language
    - executable program optimization level (see `### Executable Program Optimization Level`)
    - output executable file path (default=`{logic_program_path}.{language_postfix}`)

- Check Semantic for the logic program
    Use `/scripts/semantic_parser.py {file-path}` to check semantics.

- Reformat program
    Use `scripts/reformat.py {file-path}` to reformat it. It convert latex-style symbol-representation `\...` into symbols. E.g. `\in` = `∈`.
    After reformat, there should be no `\...` symbol exists in text.

- Analyze the Logic Program
- Translate into Executable program

## Executable Program Optimization Level

When translating logic program to executable program, ask the user explicitly about what optimization-level is expected.

Optimization mode rules:

- `-O0`: strictly follow `.lp` declarations as much as possible while keeping output correct; use assertions to keep conditions in .lp; treat performance as low priority.
- `-O1`: apply `-O0` behavior; Ignore unused symbols and conditions that doesn't contribute to the output of each function.
- `-O2`: Enable as much optimization as possible as long as main logic is preserved.

# Tools

## Semantic parser
`@/scripts/semantic_parser.py`: Generates formal semantic-architecture and verify semantic-correctness and work as basis for program analyses.
    - run `verify_semantic_parser` on all `.lp` programs in `@/references` whenever updating the script. Ensure that `semantic_node -> program_source -> semantic_node` process retain all semantic information of original program.

## Class Inheritance Graph
Use command `show-class-inheritance-graph {class}` to find all parent-classes and sub-classes of a given class from the logic program.

Use command `show-class-inheritance-graph` to show all classes' inheritance relations.

## Class Info
Use command `show-class {class}` to print the `class` and all member-functions it declares/inherits. And its inheritance graph.

Use command `show-class -full {class}` to print all conditions defined on the class and member-functions, as well as all info in `show-class {class}`.

## Condition Decomposer
Decompose a complicated ∀ condition into a list of serialized conditions.
Use `@/scripts/condition_decomposer.py`