Value

# Computation dependencies.
quadruple: _value => _out_value
    | _twice_value = _value + _value
    _out_value = _twice_value + _twice_value

# Conditional guarantees.
quadruple: _value => _out_value
    | _value >= 0
    _out_value >= 0

quadruple: _value => _out_value
    | _value < 0
    _out_value < 0

# Order preservation; a specification obligation, not a proof.
quadruple: _value => _out_value
    ∀{| _other_value | _other_value <= _value | quadruple(_other_value) <= _out_value}
