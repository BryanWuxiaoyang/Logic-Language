
Str~Sym

Stmt
    ::bound_syms
    ::free_syms
    ::sub_stmts
    ::all_stmts: stmt => stmts
        |- stmt.sub_stmts = {}
            stmts = {stmt}
        |- stmt.sub_stmts \neq {}
            stmts = {stmt' \in stmt.sub_stmts => stmt'.all_stmts}
        # in the final module_AST, bound-symbol names must not conflict with
        # current-statement or ancestor bound-symbol names.

    ::all_bound_syms: stmt => syms
        syms = {| stmt' \in stmt.all_stmts => stmt'.bound_syms}

    ::all_free_syms: stmt => syms
        syms = {| stmt' \in stmt.all_stmts => stmt'.free_syms}

    ::active_free_syms: stmt => syms
        syms = stmt.all_free_syms - stmt.all_bound_syms

Stmt~Binding_stmt
    ::dst_sym
    ::src_stmt
    ::bound_syms: binding_stmt => syms
        syms = {}
    ::free_syms: binding_stmt => syms
        syms = {binding_stmt.dst_sym}
    ::sub_stmts: binding_stmt => stmts
        stmts = {binding_stmt.src_stmt}

Stmt~Literal_stmt

Stmt~Func_stmt
    ::call_sym
    ::arg_sym_list
    ::bound_syms: func_stmt => syms
        syms = {}
    ::free_syms: func_stmt => syms
        syms = func_stmt.arg_sym_list \union {func_stmt.call_sym}
    ::sub_stmts: func_stmt => stmts
        stmts = {}

Stmt ~ Proposition_stmt

Func_stmt~Pred_stmt
Proposition_stmt ~ Pred_stmt

Stmt~Module_stmt
    ::bound_syms
    ::free_syms: module_stmt => syms
        syms = {}

    ::premise_binding_stmts
    ::premise_proposition_stmts
    ::target_proposition_stmts
    ::sub_stmts: module_stmt => stmts
        stmts = module_stmt.premise_binding_stmts \union module_stmt.premise_proposition_stmts \union module_stmt.target_proposition_stmts

Module_stmt~Set_stmt

Module_stmt~Quantified_stmt
    ::quantifier_sym
Proposition_stmt~Quantified_stmt
