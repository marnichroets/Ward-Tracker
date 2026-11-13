"""Temporary per-page thumbnails for Meeting Pack attachments (no persistence).

The browser PDF plug-in does not reliably honour #page= fragments in blob iframes.
Render each page independently, small enough for drag-and-drop preview cards.
"""
import base64
from io import BytesIO

import meeting_attachments


class PreviewError(ValueError):
    pass


def pdf_page_thumbnails(filename: str, data: bytes, *, max_edge: int = 800) -> list[str]:
    """Return JPEG data URIs in the exact page order of an uploaded PDF.

    In-memory only. Existing attachment limits are enforced before rendering.
    """
    reader = meeting_attachments.validate_pdf_attachment(filename, data)
    if len(reader.pages) > meeting_attachments.MAX_EXTRA_PAGES:
        raise PreviewError('A PDF can contain at most 100 pages.')
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise PreviewError('PDF page previews are not available on this server.') from exc

    try:
        pdf = pdfium.PdfDocument(data)
        output = []
        for idx in range(len(pdf)):
            page = pdf[idx]
            width, height = page.get_size()
            if width <= 0 or height <= 0:
                raise PreviewError('A PDF page has invalid dimensions.')
            # Small previews only. Never render original-resolution pages.
            scale = min(max_edge / max(width, height), 1.75)
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil().convert('RGB')
            buf = BytesIO()
            image.save(buf, format='JPEG', quality=76, optimize=True)
            output.append('data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode('ascii'))
            image.close()
            bitmap.close()
            page.close()
        pdf.close()
        return output
    except PreviewError:
        raise
    except Exception as exc:
        raise PreviewError('Could not render one or more PDF pages.') from exc
