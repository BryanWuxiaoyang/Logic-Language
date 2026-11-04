"""Record-field interpretation of eligible_ids.lp; IDs are hashable."""


def eligible_ids(users):
    return {
        user["id"]
        for user in users
        if user["active"] and user["age"] >= 18
    }


if __name__ == "__main__":
    users = [
        {"id": 1, "active": True, "age": 18},
        {"id": 1, "active": True, "age": 22},
        {"id": 2, "active": True, "age": 17},
        {"id": 3, "active": False, "age": 40},
    ]
    print(sorted(eligible_ids(users)))
