"""Fabrique de petits documents d'essai, sans bibliothèque : bureautique (formats ouverts et Microsoft) et PDF. Pour les essais et le banc."""
import io
import zipfile
from xml.sax.saxutils import escape


def archive(members, mimetype=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as pack:
        if mimetype:
            pack.writestr(zipfile.ZipInfo('mimetype'), mimetype, compress_type=zipfile.ZIP_STORED)
        for name, text in members.items():
            pack.writestr(name, text)
    return out.getvalue()


def docx(*paragraphs, header=None):
    """Traitement de texte Microsoft : chaque paragraphe est coupé en deux passages de mise en forme, comme le fait un vrai logiciel."""
    runs = lambda text: f'<w:r><w:t>{escape(text[:len(text) // 2])}</w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>{escape(text[len(text) // 2:])}</w:t></w:r>'
    body = ''.join(f'<w:p>{runs(text)}</w:p>' for text in paragraphs)
    members = {'[Content_Types].xml': '<Types/>', 'word/document.xml': f'<?xml version="1.0"?><w:document xmlns:w="urn:w"><w:body>{body}</w:body></w:document>'}
    if header:
        members['word/header1.xml'] = f'<w:hdr xmlns:w="urn:w"><w:p><w:r><w:t>{escape(header)}</w:t></w:r></w:p></w:hdr>'
    return archive(members)


def xlsx(*cells):
    return archive({'[Content_Types].xml': '<Types/>', 'xl/workbook.xml': '<workbook/>',
                    'xl/sharedStrings.xml': '<sst xmlns="urn:s">' + ''.join(f'<si><t>{escape(cell)}</t></si>' for cell in cells) + '</sst>'})


def pptx(*slides):
    return archive({'[Content_Types].xml': '<Types/>', **{f'ppt/slides/slide{index}.xml': f'<p:sld xmlns:p="urn:p" xmlns:a="urn:a"><p:txBody><a:p><a:r><a:t>{escape(text)}</a:t></a:r></a:p></p:txBody></p:sld>'
                                                           for index, text in enumerate(slides, 1)}})


def odt(*paragraphs, kind='text'):
    body = ''.join(f'<text:p>{escape(text)}</text:p>' for text in paragraphs)
    return archive({'content.xml': f'<?xml version="1.0"?><office:document-content xmlns:office="urn:o" xmlns:text="urn:t"><office:body><office:{kind}>{body}</office:{kind}></office:body></office:document-content>'},
                   mimetype='application/vnd.oasis.opendocument.' + kind)


def pdf(*lines):
    """PDF d'une page, texte en clair, écrit à la main."""
    parts = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
             b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>']
    shown = b''.join(b'(' + line.encode('cp1252').replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)') + b') Tj 0 -20 Td ' for line in lines)
    stream = b'BT /F1 12 Tf 72 760 Td ' + shown + b'ET'
    parts.append(b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream')
    parts.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
    out, offsets = b'%PDF-1.4\n', []
    for index, part in enumerate(parts, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % index + part + b'\nendobj\n'
    table = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(parts) + 1) + b''.join(b'%010d 00000 n \n' % offset for offset in offsets)
    return out + b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(parts) + 1, table)
