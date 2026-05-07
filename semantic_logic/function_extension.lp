$import module_AST.lp

List

Quantified_stmt::get_func_decl_stmt: _quantified_stmt => _func_decl_stmt
    # Some _quantified_stmt can reduce to a function-decl, which is more helpful for program-implementation

Typed_sym
    ::sym
    ::class_sym

Quantified_stmt~Func_decl_stmt
Func_decl_stmt
    ::quantifier_sym: _func_decl_stmt => _quantifier_sym
        _quantifier_sym = '\all'

    ::func_sym

    ::input_typed_sym_list
    ::output_typed_sym_list

    ::input_sym_list: _func_decl_stmt => _list
        | _id < _func_decl_stmt.input_typed_sym_list.size
        | _typed_sym = _func_decl_stmt.input_typed_sym_list[_id]
        _list[_id] = _typed_sym.sym
    
    ::output_sym_list: _func_decl_stmt => _list
        | _id < _func_decl_stmt.output_typed_sym_list.size
        | _typed_sym = _func_decl_stmt.output_typed_sym_list[_id]
        _list[_id] = _typed_sym.sym

    ::func_bound_syms
    ::bound_syms: _func_decl_stmt => _syms
        _syms = _func_decl_stmt.input_sym_list \union _func_decl_stmt.output_sym_list \union _func_decl_stmt.func_bound_syms

    ::function_stmt: _func_decl_stmt => _stmt
        _stmt.call_sym = _func_decl_stmt.func_sym
        _stmt.arg_sym_list = _func_decl_stmt.input_sym_list

    ::output_binding_stmts
    ::func_premise_binding_stmts
    ::premise_binding_stmts: _func_decl_stmt => _stmts
        _stmts = _func_decl_stmt.output_binding_stmts \union _func_decl_stmt.func_premise_binding_stmts

    ::premise_proposition_stmts
    ::target_proposition_stmts

Func_decl_stmt~Single_output_func_decl_stmt
Single_output_func_decl_stmt
    ::output_sym_list: _single_output_func_decl_stmt => _list
        _list.size = 1

    ::output_binding_stmts
        # _output_sym_list[0] = F(_input_sym_list)

Func_decl_stmt~Multi_output_func_decl_stmt
Multi_output_func_decl_stmt
    ::tmp_output_sym
    ::output_binding_stmts
        # _tmp_output_sym = F(_input_sym_list)
        # _output_sym_list[0] = _tmp_output_sym[0]
        # _output_sym_list[1] = _tmp_output_sym[1]
        # ...
