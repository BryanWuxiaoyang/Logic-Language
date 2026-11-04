User
Document
Predicate

# Vocabulary: ownership and membership in a document's sharing recipients.
is_owner: (_user, _document) => _is_owner
Predicate ~ is_owner
shared_with: (_document, _user) => _is_shared
Predicate ~ shared_with

can_read: (_user, _document) => _is_allowed
    _is_allowed = is_owner(_user, _document) || shared_with(_document, _user)
