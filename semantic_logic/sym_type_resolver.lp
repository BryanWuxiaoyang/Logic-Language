$import module_AST.lp
$import module_AST_pred_stmts.lp

Sym_type
class_sym_type
Sym_type ~ class_sym_type
pure_sym_type
Sym_type ~ pure_sym_type
func_sym_type
Sym_type ~ func_sym_type
pred_sym_type
Sym_type ~ pred_sym_type

Stmt::is_inheriting_function: (_stmt, _sym) => _bool

Stmt::is_call_sym_in_func_stmt: (_stmt, _sym) => _bool

Stmt::is_func_sym: (_stmt, _sym) => _bool
    _bool = (_stmt.is_inheriting_function(_sym) || _stmt.is_call_sym_in_func_stmt(_sym))

Stmt::is_inheriting_predicate: (_stmt, _sym) => _bool

Stmt::is_call_sym_in_pred_stmt: (_stmt, _sym) => _bool

Stmt::is_pred_sym: (_stmt, _sym) => _bool
    _bool = (_stmt.is_func_sym(_sym) && _stmt.is_inheriting_predicate(_sym) && _stmt.is_call_sym_in_pred_stmt(_sym))

Stmt::is_class_sym: (_stmt, _sym) => _bool
    _bool = _sym.is_capital_letter

Stmt::is_pure_sym: (_stmt, _sym) => _bool
    _bool = !((_stmt.is_func_sym(_sym) || _stmt.is_class_sym(_sym)))

Stmt::get_sym_type: (_stmt, _sym) => _sym_type
    |- _stmt.is_class_sym(_sym)
        _sym_type = class_sym_type
    |- !(_stmt.is_class_sym(_sym))
        |- _stmt.is_func_sym(_sym)
            |- _stmt.is_pred_sym(_sym)
                _sym_type = pred_sym_type
            |- !(_stmt.is_pred_sym(_sym))
                _sym_type = func_sym_type
        |- !(_stmt.is_func_sym(_sym))
            _sym_type = pure_sym_type
