
Sym
    # Compiler-emitted symbol AST nodes carry `source_loc` for diagnostics.
    # Generated symbols set `generated=true` and use the authored source
    # symbol/expression location as `source_loc`.
    ::name
    ::source_name

Stmt
    ::bound_syms
    ::free_syms
    ::sub_stmts
    ::all_stmts: _stmt => _stmts
        |- _stmt.sub_stmts = {}
            _stmts = {_stmt}
        |- _stmt.sub_stmts \neq {}
            _stmts = {| _stmt' | _stmt' \in _stmt.sub_stmts => _stmt'.all_stmts} \union {_stmt}
        # in the final module_AST, bound-symbol names must not conflict with
        # current-statement or ancestor bound-symbol names.

    ::all_bound_syms = {| _stmt' \in _stmt.all_stmts => _stmt'.bound_syms}

    ::all_free_syms = {| _stmt' \in _stmt.all_stmts => _stmt'.free_syms}

    ::real_free_syms: _stmt => _syms
        | _free_syms = _stmt.free_syms \union (\union({| _stmt' | _stmt' \in _stmt.sub_stmts => _stmt'.real_free_syms}))
        _syms = _free_syms - _stmt.bound_syms

Stmt~Binding_stmt
Binding_stmt
    ::dst_sym
    ::src_stmt
    ::bound_syms = {}
    ::free_syms = {_binding_stmt.dst_sym}
    ::sub_stmts = {_binding_stmt.src_stmt}

Literal_stmt
Stmt~Literal_stmt

Stmt~Func_stmt
Func_stmt
    ::call_sym
    ::arg_sym_list
    ::bound_syms = {}
    ::free_syms = _func_stmt.arg_sym_list \union {_func_stmt.call_sym}
    ::sub_stmts = {}

Proposition_stmt
Stmt ~ Proposition_stmt

Pred_stmt
Func_stmt~Pred_stmt
Proposition_stmt ~ Pred_stmt

Stmt~Module_stmt
Module_stmt
    ::bound_syms
    ::free_syms = {}

    ::premise_binding_stmts
    ::premise_proposition_stmts
    ::target_proposition_stmts
    ::sub_stmts = _module_stmt.premise_binding_stmts \union _module_stmt.premise_proposition_stmts \union _module_stmt.target_proposition_stmts

Set_stmt
Module_stmt~Set_stmt

Module_stmt~Quantified_stmt
Quantified_stmt
    ::quantifier_sym
Proposition_stmt~Quantified_stmt

AST_node
AST_node ~ Sym
AST_node ~ Stmt
