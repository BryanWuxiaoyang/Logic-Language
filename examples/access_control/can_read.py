"""Document-field interpretation of can_read.lp."""


def can_read(user, doc):
    return user == doc["owner"] or user in doc["shared"]


if __name__ == "__main__":
    doc = {"owner": "alice", "shared": {"bob"}}
    print([can_read(user, doc) for user in ("alice", "bob", "carol")])
