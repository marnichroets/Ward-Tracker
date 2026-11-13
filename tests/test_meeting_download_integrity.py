"""Downloaded customised PDFs must include uploaded pages and expose their real count."""
import asyncio
import io
import json
import os
from unittest.mock import patch

import pytest

pytest.importorskip("motor", reason="FastAPI database dependencies unavailable in this environment")
from fastapi import UploadFile
from pypdf import PdfReader, PdfWriter

os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
os.environ.setdefault("ADMIN_PIN", "local-test-pin")
os.environ.setdefault("JWT_SECRET", "local-test-secret")
import main


def _pdf(*widths):
    out = io.BytesIO()
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=400)
    writer.write(out)
    return out.getvalue()


def test_combined_route_exposes_real_page_count_and_includes_uploaded_page():
    async def synthetic_pack(*_):
        return {'title': 'SYNTHETIC'}
    attachment = UploadFile(filename='sample.pdf', file=io.BytesIO(_pdf(333)))
    order = [
        {'kind': 'generated', 'page': 2},
        {'kind': 'attachment', 'file': 0, 'page': 1},
        {'kind': 'generated', 'page': 1},
    ]

    async def request():
        with patch.object(main, 'leader_meeting_pack_data', synthetic_pack), \
             patch.object(main.meeting_pack, 'meeting_pack_pdf_bytes', return_value=_pdf(111, 222)), \
             patch.object(main.meeting_pack, 'meeting_pack_filename', return_value='synthetic.pdf'):
            response = await main.leader_meeting_pack_combined_pdf(
                date_from='2026-11-09', date_to='2026-11-15',
                files=[attachment], sequence_json=json.dumps(order), _=True,
            )
            chunks = [chunk async for chunk in response.body_iterator]
            return response, b''.join(chunks)

    response, content = asyncio.run(request())
    widths = [int(page.mediabox.width) for page in PdfReader(io.BytesIO(content)).pages]
    assert widths == [222, 333, 111], 'attachment must be inserted at chosen position'
    assert response.headers['x-meeting-pages'] == '3', 'header reflects actual output'
    assert response.headers['cache-control'] == 'no-store'
