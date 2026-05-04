$import module_AST.lp
$import module_AST_pred_stmts.lp

Sym_type
Class_sym_type
Sym_type ~ Class_sym_type
Pure_sym_type
Sym_type ~ Pure_sym_type
Func_sym_type
Sym_type ~ Func_sym_type
Pred_sym_type
Sym_type ~ Pred_sym_type

Stmt::is_inheriting_function: (stmt, sym) => bool

Stmt::is_call_sym_in_func_stmt: (stmt, sym) => bool

Stmt::is_func_sym: (stmt, sym) => bool
    bool = (stmt.is_inheriting_function(sym) || stmt.is_call_sym_in_func_stmt(sym))

Stmt::is_inheriting_predicate: (stmt, sym) => bool

Stmt::is_call_sym_in_pred_stmt: (stmt, sym) => bool

Stmt::is_pred_sym: (stmt, sym) => bool
    bool = (stmt.is_func_sym(sym) && stmt.is_inheriting_predicate(sym) && stmt.is_call_sym_in_pred_stmt(sym))

Stmt::is_class_sym: (stmt, sym) => bool
    bool = sym.is_capital_letter

Stmt::is_pure_sym: (stmt, sym) => bool
    bool = !((stmt.is_func_sym(sym) || stmt.is_class_sym(sym)))

Stmt::get_sym_type: (stmt, sym) => sym_type
    |- stmt.is_func_sym(sym)
        |- stmt.is_pred_sym(sym)
            sym_type = Pred_sym_type
        |- !(stmt.is_pred_sym(sym))
            sym_type = Func_sym_type
    |- !(stmt.is_func_sym(sym))
        |- stmt.is_class_sym(sym)
            sym_type = Class_sym_type
        |- !(stmt.is_class_sym(sym))
            sym_type = Pure_sym_type
