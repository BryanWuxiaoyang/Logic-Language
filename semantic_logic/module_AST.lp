
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

stmt~term
stmt~proposition

stmt~sym
    ::bound_syms = {}
    ::free_syms = {sym}
    ::sub_stmts = {}
term~sym

stmt~equality_stmt
    ::dst_sym
    ::src_term
    ::bound_syms = {}
    ::free_syms = {equality_stmt.dst_sym}
    ::sub_stmts = {equality_stmt.src_term}
proposition~equality_stmt

stmt~call_stmt
    ::call_sym
    ::arg_sym_list
    ::bound_syms = {}
    ::free_syms = call_stmt.arg_sym_list \union {call_stmt.call_sym}
    ::sub_stmts = {}

call_stmt~predicate_stmt
proposition~predicate_stmt

call_stmt~function_stmt
term~function_stmt

stmt~module_stmt
    ::bound_syms
    ::free_syms = {}

    ::premise_equality_stmts
    ::premise_PSs
    ::target_PSs
    ::sub_stmts = module_stmt.premise_equality_stmts \union module_stmt.premise_PSs \union module_stmt.target_PSs

module_stmt~set_stmt
term~set_stmt

module_stmt~quantified_stmt
    ::quantifier_sym
proposition~quantified_stmt

predicate_stmt~inherit_stmt
    ::class_sym
    ::src_sym

    ::call_sym = '~'
    ::arg_sym_list = {inherit_stmt.class_sym, inherit_stmt.src_sym}

predicate_stmt~and_stmt
    ::call_sym = '\land'

predicate_stmt~or_stmt
    ::call_sym = '\lor'

predicate_stmt~not_stmt
    ::call_sym = '\lnot'
    ::sym
    ::arg_sym_list [not_stmt.sym]

predicate_stmt~implies_stmt
    ::premise_sym
    ::target_sym
    ::arg_sym_list = [implies_stmt.premise_sym, implies_stmt.target_sym]
