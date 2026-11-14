"""Coordinator directory import must not modify candidate roster or activities."""
import asyncio
from io import BytesIO
import os
from unittest.mock import patch
import pytest

pytest.importorskip('motor',reason='Mongo API test dependencies unavailable')
from fastapi import UploadFile, HTTPException
from test_api_smartsheet import FakeCollection
os.environ.setdefault('MONGO_URI','mongodb://127.0.0.1:1')
os.environ.setdefault('ADMIN_PIN','fake-test-pin')
os.environ.setdefault('JWT_SECRET','fake-test-secret')
import main


def upload(data):
    return UploadFile(filename='people.csv',file=BytesIO(data))


def test_people_import_preview_confirmation_duplicate_and_isolation():
    people=FakeCollection();roster=FakeCollection();entries=FakeCollection()
    filedata=b'Name,Role,Municipality,Ward\nExample Person,Activist,Amahlathi,7\nSecond Person,PR,Raymond Mhlaba,19\n'
    async def go():
        with patch.object(main,'people_col',people),patch.object(main,'roster_col',roster),patch.object(main,'entries_col',entries):
            preview=await main.admin_import_people(file=upload(filedata),confirm=False,_=True)
            assert preview['new']==2 and preview['imported']==0 and not people.docs
            result=await main.admin_import_people(file=upload(filedata),confirm=True,_=True)
            assert result['imported']==2
            duplicate=await main.admin_import_people(file=upload(filedata),confirm=True,_=True)
            assert duplicate['imported']==0 and duplicate['existing']==2
            assert not roster.docs and not entries.docs
    asyncio.run(go())


def test_invalid_rows_not_partially_imported():
    people=FakeCollection()
    raw=b'Name,Role,Municipality,Ward\nExample Person,Activist,Amahlathi,7\nBad Person,PR,Amahlathi,999\n'
    async def go():
        with patch.object(main,'people_col',people):
            preview=await main.admin_import_people(file=upload(raw),confirm=False,_=True)
            assert preview['new']==1 and preview['rejected_count']==1
            with pytest.raises(HTTPException) as exc:
                await main.admin_import_people(file=upload(raw),confirm=True,_=True)
            assert exc.value.status_code==400
            assert not people.docs
    asyncio.run(go())


def test_directory_requires_admin():
    with pytest.raises(HTTPException):
        asyncio.run(main.require_admin(None))
