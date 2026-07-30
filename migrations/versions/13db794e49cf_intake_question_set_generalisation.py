"""intake question set generalisation

Revision ID: 13db794e49cf
Revises: fd7079e47765
Create Date: 2026-07-30 08:33:06.916300

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '13db794e49cf'
down_revision: Union[str, Sequence[str], None] = 'fd7079e47765'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    sa.Enum('ACTIVITY', 'ASSET', name='intakequestionset').create(
        op.get_bind(), checkfirst=True
    )

    with op.batch_alter_table('intake_question') as batch_op:
        batch_op.add_column(
            sa.Column(
                'question_set',
                sa.Enum('ACTIVITY', 'ASSET', name='intakequestionset'),
                nullable=False,
                server_default='ACTIVITY',
            )
        )

    with op.batch_alter_table('intake_submission') as batch_op:
        batch_op.add_column(
            sa.Column(
                'question_set',
                sa.Enum('ACTIVITY', 'ASSET', name='intakequestionset'),
                nullable=False,
                server_default='ACTIVITY',
            )
        )
        batch_op.alter_column('activity_name', new_column_name='subject_name')
        batch_op.add_column(sa.Column('asset_id', sa.String(), nullable=True))
        batch_op.create_foreign_key(
            'fk_intake_submission_asset_id', 'information_asset', ['asset_id'], ['id']
        )

    with op.batch_alter_table('intake_gap') as batch_op:
        batch_op.add_column(sa.Column('asset_id', sa.String(), nullable=True))
        batch_op.create_foreign_key(
            'fk_intake_gap_asset_id', 'information_asset', ['asset_id'], ['id']
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('intake_gap') as batch_op:
        batch_op.drop_constraint('fk_intake_gap_asset_id', type_='foreignkey')
        batch_op.drop_column('asset_id')

    with op.batch_alter_table('intake_submission') as batch_op:
        batch_op.drop_constraint('fk_intake_submission_asset_id', type_='foreignkey')
        batch_op.drop_column('asset_id')
        batch_op.alter_column('subject_name', new_column_name='activity_name')
        batch_op.drop_column('question_set')

    with op.batch_alter_table('intake_question') as batch_op:
        batch_op.drop_column('question_set')

    sa.Enum(name='intakequestionset').drop(op.get_bind(), checkfirst=True)
