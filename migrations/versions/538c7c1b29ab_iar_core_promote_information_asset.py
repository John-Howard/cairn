"""iar core promote information asset

Revision ID: 538c7c1b29ab
Revises: 403eb9d6f598
Create Date: 2026-07-27 19:31:05.906504

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '538c7c1b29ab'
down_revision: Union[str, Sequence[str], None] = '403eb9d6f598'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table('system_asset', 'information_asset')
    op.rename_table('activity_system', 'activity_asset')
    op.rename_table('system_securitymeasure', 'asset_securitymeasure')

    with op.batch_alter_table('activity_asset') as batch_op:
        batch_op.alter_column('system_id', new_column_name='asset_id')

    with op.batch_alter_table('asset_securitymeasure') as batch_op:
        batch_op.alter_column('system_id', new_column_name='asset_id')

    sa.Enum('SYSTEM', 'DATABASE', 'SOFTWARE', 'PAPER', 'PHYSICAL', name='assettype').create(
        op.get_bind(), checkfirst=True
    )
    sa.Enum('IN_USE', 'RETIRING', 'DISPOSED', name='assetstatus').create(
        op.get_bind(), checkfirst=True
    )
    sa.Enum(
        'NOT_CLASSIFIED', 'OFFICIAL', 'OFFICIAL_SENSITIVE', name='securityclassification'
    ).create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table('information_asset') as batch_op:
        batch_op.add_column(
            sa.Column(
                'asset_type',
                sa.Enum('SYSTEM', 'DATABASE', 'SOFTWARE', 'PAPER', 'PHYSICAL', name='assettype'),
                nullable=False,
                server_default='SYSTEM',
            )
        )
        batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('iao_user_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('custodian', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('business_function_id', sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                'classification',
                sa.Enum(
                    'NOT_CLASSIFIED', 'OFFICIAL', 'OFFICIAL_SENSITIVE',
                    name='securityclassification',
                ),
                nullable=False,
                server_default='NOT_CLASSIFIED',
            )
        )
        batch_op.add_column(
            sa.Column(
                'contains_personal_data', sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch_op.add_column(
            sa.Column(
                'status',
                sa.Enum('IN_USE', 'RETIRING', 'DISPOSED', name='assetstatus'),
                nullable=False,
                server_default='IN_USE',
            )
        )
        batch_op.add_column(sa.Column('next_review_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('supplier_entity_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            'fk_information_asset_iao_user_id', 'user', ['iao_user_id'], ['id']
        )
        batch_op.create_foreign_key(
            'fk_information_asset_business_function_id',
            'business_function',
            ['business_function_id'],
            ['id'],
        )
        batch_op.create_foreign_key(
            'fk_information_asset_supplier_entity_id',
            'legal_entity',
            ['supplier_entity_id'],
            ['id'],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('information_asset') as batch_op:
        batch_op.drop_constraint('fk_information_asset_supplier_entity_id', type_='foreignkey')
        batch_op.drop_constraint(
            'fk_information_asset_business_function_id', type_='foreignkey'
        )
        batch_op.drop_constraint('fk_information_asset_iao_user_id', type_='foreignkey')
        batch_op.drop_column('notes')
        batch_op.drop_column('supplier_entity_id')
        batch_op.drop_column('next_review_date')
        batch_op.drop_column('status')
        batch_op.drop_column('contains_personal_data')
        batch_op.drop_column('classification')
        batch_op.drop_column('business_function_id')
        batch_op.drop_column('custodian')
        batch_op.drop_column('iao_user_id')
        batch_op.drop_column('description')
        batch_op.drop_column('asset_type')

    sa.Enum(name='securityclassification').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='assetstatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='assettype').drop(op.get_bind(), checkfirst=True)

    with op.batch_alter_table('asset_securitymeasure') as batch_op:
        batch_op.alter_column('asset_id', new_column_name='system_id')

    with op.batch_alter_table('activity_asset') as batch_op:
        batch_op.alter_column('asset_id', new_column_name='system_id')

    op.rename_table('asset_securitymeasure', 'system_securitymeasure')
    op.rename_table('activity_asset', 'activity_system')
    op.rename_table('information_asset', 'system_asset')
