$import module_AST.lp

quantified_stmt::function_decl_stmt: quantified_stmt => function_decl_stmt
    # Some quantified_stmt can reduce to a function-decl, which is more helpful for program-implementation

typed_sym
    ::sym
    ::class_sym

quantified_stmt~function_decl_stmt
    ::quantifier_sym = '\all'

    ::func_sym

    ::input_typed_sym_list
    ::output_typed_sym_list

    ::input_sym_list
        | _id < function_decl_stmt.input_typed_sym_list.size
        | _typed_sym = function_decl_stmt.input_typed_sym_list[_id]
        input_sym_list[_id] = _typed_sym.sym
    
    ::output_sym_list
        | _id < function_decl_stmt.output_typed_sym_list.size
        | _typed_sym = function_decl_stmt.output_typed_sym_list[_id]
        output_sym_list[_id] = _typed_sym.sym

    ::func_bound_syms
    ::bound_syms = function_decl_stmt.input_sym_list \union function_decl_stmt.output_sym_list \union function_decl_stmt.func_bound_syms

    ::function_stmt
        function_stmt.call_sym = function_decl_stmt.func_sym
        function_stmt.arg_sym_list = function_decl_stmt.input_sym_list

    ::output_equality_stmts
    ::func_premise_equality_stmts
    ::premise_equality_stmts = function_decl_stmt.output_equality_stmts \union function_decl_stmt.func_premise_equality_stmts

    ::premise_PSs
    ::target_PSs

function_decl_stmt~single_output_function_decl_stmt
    ::output_sym_list
        output_sym_list.size = 1

    ::output_equality_stmts
        # output_sym_list[0] = F(input_sym_list)

function_decl_stmt~multi_output_function_decl_stmt
    ::tmp_output_sym
    ::output_equality_stmts
        # tmp_output_sym = F(input_sym_list)
        # output_sym_list[0] = tmp_output_sym[0]
        # output_sym_list[1] = tmp_output_sym[1]
        # ...
