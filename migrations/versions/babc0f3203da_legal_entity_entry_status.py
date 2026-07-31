"""legal entity entry status

Revision ID: babc0f3203da
Revises: 13db794e49cf
Create Date: 2026-07-31 16:02:30.069028

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'babc0f3203da'
down_revision: Union[str, Sequence[str], None] = '13db794e49cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('legal_entity', sa.Column('entry_status', sa.Enum('PROPOSED', 'APPROVED', 'REJECTED', name='entrystatus'), nullable=False, server_default='APPROVED'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('legal_entity', 'entry_status')
