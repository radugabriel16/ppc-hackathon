"""Application-level transaction tests with SQLite and encrypted in-memory storage.
PostGIS triggers, PostgreSQL advisory locks and real S3 remain covered separately
by test_document_intake_integration.py on the Compose stack.
"""
import io
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from geoalchemy2 import Geometry
from sqlalchemy import create_engine, MetaData, LargeBinary, JSON, event, select, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.datastructures import UploadFile

from app import models
from app.core.policy_schema import load_policies
from app.core.settings import get_settings
from app.document_intake import service
from app.document_intake.identity import demo_cnp, fingerprint, masked
from app.documents.encryption import DocumentKey
from app.models.clients import Client, ClientDocument, ConnectionCase, DocumentType
from app.models.document_intake import DocumentIntakeItem
from app.models.enums import CaseStatus, ClientType, FileStatus, StorageBackend
from app.models.files import File
from app.policies.service import PolicyManager
from app.storage.base import StoredObject, StorageUnavailable
from tests.test_document_intake import pdf


@pytest.fixture
def workflow(tmp_path,monkeypatch):
    keydir=tmp_path/'secrets';keydir.mkdir();(keydir/'cnp_hmac_key').write_text('11'*32)
    monkeypatch.setattr(get_settings(),'secrets_dir',str(keydir))
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    @event.listens_for(engine,'connect')
    def functions(conn,_):
        for name in ('AsEWKB','ST_AsEWKB','GeomFromEWKT','ST_GeomFromEWKT'):
            conn.create_function(name,1,lambda value:value)
    copied=MetaData()
    for table in models.Base.metadata.sorted_tables:
        cloned=table.to_metadata(copied)
        for col in cloned.c:
            if isinstance(col.type,Geometry):col.type=LargeBinary()
            elif isinstance(col.type,JSONB):col.type=JSON()
    copied.create_all(engine)
    actor,region,client_id,case_id=(uuid.uuid4() for _ in range(4))
    with Session(engine) as db:
        db.execute(copied.tables['app_users'].insert().values(id=actor,username='operator-test',password_hash='not-used',role='OPERATOR'))
        db.execute(copied.tables['regions'].insert().values(id=region,code='TEST',name='Test region'))
        db.add(Client(id=client_id,region_id=region,external_code='TEST-CLIENT',name_enc=b'Demo',email_enc=b'demo@example.invalid',
            client_type=ClientType.RESIDENTIAL,cnp_hmac=fingerprint(demo_cnp(1)),cnp_masked=masked(demo_cnp(1))))
        db.add(ConnectionCase(id=case_id,client_id=client_id,status=CaseStatus.OPEN,opened_at=service.now()))
        for kind in service.TYPES:
            db.add(DocumentType(code=kind,name=kind,required_for_connection=True))
        db.commit()
    @asynccontextmanager
    async def unlocked(_):yield
    monkeypatch.setattr(service,'get_catalog_engine',lambda:engine)
    monkeypatch.setattr(service,'upload_lock',unlocked)
    monkeypatch.setattr('app.files.service.get_catalog_engine',lambda:engine)
    monkeypatch.setattr('app.uploads.locking.upload_lock',unlocked)
    class Storage:
        def __init__(self):self.data={};self.fail=False
        async def put(self,category,key,stream,size):
            if self.fail:raise StorageUnavailable('test outage')
            self.data[key]=stream.read();return StoredObject(key,size)
        async def get(self,category,key):yield self.data[key]
        async def delete(self,category,key):self.data.pop(key,None)
    storage=Storage()
    config=load_policies(Path(__file__).resolve().parents[2]/'config/policies.yaml')
    manager=PolicyManager(config,{StorageBackend.s3:storage})
    key=DocumentKey('test-key',b'k'*32)
    async def upload(data,**kwargs):
        upload=UploadFile(filename='misleading-identity-name.jpg',file=io.BytesIO(data))
        item_id=await service.store_item(upload,manager,key,actor,**kwargs)
        await service.process_item(item_id,manager,key)
        with Session(engine) as db:return db.get(DocumentIntakeItem,item_id)
    yield SimpleNamespace(schema=copied,engine=engine,upload=upload,storage=storage,client_id=client_id,case_id=case_id,actor=actor,manager=manager,key=key)
    engine.dispose()


