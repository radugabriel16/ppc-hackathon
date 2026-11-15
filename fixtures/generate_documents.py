"""Build content-based parser fixtures, synthetic identities and a mixed demo ZIP.
Run from repo root: PYTHONPATH=backend:. python fixtures/generate_documents.py
Dependencies: backend/requirements-test.txt. Does not connect to a database.
"""
import io
import json
from pathlib import Path
import zipfile

from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from app.document_intake.identity import demo_cnp

ROOT = Path(__file__).with_name('documents')


def make_pdf(title, body, *, font='Helvetica', x=60, y=750):
    stream=io.BytesIO(); c=canvas.Canvas(stream,pagesize=A4)
    c.setFont(font,15)
    for line in title.split('\n'):
        c.drawString(x,y,line);y-=24
    y-=24;c.setFont(font,11)
    for line in body.split('\n'):
        c.drawString(x,y,line);y-=18
    c.save();return stream.getvalue()


def main():
    ROOT.mkdir(exist_ok=True)
    pdfmetrics.registerFont(TTFont('FixtureSerif', str(ROOT/'fonts/LiberationSerif-Regular.ttf')))
    expected={}
    def save(name,data,reason,kind=None):
        (ROOT/name).write_bytes(data)
        expected[name]={'reason':reason,'detectedType':kind}
    for i in (1,2):
        for approval in (False,True):
            kind='CONNECTION_APPROVAL' if approval else 'REQUEST_FORM'
            title='AVIZ DE RACORDARE' if approval else 'CERERE DE RACORDARE'
            label='C.N.P.:\n' if i==2 else 'CNP '
            body=f'Subsemnatul Demo Client {i}, {label}{demo_cnp(i)}, solicit racordarea.\nDeclar că cererea de racordare este în dosar și accept condițiile.'
            # Deliberately misleading file names; type must follow visible title.
            if i==2:
                body=body.replace('că','ca').replace('în','in').replace('și','si').replace('condițiile','conditiile')
            filename=f'{i}_'+('carte_identitate.pdf' if approval else 'aviz.pdf')
            save(filename,make_pdf(title,body,font='Times-Roman' if i==2 else 'FixtureSerif',x=80 if i==2 else 60,y=710 if i==2 else 750),None,kind)
    save('invalid_checksum.pdf',make_pdf('CERERE DE RACORDARE',f'Subsemnatul Demo, CNP {demo_cnp(3)[:-1]}9, solicit racordarea.'),'CNP_INVALID','REQUEST_FORM')
    save('unknown_client.pdf',make_pdf('CERERE DE RACORDARE',f'Subsemnatul Demo, CNP {demo_cnp(999)}, solicit racordarea.'),'CUSTOMER_NOT_FOUND','REQUEST_FORM')
    save('both_titles.pdf',make_pdf('CERERE DE RACORDARE\nAVIZ DE RACORDARE',f'Subsemnatul Demo, CNP {demo_cnp(1)}'),'AMBIGUOUS_TYPE')
    save('no_title.pdf',make_pdf('DOCUMENT NECUNOSCUT',f'Subsemnatul Demo, CNP {demo_cnp(1)}'),'UNRECOGNIZED_TYPE')
    save('two_cnps.pdf',make_pdf('CERERE DE RACORDARE',f'Subsemnatul Demo, CNP {demo_cnp(1)}, CNP {demo_cnp(2)}'),'CNP_AMBIGUOUS','REQUEST_FORM')
    save('identity.pdf',make_pdf('CARTE DE IDENTITATE',f'Subsemnatul Demo, CNP {demo_cnp(1)}'),'IDENTITY_DOCUMENT','ID')
    image=Image.new('RGB',(1000,600),'white');draw=ImageDraw.Draw(image)
    draw.text((50,60),'IDENTITY CARD - SYNTHETIC DEMO ONLY',fill='black')
    draw.text((50,130),'Demo Client 1',fill='black')
    stream=io.BytesIO();image.save(stream,format='JPEG')
    save('identity.jpg',stream.getvalue(),'NO_EXTRACTABLE_TEXT')
    stream=io.BytesIO();image.save(stream,format='PDF')
    save('scanned.pdf',stream.getvalue(),'NO_EXTRACTABLE_TEXT')
    encrypted=PdfWriter();encrypted.append(PdfReader(io.BytesIO(make_pdf('CERERE DE RACORDARE','Subsemnatul Demo'))));encrypted.encrypt('demo-only')
    stream=io.BytesIO();encrypted.write(stream)
    save('encrypted.pdf',stream.getvalue(),'PARSE_ERROR')
    save('corrupt.pdf',b'%PDF-1.7\ncorrupted demo bytes','PARSE_ERROR')
    save('request.pdf.txt',b'CERERE DE RACORDARE - not a PDF','UNSUPPORTED_FORMAT')
    (ROOT/'expected.json').write_text(json.dumps(expected,indent=2)+'\n')
    clients=[{'externalCode':f'DEMO-1-{i:02d}','name':f'Demo Client {i}','cnp':demo_cnp(i)} for i in range(1,7)]
    (ROOT/'demo-clients.json').write_text(json.dumps(clients,indent=2)+'\n')
    with zipfile.ZipFile(ROOT/'demo-batch.zip','w',zipfile.ZIP_DEFLATED) as zip:
        for name in expected:zip.write(ROOT/name,name)
    print(f'Generated {len(expected)} synthetic files and demo-batch.zip')


if __name__=='__main__':main()
