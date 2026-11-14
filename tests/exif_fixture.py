"""Fabrique des images d'essai avec bloc EXIF et vignette, sans bibliothèque d'images : pour les essais et le banc."""
import struct
import zlib

# Petit JPEG valide (8 × 8, gris) : sert d'image et de vignette quand l'essai n'a pas besoin de mieux.
TINY = bytes.fromhex(
    'ffd8ffe000104a46494600010100000100010000ffdb0043001b12141714111b1716171e1c1b2028422b28252528513a3d3042605565645f555d5b6a'
    '7899816a7190735b5d85b586909ea3abadab6780bcc9baa6c799a8aba4ffc0000b080008000801011100ffc400140001000000000000000000000000'
    '00000000ffc40014100100000000000000000000000000000000ffda0008010100003f003fffd9')


def tiff(date=None, orient=None, thumb=b'', model=None, order='<', taken=None, size=None):
    """Bloc TIFF d'un EXIF : IFD0 (appareil, orientation, date), sous-IFD (prise de vue, dimensions), IFD1 (vignette)."""
    text = lambda value: value.encode('ascii') + b'\x00'
    first, detail, second = [], [], []
    if model is not None:
        first.append((0x0110, 2, text(model)))
    if orient is not None:
        first.append((0x0112, 3, orient))
    if date is not None:
        first.append((0x0132, 2, text(date)))
    if taken is not None:
        detail.append((0x9003, 2, text(taken)))
    if size is not None:
        detail += [(0xA002, 4, size[0]), (0xA003, 4, size[1])]
    if detail:
        first.append((0x8769, 4, 'detail'))
    if thumb:
        second += [(0x0201, 4, 'thumb'), (0x0202, 4, len(thumb))]
    span = lambda entries: 2 + 12 * len(entries) + 4
    at = {'first': 8}
    at['detail'] = at['first'] + span(first)
    at['second'] = at['detail'] + (span(detail) if detail else 0)
    cursor = at['second'] + (span(second) if second else 0)
    extra = b''

    def pack(entries, following):
        nonlocal cursor, extra
        out = struct.pack(order + 'H', len(entries))
        for tag, kind, value in entries:
            if kind == 2:
                if len(value) <= 4:
                    out += struct.pack(order + 'HHI', tag, kind, len(value)) + value.ljust(4, b'\x00')
                else:
                    out += struct.pack(order + 'HHII', tag, kind, len(value), cursor)
                    extra += value
                    cursor += len(value)
            elif kind == 3:
                out += struct.pack(order + 'HHIH', tag, kind, 1, value) + b'\x00\x00'
            else:
                out += struct.pack(order + 'HHII', tag, kind, 1, at[value] if isinstance(value, str) else value)
        return out + struct.pack(order + 'I', following)

    # Les chaînes longues se rangent après les trois répertoires, la vignette en dernier : son adresse dépend d'elles.
    strings = sum(len(value) for entries in (first, detail) for _, kind, value in entries if kind == 2 and len(value) > 4)
    at['thumb'] = cursor + strings
    head = (b'II' if order == '<' else b'MM') + struct.pack(order + 'HI', 42, 8)
    body = pack(first, at['second'] if second else 0)
    if detail:
        body += pack(detail, 0)
    if second:
        body += pack(second, 0)
    return head + body + extra + thumb


def jpeg(image=TINY, **exif):
    """JPEG complet : l'image donnée, précédée d'un bloc EXIF si des champs sont demandés."""
    if not exif:
        return image
    block = b'Exif\x00\x00' + tiff(**exif)
    return b'\xff\xd8\xff\xe1' + struct.pack('>H', len(block) + 2) + block + image[2:]


def png(width=3, height=2):
    """PNG valide, uni."""
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    rows = b''.join(b'\x00' + b'\x80' * width for _ in range(height))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')
