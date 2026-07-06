from sqlalchemy import Column, Table, Text

from app.core.orm import Base

# The `users` table itself is managed via raw SQL in app.core.database.init_db().
# This mirrors just enough of it in SQLAlchemy's metadata so ORM models elsewhere
# can declare a ForeignKey("users.id") that resolves during create_all().
users_table = Table(
    "users",
    Base.metadata,
    Column("id", Text, primary_key=True),
)
