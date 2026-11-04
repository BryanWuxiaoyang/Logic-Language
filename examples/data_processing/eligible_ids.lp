User
Value
Id
Predicate

# Vocabulary: these functions read fields of a user record.
active: _user => _is_active
Predicate ~ active
age: _user => _value
user_id: _user => _id

# Input records represent a finite set of users; output IDs form a set.
eligible_ids: _users => _ids
    _ids = {
        | _user
        User ~ _user
        _user ∈ _users
        active(_user)
        age(_user) >= 18
        => user_id(_user)
    }
