import io
import subprocess
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from app.document_intake.identity import demo_cnp, valid_cnp
from app.document_intake.parser import classify, normalize, parse


def pdf(title='CERERE DE RACORDARE', content=None):
    out=io.BytesIO()
    c=canvas.Canvas(out)
    c.drawString(60,750,title)
    c.drawString(60,700,content or f'Subsemnatul Demo Client, CNP {demo_cnp(1)}, solicit racordarea.')
    c.drawString(60,650,'Declar ca datele sunt corecte.')
    c.save()
    return out.getvalue()


def test_normalize_and_valid_cnp():
    assert normalize('  șţî â\nă ŞȚ  ') == 'STI A A ST'
    for i in range(1,20):
        assert valid_cnp(demo_cnp(i))
    assert not valid_cnp('0000000000001')
    assert not valid_cnp(demo_cnp(1)[:-1]+str((int(demo_cnp(1)[-1])+1)%10))
    assert not valid_cnp('5990230400011')


@pytest.mark.parametrize('title,kind',[('CERERE DE RACORDARE','REQUEST_FORM'),('AVIZ DE RACORDARE','CONNECTION_APPROVAL')])
def test_pdf_classification_ignores_filename_and_metadata(title,kind):
    # Input intentionally has no filename parameter, not even for fallback.
    result=parse(pdf(title))
    assert result.reason is None
    assert result.detected_type == kind
    assert result.cnp == demo_cnp(1)


def test_title_area_not_mentions_in_body():
    value=classify(f'AVIZ DE RACORDARE\nSubsemnatul Demo, CNP {demo_cnp(1)}, solicit avizul.\nDeclar ca cererea de racordare este depusa.')
    assert value.detected_type=='CONNECTION_APPROVAL' and value.reason is None
    value=classify(f'DOCUMENT DIFERIT\nSubsemnatul Demo, CNP {demo_cnp(1)}, solicit racordarea.\nCERERE DE RACORDARE')
    assert value.reason=='UNRECOGNIZED_TYPE'


@pytest.mark.parametrize('text,reason',[
 ('CERERE DE RACORDARE\nAVIZ DE RACORDARE\nSubsemnatul Demo','AMBIGUOUS_TYPE'),
 ('ALTE ACTE\nSubsemnatul Demo','UNRECOGNIZED_TYPE'),
 ('CARTE DE IDENTITATE\nSubsemnatul Demo','IDENTITY_DOCUMENT'),
 ('CERERE DE RACORDARE\nSubsemnatul Demo fara identificator','CNP_MISSING'),
 ('CERERE DE RACORDARE\nSubsemnatul Demo CNP 123','CNP_INVALID'),
 ('CERERE DE RACORDARE\nSubsemnatul Demo CNP 0000000000001','CNP_INVALID'),
 (f'CERERE DE RACORDARE\nSubsemnatul Demo CNP {demo_cnp(1)} CNP {demo_cnp(2)}','CNP_AMBIGUOUS')])
def test_review_reasons(text,reason):
    assert classify(text).reason==reason


def test_wrapped_title_and_label_and_first_paragraph_only():
    result=classify(f'CERERE DE\nRACORDARE\nSubsemnatul Demo, C.N.P.:\n{demo_cnp(1)}, solicit racordarea.\n\nCNP {demo_cnp(2)}')
    assert result.cnp==demo_cnp(1)
    result=classify(f'CERERE DE RACORDARE\nSubsemnatul Demo fara CNP.\n\nCNP {demo_cnp(1)}')
    assert result.cnp is None


def test_nontext_encrypted_corrupt_unsupported_and_timeout():
    assert parse(b'\xff\xd8\xffimage').reason=='NO_EXTRACTABLE_TEXT'
    assert parse(b'\x89PNG\r\n\x1a\nimage').reason=='NO_EXTRACTABLE_TEXT'
    assert parse(b'hello.pdf').reason=='UNSUPPORTED_FORMAT'
    assert parse(b'%PDF-invalid').reason=='PARSE_ERROR'
    blank=PdfWriter();blank.add_blank_page(width=595,height=842)
    buffer=io.BytesIO();blank.write(buffer)
    assert parse(buffer.getvalue()).reason=='NO_EXTRACTABLE_TEXT'
    encrypted=PdfWriter();encrypted.append(PdfReader(io.BytesIO(pdf())));encrypted.encrypt('secret')
    buffer=io.BytesIO();encrypted.write(buffer)
    assert parse(buffer.getvalue()).reason=='PARSE_ERROR'
    with patch('app.document_intake.parser.subprocess.run',side_effect=subprocess.TimeoutExpired('parser',10)):
        assert parse(pdf()).reason=='PARSE_ERROR'
    pages=PdfWriter()
    for _ in range(21):pages.add_blank_page(width=595,height=842)
    buffer=io.BytesIO();pages.write(buffer)
    assert parse(buffer.getvalue()).reason=='PARSE_ERROR'
