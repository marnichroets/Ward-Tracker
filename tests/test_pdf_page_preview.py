"""Every uploaded page must render its own independent preview."""
import base64
from io import BytesIO
from pypdf import PdfWriter
from PIL import Image
import pytest

from pdf_page_preview import pdf_page_thumbnails


def test_distinct_pdf_page_thumbnails():
    writer=PdfWriter()
    writer.add_blank_page(width=800,height=450)
    writer.add_blank_page(width=450,height=800)
    output=BytesIO();writer.write(output)
    thumbs=pdf_page_thumbnails('mixed.pdf',output.getvalue())
    assert len(thumbs)==2
    sizes=[]
    for item in thumbs:
        assert item.startswith('data:image/jpeg;base64,')
        image=Image.open(BytesIO(base64.b64decode(item.split(',',1)[1])))
        sizes.append(image.size)
    assert sizes[0] != sizes[1], 'Each preview uses that page’s real dimensions'


def test_pdf_preview_rejects_bad_files():
    with pytest.raises(ValueError):
        pdf_page_thumbnails('not-a-pdf.txt',b'bad')
