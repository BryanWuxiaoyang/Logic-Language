Value
Set
Function

# Model: finite sets of integer values and an integer-valued function.
# Boolean equations define properties; they do not assert or prove that
# every function has these properties.
is_mapping: (_function, _domain_set, _codomain_set) => _is_mapping
    _is_mapping = ∀{
        | _value
        | _value ∈ _domain_set
        _function(_value) ∈ _codomain_set
    }

is_injective: (_function, _domain_set) => _is_injective
    _is_injective = ∀{
        | _value, _other_value
        | _value ∈ _domain_set, _other_value ∈ _domain_set
        | _function(_value) = _function(_other_value)
        _value = _other_value
    }

is_surjective: (_function, _domain_set, _codomain_set) => _is_surjective
    _is_surjective = ∀{
        | _value
        | _value ∈ _codomain_set
        ∃{
            | _other_value
            Value ~ _other_value
            _other_value ∈ _domain_set
            _function(_other_value) = _value
        }
    }
