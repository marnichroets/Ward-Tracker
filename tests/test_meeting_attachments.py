"""PDF attachment merging must preserve order, discard unsafe annotations and bound input."""
import io
import unittest

from pypdf import PdfReader, PdfWriter

from meeting_attachments import (
    MeetingAttachmentError, combine_meeting_pdf,
    MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_EXTRA_PAGES,
)


def sample_pdf(w=200, h=200, pages=1):
    out = io.BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=w, height=h)
    writer.write(out)
    return out.getvalue()


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.base = sample_pdf(222, 300, 2)

    def test_order_and_pages_preserved(self):
        merged = combine_meeting_pdf(self.base, [('first.pdf', sample_pdf(300, 500)), ('two.PDF', sample_pdf(400, 600))])
        pages = PdfReader(io.BytesIO(merged)).pages
        self.assertEqual(len(pages), 4)
        self.assertEqual([int(p.mediabox.width) for p in pages], [222, 222, 300, 400])

    def test_custom_order_interleaves_and_removes_pages(self):
        pdf = combine_meeting_pdf(self.base, [('first.pdf', sample_pdf(333, 410, 2))], sequence=[
            {'kind':'generated','page':2},
            {'kind':'attachment','file':0,'page':2},
            {'kind':'generated','page':1},
        ])
        pages = PdfReader(io.BytesIO(pdf)).pages
        self.assertEqual([int(page.mediabox.width) for page in pages], [222,333,222])
        self.assertEqual(len(pages), 3, 'other pages must be omitted')

    def test_custom_order_allows_removed_attachments_and_selected_generated_pages(self):
        merged = combine_meeting_pdf(self.base, [], sequence=[{'kind':'generated','page':2}])
        self.assertEqual(len(PdfReader(io.BytesIO(merged)).pages),1)

    def test_custom_order_rejects_missing_duplicate_and_forged_pages(self):
        valid=[('one.pdf',sample_pdf(pages=2))]
        invalid_orders=([],
          [{'kind':'generated','page':3}],
          [{'kind':'attachment','file':1,'page':1}],
          [{'kind':'attachment','file':0,'page':3}],
          [{'kind':'generated','page':1}]*2,
          [{'kind':'generated','page':True}],
          [{'kind':'generated','page':1,'file':0}],
          [{'kind':'attachment','file':0,'page':0}],
          [{'kind':'unknown','page':1}],
          ['generated:1'],
        )
        for order in invalid_orders:
            with self.subTest(order=order), self.assertRaises(MeetingAttachmentError):
                combine_meeting_pdf(self.base,valid,sequence=order)

    def test_upload_limits(self):
        self.assertEqual(MAX_FILE_BYTES,25*1024*1024)
        self.assertEqual(MAX_TOTAL_BYTES,100*1024*1024)
        with self.assertRaises(MeetingAttachmentError):
            combine_meeting_pdf(self.base,[('too-large.pdf',sample_pdf()+b' ' * MAX_FILE_BYTES)])

    def test_refuses_empty_invalid_and_nonpdf(self):
        for files in ([], [('bad.txt', sample_pdf())], [('bad.pdf', b'not really pdf')], [('bad.pdf', b'')]):
            with self.subTest(files=files), self.assertRaises(MeetingAttachmentError):
                combine_meeting_pdf(self.base, files)

    def test_strips_interactive_annotations_from_attachment(self):
        writer = PdfWriter()
        writer.add_blank_page(width=240, height=280)
        writer.add_uri(0, 'https://example.org/', (10, 10, 100, 30))
        data = io.BytesIO(); writer.write(data)
        merged = PdfReader(io.BytesIO(combine_meeting_pdf(self.base, [('linked.pdf', data.getvalue())])))
        self.assertNotIn('/Annots', merged.pages[-1], 'external links/interactive annotations must not carry over')

    def test_refuses_password_protected_attachment(self):
        writer = PdfWriter();writer.add_blank_page(width=200,height=200)
        writer.encrypt('secret')
        data=io.BytesIO(); writer.write(data)
        with self.assertRaises(MeetingAttachmentError):
            combine_meeting_pdf(self.base, [('locked.pdf', data.getvalue())])

    def test_refuses_excessive_files_pages_and_bytes(self):
        with self.assertRaises(MeetingAttachmentError):
            combine_meeting_pdf(self.base, [('x.pdf', sample_pdf())] * (MAX_FILES + 1))
        with self.assertRaises(MeetingAttachmentError):
            combine_meeting_pdf(self.base, [('x.pdf', sample_pdf(pages=MAX_EXTRA_PAGES + 1))])
        with self.assertRaises(MeetingAttachmentError):
            combine_meeting_pdf(self.base, [('x.pdf', sample_pdf() + b' ' * MAX_FILE_BYTES)])


if __name__ == '__main__':
    unittest.main()
