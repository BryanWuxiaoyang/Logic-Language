$import object_AST.lp

List

Quantified_stmt~Func_decl_stmt
Func_decl_stmt
    ::quantifier_sym = '∀'

    ::func_sym

    ::input_sym_list
    ::output_sym_list

    ::input_sym_list: _func_decl_stmt => _list
        | _id < _func_decl_stmt.input_sym_list.size
        | _typed_sym = _func_decl_stmt.input_sym_list[_id]
        _list[_id] = _typed_sym.sym
    
    ::output_sym_list: _func_decl_stmt => _list
        | _id < _func_decl_stmt.output_sym_list.size
        | _typed_sym = _func_decl_stmt.output_sym_list[_id]
        _list[_id] = _typed_sym.sym

    ::body_bound_syms
    ::bound_syms = _func_decl_stmt.input_sym_list \union _func_decl_stmt.output_sym_list \union _func_decl_stmt.body_bound_syms

Class_decl_stmt
    ::class_sym
    ::func_decl_stmts

Class_field_decl_stmt
    ::class_sym
    ::field_sym
    ::output_sym

Class_member_stmt
    ::class_sym
    ::member_stmt
