
str~sym

stmt
    ::bound_syms
    ::free_syms
    ::sub_stmts

    ::all_stmts
        |- stmt.sub_stmts = {}
            all_stmts = {stmt}
        |- stmt.sub_stmts \neq {}
            all_stmts = {stmt' \in stmt.sub_stmts => stmt'.all_stmts}
        # in the final module_AST, symbol-name conflicts have already been resolved by freshening, 
        # so every active symbol name at any scope point is unambiguous.

    ::all_bound_syms = {| stmt' \in stmt.all_stmts => stmt'.bound_syms}

    ::all_free_syms = {| stmt' \in stmt.all_stmts => stmt'.free_syms}

    ::active_free_syms = stmt.all_free_syms - stmt.all_bound_syms

stmt~binding_stmt
    ::dst_sym
    ::src_stmt
    ::bound_syms = {}
    ::free_syms = {binding_stmt.dst_sym}
    ::sub_stmts = {binding_stmt.src_stmt}

stmt~literal_stmt

stmt~func_stmt
    ::call_sym
    ::arg_sym_list
    ::bound_syms = {}
    ::free_syms = func_stmt.arg_sym_list \union {func_stmt.call_sym}
    ::sub_stmts = {}
FS = func_stmt

func_stmt~pred_stmt
PS = pred_stmt

stmt~module_stmt
    ::bound_syms
    ::free_syms = {}

    ::premise_binding_stmts
    ::premise_PSs
    ::target_PSs
    ::sub_stmts = module_stmt.premise_binding_stmts \union module_stmt.premise_PSs \union module_stmt.target_PSs

module_stmt~set_stmt

module_stmt~quantified_stmt
    ::quantifier_sym

