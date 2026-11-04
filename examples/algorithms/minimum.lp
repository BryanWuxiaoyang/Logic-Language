Value
Set

# Model: a finite set of integers with the ordinary order.
minimum: _value_set => _out_value
    | ∃{
        | _value
        Value ~ _value
        _value ∈ _value_set
    }
    _out_value ∈ _value_set
    ∀{| _other_value | _other_value ∈ _value_set | _out_value <= _other_value}
