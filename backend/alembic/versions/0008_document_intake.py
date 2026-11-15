"""Durable document intake and HMAC-only client matching."""
from alembic import op
import sqlalchemy as sa

revision = '0008_document_intake'
down_revision = '0007_forecast_calibration'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('clients', sa.Column('cnp_hmac', sa.String(64)))
    op.add_column('clients', sa.Column('cnp_masked', sa.String(16)))
    op.create_index('ix_clients_cnp_hmac', 'clients', ['cnp_hmac'], unique=True)
    op.add_column('client_documents', sa.Column('superseded_at', sa.TIMESTAMP(timezone=True)))
    op.alter_column('files', 'region_id', nullable=True)
    op.create_check_constraint('ck_unassigned_connection_document', 'files', "region_id IS NOT NULL OR category = 'CONNECTION_DOCUMENT'")
    op.create_table('document_intake_batches',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('created_by', sa.Uuid(), sa.ForeignKey('app_users.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('finished_at', sa.TIMESTAMP(timezone=True)),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('sealed', sa.Boolean(), nullable=False),
        *[sa.Column(name, sa.Integer(), nullable=False) for name in
          ('total_count','auto_linked_count','review_count','failed_count')])
    op.create_index('ix_document_intake_batches_status', 'document_intake_batches', ['status'])
    op.create_table('document_intake_items',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('batch_id', sa.Uuid(), sa.ForeignKey('document_intake_batches.id', ondelete='CASCADE')),
        sa.Column('file_id', sa.Uuid(), sa.ForeignKey('files.id', ondelete='RESTRICT')),
        sa.Column('original_file_name', sa.String(512), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('review_queue', sa.String(16)), sa.Column('review_reason', sa.String(64)),
        sa.Column('detected_type', sa.String(64)), sa.Column('extracted_cnp_hmac', sa.String(64)),
        sa.Column('cnp_masked', sa.String(16)), sa.Column('confirmed_type', sa.String(64)),
        *[sa.Column(name, sa.Uuid(), sa.ForeignKey('clients.id')) for name in
          ('suggested_customer_id','customer_id','requested_customer_id')],
        sa.Column('requested_type', sa.String(64)), sa.Column('confirm_manual', sa.Boolean(), nullable=False),
        sa.Column('reviewed_by', sa.Uuid(), sa.ForeignKey('app_users.id')),
        sa.Column('reviewed_at', sa.TIMESTAMP(timezone=True)), sa.Column('error_detail', sa.String(128)),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False))
    for name in ('batch_id','file_id','status','review_queue'):
        op.create_index('ix_document_intake_items_' + name, 'document_intake_items', [name])
    op.execute("UPDATE document_types SET required_for_connection=false WHERE code='PROOF_OF_ADDRESS'")
    op.execute("""INSERT INTO document_types(id,code,name,required_for_connection)
        VALUES ('8cd303ee-e638-4f55-b83d-1595f12eaf24','CONNECTION_APPROVAL','Connection approval',true)
        ON CONFLICT (code) DO UPDATE SET required_for_connection=true""")


def downgrade():
    op.drop_table('document_intake_items')
    op.drop_table('document_intake_batches')
    op.execute("UPDATE document_types SET required_for_connection=true WHERE code='PROOF_OF_ADDRESS'")
    op.execute("UPDATE document_types SET required_for_connection=false WHERE code='CONNECTION_APPROVAL'")
    op.drop_constraint('ck_unassigned_connection_document', 'files', type_='check')
    # A downgrade requires the intake queue to be empty; never silently delete PII files.
    op.alter_column('files', 'region_id', nullable=False)
    op.drop_column('client_documents', 'superseded_at')
    op.drop_index('ix_clients_cnp_hmac', table_name='clients')
    op.drop_column('clients', 'cnp_masked')
    op.drop_column('clients', 'cnp_hmac')
