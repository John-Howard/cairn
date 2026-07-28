"""asset multi function

Revision ID: fd7079e47765
Revises: 538c7c1b29ab
Create Date: 2026-07-28 09:25:32.425702

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fd7079e47765'
down_revision: Union[str, Sequence[str], None] = '538c7c1b29ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'asset_businessfunction',
        sa.Column('asset_id', sa.String(), nullable=False),
        sa.Column('business_function_id', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['asset_id'], ['information_asset.id']),
        sa.ForeignKeyConstraint(['business_function_id'], ['business_function.id']),
        sa.PrimaryKeyConstraint('asset_id', 'business_function_id'),
    )
    op.execute(
        "INSERT INTO asset_businessfunction (asset_id, business_function_id) "
        "SELECT id, business_function_id FROM information_asset "
        "WHERE business_function_id IS NOT NULL"
    )
    with op.batch_alter_table('information_asset') as batch_op:
        batch_op.drop_column('business_function_id')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('information_asset') as batch_op:
        batch_op.add_column(sa.Column('business_function_id', sa.String(), nullable=True))
        batch_op.create_foreign_key(
            'fk_information_asset_business_function_id',
            'business_function',
            ['business_function_id'],
            ['id'],
        )
    op.execute(
        "UPDATE information_asset SET business_function_id = ("
        "SELECT MIN(business_function_id) FROM asset_businessfunction "
        "WHERE asset_businessfunction.asset_id = information_asset.id"
        ")"
    )
    op.drop_table('asset_businessfunction')
