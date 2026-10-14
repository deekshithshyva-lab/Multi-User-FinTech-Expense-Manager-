"""Default categories and starter auto-categorisation rules for new users."""
from ..extensions import db
from ..models import Category, CategoryKind, CategoryRule, MatchType, User

# name -> (kind, colour)
DEFAULT_CATEGORIES: dict[str, tuple[CategoryKind, str]] = {
    "Groceries": (CategoryKind.EXPENSE, "#22c55e"),
    "Dining": (CategoryKind.EXPENSE, "#f97316"),
    "Transport": (CategoryKind.EXPENSE, "#3b82f6"),
    "Utilities": (CategoryKind.EXPENSE, "#06b6d4"),
    "Housing": (CategoryKind.EXPENSE, "#8b5cf6"),
    "Entertainment": (CategoryKind.EXPENSE, "#ec4899"),
    "Health": (CategoryKind.EXPENSE, "#ef4444"),
    "Shopping": (CategoryKind.EXPENSE, "#eab308"),
    "Travel": (CategoryKind.EXPENSE, "#14b8a6"),
    "Fees": (CategoryKind.EXPENSE, "#64748b"),
    "Income": (CategoryKind.INCOME, "#10b981"),
    "Transfers": (CategoryKind.TRANSFER, "#94a3b8"),
}

# category -> [(pattern, priority)]; lower priority number = evaluated first.
DEFAULT_RULES: dict[str, list[tuple[str, int]]] = {
    "Groceries": [("walmart", 100), ("kroger", 100), ("whole foods", 100), ("trader joe", 100),
                  ("costco", 100), ("aldi", 100), ("tesco", 100), ("bigbasket", 100), ("supermarket", 100)],
    "Dining": [("uber eats", 50), ("starbucks", 100), ("mcdonald", 100), ("doordash", 100),
               ("swiggy", 100), ("zomato", 100), ("restaurant", 100), ("cafe", 100), ("pizza", 100)],
    "Transport": [("uber", 100), ("lyft", 100), ("shell", 100), ("chevron", 100), ("fuel", 100),
                  ("metro", 100), ("parking", 100)],
    "Utilities": [("electric", 100), ("water bill", 100), ("comcast", 100), ("verizon", 100),
                  ("at&t", 100), ("internet", 100), ("airtel", 100)],
    "Housing": [("rent", 100), ("mortgage", 100)],
    "Entertainment": [("netflix", 100), ("spotify", 100), ("hulu", 100), ("cinema", 100), ("steam", 100)],
    "Health": [("pharmacy", 100), ("cvs", 100), ("walgreens", 100), ("hospital", 100), ("clinic", 100)],
    "Shopping": [("amazon", 100), ("target", 100), ("ebay", 100), ("ikea", 100)],
    "Travel": [("airline", 100), ("airbnb", 100), ("booking.com", 100), ("delta air", 100), ("hotel", 100)],
    "Fees": [("service fee", 100), ("overdraft", 100), ("atm fee", 100)],
    "Income": [("salary", 100), ("payroll", 100), ("direct deposit", 100), ("interest paid", 100)],
    "Transfers": [("transfer", 100), ("credit card payment", 50), ("zelle", 100)],
}


def seed_user_defaults(user: User) -> None:
    """Create the default categories + rules for `user` (call once, right after registration)."""
    categories: dict[str, Category] = {}
    for name, (kind, color) in DEFAULT_CATEGORIES.items():
        categories[name] = Category(user=user, name=name, kind=kind, color=color)
        db.session.add(categories[name])

    for cat_name, rules in DEFAULT_RULES.items():
        for pattern, priority in rules:
            db.session.add(
                CategoryRule(user=user, category=categories[cat_name], pattern=pattern,
                             match_type=MatchType.CONTAINS, priority=priority)
            )
    db.session.flush()
