"""Requires migrated Compose catalog/S3 and generated secrets; no mocked storage."""
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import get_catalog_engine
from app.core.settings import get_settings
from app.document_intake.identity import demo_cnp, fingerprint, masked
from app.main import create_app
from app.document_intake.service import run_intake
from app.models.audit import AuditEvent
from app.models.clients import Client, ClientDocument, ConnectionCase
from app.models.document_intake import DocumentIntakeBatch, DocumentIntakeItem
from app.models.enums import CaseStatus, ClientType, IssueType, IssueStatus
from app.models.geography import Region, NetworkAsset
from app.models.issues import MapIssue
from tests.test_document_intake import pdf

pytestmark=pytest.mark.integration
BASE='/api/v1'


@pytest.fixture
def intake_api():
    settings=get_settings(); client_id=uuid.uuid4();case_id=uuid.uuid4()
    # UUID-derived synthetic date/serial; use an unused valid fixture identity.
    with Session(get_catalog_engine()) as db:
        serial=next(i for i in range(100,999) if db.scalar(select(Client.id).where(Client.cnp_hmac==fingerprint(demo_cnp(i)))) is None)
        cnp=demo_cnp(serial)
        region=db.scalar(select(Region).order_by(Region.code))
        db.add(Client(id=client_id,region_id=region.id,external_code='intake-'+client_id.hex,
            name_enc=b'demo-only',email_enc=b'demo@example.invalid',client_type=ClientType.RESIDENTIAL,
            cnp_hmac=fingerprint(cnp),cnp_masked=masked(cnp)))
        db.flush()
        db.add(ConnectionCase(id=case_id,client_id=client_id,status=CaseStatus.OPEN,opened_at=datetime.now(timezone.utc)))
        db.commit()
    app=create_app(); item_ids=[];batch_ids=[]
    with TestClient(app,base_url='https://localhost',headers={'Origin':'https://localhost'}) as client:
        r=client.post(BASE+'/auth/login',json={'username':'operator','password':(Path(settings.secrets_dir)/'operator_password').read_text().strip()})
        assert r.status_code==200,r.text
        client.headers['X-CSRF-Token']=client.cookies['filegrid_csrf']
        def upload(data,**fields):
            r=client.post(BASE+'/customer-documents',files={'file':('a-misleading-identity-name.jpg',data,'image/jpeg')},data=fields)
            assert r.status_code==201,r.text
            item=r.json();item_ids.append(uuid.UUID(item['id']));return item
        try:
            yield client,upload,cnp,client_id,case_id,item_ids,batch_ids
        finally:
            with Session(get_catalog_engine()) as db:
                db.execute(delete(MapIssue).where(MapIssue.case_id==case_id))
                db.execute(delete(ClientDocument).where(ClientDocument.case_id==case_id))
                db.execute(delete(AuditEvent).where(AuditEvent.entity_id.in_(item_ids)))
                db.execute(delete(DocumentIntakeItem).where(DocumentIntakeItem.id.in_(item_ids)))
                db.execute(delete(DocumentIntakeBatch).where(DocumentIntakeBatch.id.in_(batch_ids)))
                db.execute(delete(ConnectionCase).where(ConnectionCase.id==case_id))
                db.execute(delete(Client).where(Client.id==client_id));db.commit()


def test_auto_link_idempotency_manual_replace_and_complete(intake_api):
    client,upload,cnp,client_id,case_id,_,_=intake_api
    body=f'Subsemnatul Demo, CNP {cnp}, solicit racordarea.'
    first=upload(pdf(content=body))
    assert first['status']=='AUTO_LINKED' and first['customerId']==str(client_id)
    again=upload(pdf(content=body))
    # ReportLab's document ID is random: exact-byte idempotency uses the SAME input.
    exact=pdf(content=body)
    one=upload(exact)
    if one['status']=='NEEDS_REVIEW':
        r=client.post(BASE+f"/customer-documents/review-items/{one['id']}/confirm",json={
            'cnp':cnp,'documentType':'REQUEST_FORM','version':one['version'],'replaceExisting':True})
        assert r.status_code==200,r.text
        one=r.json()
    duplicate=upload(exact)
    assert duplicate['status']=='AUTO_LINKED' and duplicate['fileId']==one['fileId']
    approval=upload(pdf('AVIZ DE RACORDARE',body))
    assert approval['status']=='AUTO_LINKED'
    identity=upload(pdf('CARTE DE IDENTITATE',body))
    assert identity['status']=='NEEDS_REVIEW' and identity['reviewQueue']=='IDENTITY'
    confirmed=client.post(BASE+f"/customer-documents/review-items/{identity['id']}/confirm",json={
        'cnp':cnp,'documentType':'ID','version':identity['version']})
    assert confirmed.status_code==200,confirmed.text
    checklist=client.get(BASE+f'/connection-cases/{case_id}/documents').json()
    assert checklist['missingDocumentTypes']==[]
    stale=client.post(BASE+f"/customer-documents/review-items/{identity['id']}/reject",json={'reason':'test','version':identity['version']})
    assert stale.status_code==409


def test_prefilled_mismatch_reject_and_batch_isolation(intake_api):
    client,upload,cnp,client_id,_,item_ids,batch_ids=intake_api
    mismatch=upload(pdf('AVIZ DE RACORDARE',f'Subsemnatul Demo, CNP {cnp}'),customerId=str(client_id),documentType='REQUEST_FORM')
    assert mismatch['reviewReason']=='CONTENT_MISMATCH'
    r=client.post(BASE+f"/customer-documents/review-items/{mismatch['id']}/reject",json={'reason':'Wrong type','version':mismatch['version']})
    assert r.status_code==200 and r.json()['status']=='REJECTED'
    response=client.post(BASE+'/customer-documents/batches',files=[
        ('files',('aviz.jpg',pdf(content=f'Subsemnatul Demo, CNP {cnp}'),'application/pdf')),
        ('files',('request.pdf',b'%PDF-broken','application/pdf')),
        ('files',('other.pdf',b'plain text','text/plain'))])
    assert response.status_code==202,response.text
    batch_id=response.json()['batchId'];batch_ids.append(uuid.UUID(batch_id))
    deadline=time.monotonic()+60
    while True:
        anyio.run(run_intake,client.app.state.policy_manager,client.app.state.document_key)
        batch=client.get(BASE+'/customer-documents/batches/'+batch_id).json()
        if batch['status']=='COMPLETED':break
        assert time.monotonic()<deadline,'Worker did not finish batch'
        time.sleep(1)
    item_ids.extend(uuid.UUID(i['id']) for i in batch['items'])
    assert batch['autoLinkedCount']==1 and batch['reviewCount']==2 and batch['failedCount']==0,batch
    # Session and CSRF remain enforced on the new endpoints.
    client.headers.pop('X-CSRF-Token')
    assert client.post(BASE+'/customer-documents',files={'file':('a.pdf',pdf(),'application/pdf')}).status_code==403
    client.cookies.clear()
    assert client.get(BASE+'/customer-documents/review-items').status_code==401
