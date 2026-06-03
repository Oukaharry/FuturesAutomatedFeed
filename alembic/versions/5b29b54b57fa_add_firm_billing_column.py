"""add_firm_billing_column

Revision ID: 5b29b54b57fa
Revises: 44e368d8bfce
Create Date: 2026-04-14 17:23:49.376388

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b29b54b57fa'
down_revision: Union[str, Sequence[str], None] = '44e368d8bfce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Column may already exist if schema was created/updated outside Alembic.
    op.execute(
        "ALTER TABLE clients_data ADD COLUMN IF NOT EXISTS firm_billing TEXT DEFAULT '{}'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('clients_data', 'firm_billing')
    pass
    # ### end Alembic commands ###