@pytest.mark.anyio
async def test_storage_first_link_idempotency_and_manual_replacement(workflow):
    w=workflow;data=pdf(content=f'Subsemnatul Demo, CNP {demo_cnp(1)}, solicit racordarea.')
    first=await w.upload(data)
    assert first.status=='AUTO_LINKED',first.error_detail
    assert all(value!=data and b'Subsemnatul' not in value for value in w.storage.data.values())
    with Session(w.engine) as db:
        file=db.get(File,first.file_id)
        assert file.status==FileStatus.READY and file.last_verified_at and file.encrypted
        assert file.region_id is not None
    duplicate=await w.upload(data)
    assert duplicate.status=='AUTO_LINKED' and duplicate.file_id==first.file_id
    changed=await w.upload(pdf(content=f'Subsemnatul Alt Demo, CNP {demo_cnp(1)}, solicit racordarea.'))
    assert changed.review_reason=='TYPE_ALREADY_PRESENT'
    with Session(w.engine) as db:
        item=db.get(DocumentIntakeItem,changed.id)
        service.link(db,item,db.get(Client,w.client_id),'REQUEST_FORM',w.actor,manual=True,replace=True)
        db.commit()
        docs=db.scalars(select(ClientDocument).where(ClientDocument.case_id==w.case_id)).all()
        assert len(docs)==2 and sum(doc.superseded_at is not None for doc in docs)==1


@pytest.mark.anyio
async def test_mismatch_identity_unknown_and_failed_storage_do_not_link(workflow):
    w=workflow
    mismatch=await w.upload(pdf('AVIZ DE RACORDARE',f'Subsemnatul Demo, CNP {demo_cnp(1)}'),
        requested_customer=w.client_id,requested_type='REQUEST_FORM')
    assert mismatch.review_reason=='CONTENT_MISMATCH'
    identity=await w.upload(pdf('CARTE DE IDENTITATE',f'Subsemnatul Demo, CNP {demo_cnp(1)}'))
    assert identity.review_queue=='IDENTITY'
    unknown=await w.upload(pdf(content=f'Subsemnatul Demo, CNP {demo_cnp(99)}'))
    assert unknown.review_reason=='CUSTOMER_NOT_FOUND'
    broken=await w.upload(b'%PDF-broken')
    assert broken.review_reason=='PARSE_ERROR'
    w.storage.fail=True
    failed=await w.upload(pdf())
    assert failed.status=='FAILED'
    with Session(w.engine) as db:
        assert db.scalar(select(func.count()).select_from(ClientDocument))==0

@pytest.mark.anyio
async def test_checklist_completion_resolves_existing_issue_atomically(workflow):
    import struct
    from app.models.issues import MapIssue
    from app.models.enums import IssueStatus
    w=workflow;asset,issue_id=uuid.uuid4(),uuid.uuid4()
    point=struct.pack('<bIdd',1,1,26.1,44.4)
    with Session(w.engine) as db:
        region=db.get(Client,w.client_id).region_id
        db.execute(w.schema.tables['network_assets'].insert().values(id=asset,region_id=region,code='TEST-ASSET',name='Asset',type='SUBSTATION',geometry=point))
        db.execute(w.schema.tables['map_issues'].insert().values(id=issue_id,asset_id=asset,
            client_id=w.client_id,case_id=w.case_id,location=point,type='MISSING_DOCUMENTS',
            title='Missing documents',severity='LOW',status='OPEN',created_at=service.now(),version=1,is_historical=False))
        db.commit()
    body=f'Subsemnatul Demo, CNP {demo_cnp(1)}, solicit racordarea.'
    for title in ['CERERE DE RACORDARE','AVIZ DE RACORDARE']:
        assert (await w.upload(pdf(title,body))).status=='AUTO_LINKED'
    with Session(w.engine) as db:
        assert db.get(MapIssue,issue_id).status==IssueStatus.OPEN
    identity=await w.upload(pdf('CARTE DE IDENTITATE',body))
    with Session(w.engine) as db:
        item=db.get(DocumentIntakeItem,identity.id)
        service.link(db,item,db.get(Client,w.client_id),'ID',w.actor,manual=True)
        db.commit()
        issue=db.get(MapIssue,issue_id)
        assert issue.status==IssueStatus.RESOLVED and issue.resolved_at is not None
        assert db.scalar(select(func.count()).select_from(ClientDocument))==3


