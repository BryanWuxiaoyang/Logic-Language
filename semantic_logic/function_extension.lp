$import module_AST.lp

Quantified_stmt::get_func_decl_stmt: quantified_stmt => func_decl_stmt
    # Some quantified_stmt can reduce to a function-decl, which is more helpful for program-implementation

Typed_sym
    ::sym
    ::class_sym

Quantified_stmt~Func_decl_stmt
Func_decl_stmt
    ::quantifier_sym: func_decl_stmt => sym
        sym = '\all'

    ::func_sym

    ::input_typed_sym_list
    ::output_typed_sym_list

    ::input_sym_list: func_decl_stmt => list
        | _id < func_decl_stmt.input_typed_sym_list.size
        | _typed_sym = func_decl_stmt.input_typed_sym_list[_id]
        list[_id] = _typed_sym.sym
    
    ::output_sym_list: func_decl_stmt => list
        | _id < func_decl_stmt.output_typed_sym_list.size
        | _typed_sym = func_decl_stmt.output_typed_sym_list[_id]
        list[_id] = _typed_sym.sym

    ::func_bound_syms
    ::bound_syms: func_decl_stmt => syms
        syms = func_decl_stmt.input_sym_list \union func_decl_stmt.output_sym_list \union func_decl_stmt.func_bound_syms

    ::function_stmt: func_decl_stmt => stmt
        stmt.call_sym = func_decl_stmt.func_sym
        stmt.arg_sym_list = func_decl_stmt.input_sym_list

    ::output_binding_stmts
    ::func_premise_binding_stmts
    ::premise_binding_stmts: func_decl_stmt => stmts
        stmts = func_decl_stmt.output_binding_stmts \union func_decl_stmt.func_premise_binding_stmts

    ::premise_proposition_stmts
    ::target_proposition_stmts

Func_decl_stmt~Single_output_func_decl_stmt
Single_output_func_decl_stmt
    ::output_sym_list: single_output_func_decl_stmt => list
        list.size = 1

    ::output_binding_stmts
        # output_sym_list[0] = F(input_sym_list)

Func_decl_stmt~Multi_output_func_decl_stmt
Multi_output_func_decl_stmt
    ::tmp_output_sym
    ::output_binding_stmts
        # tmp_output_sym = F(input_sym_list)
        # output_sym_list[0] = tmp_output_sym[0]
        # output_sym_list[1] = tmp_output_sym[1]
        # ...
