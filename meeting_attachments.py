"""Ephemeral, leader-only PDF attachment merging for the Meeting Pack.

The caller supplies bytes in the requested order; no uploads are saved to
Ward Tracker storage or attached to activity/campaign documents.
"""
from io import BytesIO
import json

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

MAX_FILES = 5
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_EXTRA_PAGES = 100


class MeetingAttachmentError(ValueError):
    pass


def validate_pdf_attachment(filename: str, data: bytes) -> PdfReader:
    if not isinstance(filename, str) or not filename.lower().endswith('.pdf'):
        raise MeetingAttachmentError('Only PDF attachments are supported.')
    if not data or len(data) > MAX_FILE_BYTES:
        raise MeetingAttachmentError('Each PDF must be 25 MB or smaller.')
    if not data.lstrip().startswith(b'%PDF-'):
        raise MeetingAttachmentError('One attachment is not a valid PDF.')
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise MeetingAttachmentError('Password-protected PDFs are not supported.')
        if not len(reader.pages):
            raise MeetingAttachmentError('The attachment contains no pages.')
        return reader
    except MeetingAttachmentError:
        raise
    except (PdfReadError, ValueError, TypeError, KeyError, OSError) as exc:
        raise MeetingAttachmentError('One attachment could not be read as a PDF.') from exc


def _ordered_pages(original: PdfReader, readers: list[PdfReader], sequence: list[dict]):
    """Validate all page references before writing a single output page."""
    if not isinstance(sequence, list) or not sequence or len(sequence) > len(original.pages) + MAX_EXTRA_PAGES:
        raise MeetingAttachmentError('The slide order is empty or too long.')
    seen = set()
    output = []
    for item in sequence:
        if not isinstance(item, dict) or set(item) not in ({'kind', 'page'}, {'kind', 'file', 'page'}):
            raise MeetingAttachmentError('The slide order contains an invalid item.')
        kind, page = item.get('kind'), item.get('page')
        if type(page) is not int or page < 1:
            raise MeetingAttachmentError('Slide page numbers must be positive integers.')
        if kind == 'generated':
            if set(item) != {'kind', 'page'}:
                raise MeetingAttachmentError('A generated slide must contain only its page number.')
            key = ('generated', page)
            if page > len(original.pages):
                raise MeetingAttachmentError('The selected Meeting Pack slide does not exist.')
            output.append((original.pages[page - 1], False))
        elif kind == 'attachment':
            if set(item) != {'kind', 'file', 'page'}:
                raise MeetingAttachmentError('An attached PDF page must name its file and page.')
            index = item.get('file')
            if type(index) is not int or not 0 <= index < len(readers):
                raise MeetingAttachmentError('The selected PDF attachment does not exist.')
            if page > len(readers[index].pages):
                raise MeetingAttachmentError('The selected attachment page does not exist.')
            key = ('attachment', index, page)
            output.append((readers[index].pages[page - 1], True))
        else:
            raise MeetingAttachmentError('Unknown slide type.')
        if key in seen:
            raise MeetingAttachmentError('The same slide cannot appear twice.')
        seen.add(key)
    if sum(is_attachment for _, is_attachment in output) > MAX_EXTRA_PAGES:
        raise MeetingAttachmentError('Attachments can contain at most 100 pages in total.')
    return output


def combine_meeting_pdf(
    base_pdf: bytes,
    attachments: list[tuple[str, bytes]],
    sequence: list[dict] | None = None,
) -> bytes:
    """Combine the selected pages in exact order; no document data is persisted."""
    if len(attachments) > MAX_FILES or (sequence is None and not attachments):
        raise MeetingAttachmentError('Add between 1 and 5 PDFs.')
    if sum(len(data) for _, data in attachments) > MAX_TOTAL_BYTES:
        raise MeetingAttachmentError('The combined attachments must be 100 MB or smaller.')
    try:
        original = PdfReader(BytesIO(base_pdf), strict=True)
        readers = [validate_pdf_attachment(name, data) for name, data in attachments]
        if sum(len(reader.pages) for reader in readers) > MAX_EXTRA_PAGES:
            raise MeetingAttachmentError('Attachments can contain at most 100 pages in total.')
        if sequence is None:
            # Backwards-compatible API: the original pack followed by whole PDFs.
            ordered = [(page, False) for page in original.pages]
            ordered += [(page, True) for reader in readers for page in reader.pages]
        else:
            ordered = _ordered_pages(original, readers, sequence)
        writer = PdfWriter()
        for page, external in ordered:
            if external:
                # Don't import actions, links or interactive annotations from PDFs.
                writer.add_page(page, excluded_keys=['/Annots', '/AA', '/OpenAction'])
            else:
                writer.add_page(page)
        writer.add_metadata({'/Title': 'Ward Tracker Leadership Meeting Pack with attachments'})
        out = BytesIO()
        writer.write(out)
        return out.getvalue()
    except MeetingAttachmentError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as exc:
        raise MeetingAttachmentError('The PDF attachments could not be combined.') from exc