@pytest.mark.anyio
async def test_api_batch_review_lookup_and_prefilled_confirmation(workflow,monkeypatch):
    import httpx
    from fastapi import FastAPI
    from app.document_intake import router as routes
    from app.auth.dependencies import get_current_user
    from app.auth.middleware import csrf_origin_middleware
    from app.core.db import get_catalog_db
    from app.core.errors import register_exception_handlers
    from app.models.enums import UserRole
    w=workflow
    @asynccontextmanager
    async def unlocked(_):yield
    monkeypatch.setattr(routes,'get_catalog_engine',lambda:w.engine)
    from app.auth.security import LoginRateLimiter
    monkeypatch.setattr(routes,'_lookup_limiter',LoginRateLimiter(limit=1))
    monkeypatch.setattr(routes,'upload_lock',unlocked)
    from app.files.router import router as files_router
    from app.documents.router import router as documents_router
    app=FastAPI();app.include_router(routes.router);app.include_router(files_router);app.include_router(documents_router);register_exception_handlers(app)
    app.middleware('http')(csrf_origin_middleware)
    app.state.policy_manager,app.state.document_key=w.manager,w.key
    app.dependency_overrides[get_current_user]=lambda:SimpleNamespace(id=w.actor,role=UserRole.OPERATOR)
    def db():
        with Session(w.engine) as session:yield session
    app.dependency_overrides[get_catalog_db]=db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://localhost',
        headers={'Origin':'https://localhost','X-CSRF-Token':'test'},cookies={'filegrid_csrf':'test'}) as client:
        r=await client.post('/api/v1/customer-documents/batches',files=[
            ('files',('identity.jpg',pdf(content=f'Subsemnatul Demo, CNP {demo_cnp(1)}'),'image/jpeg')),
            ('files',('request.pdf',b'%PDF-broken','application/pdf'))])
        assert r.status_code==202,r.text
        path='/api/v1/customer-documents/batches/'+r.json()['batchId']
        batch=(await client.get(path)).json()
        for i in batch['items']:await service.process_item(uuid.UUID(i['id']),w.manager,w.key)
        batch=(await client.get(path)).json()
        linked=next(i for i in batch['items'] if i['status']=='AUTO_LINKED')
        preview=await client.get(f"/api/v1/files/{linked['fileId']}/download?inline=true")
        assert preview.status_code==200 and preview.content.startswith(b'%PDF-')
        assert preview.headers['Content-Disposition'].startswith('inline;')
        cases=await client.get('/api/v1/connection-cases',params={'complete':'false','search':'TEST-CLIENT'})
        assert cases.status_code==200 and cases.json()['totalElements']==1,cases.text
        assert sum(d['status']=='PRESENT' for d in cases.json()['items'][0]['documents'])==1
        assert batch['status']=='COMPLETED' and batch['autoLinkedCount']==1 and batch['reviewCount']==1
        item=next(i for i in batch['items'] if i['status']=='NEEDS_REVIEW')
        invalid=await client.post(f"/api/v1/customer-documents/review-items/{item['id']}/confirm",json={
            'documentType':'ID','cnp':'0000000000001','version':item['version']})
        assert invalid.status_code==422
        lookup=await client.get('/api/v1/customers/lookup',params={'cnp':demo_cnp(1)})
        assert lookup.status_code==200 and lookup.json()['customerId']==str(w.client_id)
        assert demo_cnp(1) not in lookup.text
        limited=await client.get('/api/v1/customers/lookup',params={'cnp':demo_cnp(1)})
        assert limited.status_code==429 and limited.json()['code']=='LOOKUP_RATE_LIMITED'
        confirmed=await client.post(f"/api/v1/customer-documents/review-items/{item['id']}/confirm",json={
            'documentType':'ID','cnp':demo_cnp(1),'version':item['version']})
        assert confirmed.status_code==200 and confirmed.json()['status']=='CONFIRMED',confirmed.text
        rejected=await client.post(f"/api/v1/customer-documents/review-items/{item['id']}/reject",json={'version':item['version'],'reason':'Old version'})
        assert rejected.status_code==409
        pending=await client.post('/api/v1/customer-documents',files={'file':('a.jpg',b'\xff\xd8\xffimage','image/jpeg')})
        assert pending.status_code==201,pending.text
        pending=pending.json()
        rejected=await client.post(f"/api/v1/customer-documents/review-items/{pending['id']}/reject",json={'version':pending['version'],'reason':'Unusable document'})
        assert rejected.status_code==200 and rejected.json()['status']=='REJECTED'
        client.headers.pop('X-CSRF-Token')
        csrf=await client.post('/api/v1/customer-documents',files={'file':('a.pdf',pdf(),'application/pdf')})
        assert csrf.status_code==403
        app.dependency_overrides.pop(get_current_user)
        assert (await client.get('/api/v1/customer-documents/review-items')).status_code==401

@pytest.mark.anyio
async def test_prefilled_no_text_needs_explicit_confirmation_and_no_pii_logs(workflow,caplog):
    w=workflow
    plain=b'\xff\xd8\xffsynthetic-image-only'
    waiting=await w.upload(plain,requested_customer=w.client_id,requested_type='ID')
    assert waiting.status=='NEEDS_REVIEW' and waiting.review_reason=='NO_EXTRACTABLE_TEXT'
    approved=await w.upload(plain,requested_customer=w.client_id,requested_type='ID',confirm_manual=True)
    assert approved.status=='CONFIRMED'
    assert all(demo_cnp(1) not in record.getMessage() for record in caplog.records)
