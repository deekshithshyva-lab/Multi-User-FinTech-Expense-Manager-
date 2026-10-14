import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Budget, Category, CategoryRule, Transaction, User
from app.services.seeding import DEFAULT_CATEGORIES, seed_user_defaults


def make_user(email="a@example.com"):
    user = User(email=email, full_name="Test User")
    user.set_password("correct horse battery")
    db.session.add(user)
    db.session.flush()
    return user


def make_tx(user, fingerprint="f1"):
    return Transaction(user_id=user.id, date=dt.date(2026, 1, 1), description="x",
                       amount=Decimal("-5.00"), fingerprint=fingerprint)


def test_password_is_hashed_and_verified(app):
    user = make_user()
    assert user.password_hash != "correct horse battery"
    assert user.check_password("correct horse battery")
    assert not user.check_password("wrong")


def test_email_is_normalised_and_unique(app):
    make_user("Alice@Example.com")
    assert User.query.one().email == "alice@example.com"
    with pytest.raises(IntegrityError):
        make_user("ALICE@example.com")


def test_seed_defaults(app):
    user = make_user()
    seed_user_defaults(user)
    db.session.commit()
    assert Category.query.filter_by(user_id=user.id).count() == len(DEFAULT_CATEGORIES)
    assert CategoryRule.query.filter_by(user_id=user.id, pattern="walmart").one().category.name == "Groceries"


def test_fingerprint_unique_per_user_only(app):
    u1, u2 = make_user("a@x.com"), make_user("b@x.com")
    db.session.add_all([make_tx(u1), make_tx(u2)])   # same fingerprint, different users: OK
    db.session.commit()
    db.session.add(make_tx(u1))                      # duplicate for the same user: rejected
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_one_budget_per_category(app):
    user = make_user()
    seed_user_defaults(user)
    cat = Category.query.filter_by(user_id=user.id, name="Groceries").one()
    db.session.add(Budget(user_id=user.id, category_id=cat.id, monthly_limit=Decimal("400")))
    db.session.commit()
    db.session.add(Budget(user_id=user.id, category_id=cat.id, monthly_limit=Decimal("500")))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
