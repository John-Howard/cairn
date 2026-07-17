"""user email and oidc subject

Revision ID: d12ef3e173a7
Revises: fc08e7c30aac
Create Date: 2026-07-17 11:34:42.518540

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd12ef3e173a7'
down_revision: Union[str, Sequence[str], None] = 'fc08e7c30aac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # batch_alter_table so the unique constraints work on SQLite (table rebuild)
    with op.batch_alter_table('user') as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('oidc_subject', sa.String(), nullable=True))
        batch_op.create_unique_constraint('uq_user_email', ['email'])
        batch_op.create_unique_constraint('uq_user_oidc_subject', ['oidc_subject'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('user') as batch_op:
        batch_op.drop_constraint('uq_user_oidc_subject', type_='unique')
        batch_op.drop_constraint('uq_user_email', type_='unique')
        batch_op.drop_column('oidc_subject')
        batch_op.drop_column('email')
