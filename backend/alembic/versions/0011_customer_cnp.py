"""Store recoverable customer CNPs encrypted, alongside HMAC lookup identities."""
from alembic import op
import sqlalchemy as sa

revision = "0011_customer_cnp"
down_revision = "0010_document_intake"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clients", sa.Column("cnp_enc", sa.LargeBinary(), nullable=True))


def downgrade():
    op.drop_column("clients", "cnp_enc")
