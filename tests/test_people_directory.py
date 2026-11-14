"""Pure parsing checks: imported directory people never become candidate accounts."""
import csv
from io import BytesIO, StringIO
import pytest
from openpyxl import Workbook

from people_directory import read_import, validate_person, key_for, DirectoryError


def sample_xlsx(rows):
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def test_xlsx_names_roles_and_wards():
    data = sample_xlsx([
        ['First Name','Surname','Role','Municipality','Ward'],
        ['Alice','Testperson','Activist','Amahlathi',1],
        ['Bob','Researcher','PR','Raymond Mhlaba',20],
    ])
    people, errors = read_import('staff.xlsx', data)
    assert not errors
    assert people == [
        {'name':'Alice Testperson','role':'Activist','municipality':'Amahlathi','ward':'Ward 1'},
        {'name':'Bob Researcher','role':'PR','municipality':'Raymond Mhlaba','ward':'Ward 20'}]


def test_csv_duplicates_and_bad_ward_rejected_without_silent_drop():
    data = b'Name,Role,Municipality,Ward\nAlex Example,Councillor,Amahlathi,3\nAlex Example,Councillor,Amahlathi,3\nInvalid Person,Activist,Amahlathi,99\n'
    people, rejected = read_import('people.csv',data)
    assert len(people)==1
    assert [e['row'] for e in rejected] == [3,4]
    assert people[0]['ward']=='Ward 3'


def test_import_rejects_missing_columns_and_oversize():
    with pytest.raises(DirectoryError,match='Expected columns'):
        read_import('people.csv',b'Full Name,Email\nRandom Person,email@example.com\n')
    with pytest.raises(DirectoryError,match='2 MB'):
        read_import('people.csv',b'x'*(2*1024*1024+1))


def test_manual_validation_does_not_create_login_identity():
    person = validate_person({'name':'D. Example','municipality':'Amahlathi','ward':'Ward 14','role':'Other'})
    assert set(person)=={'name','role','municipality','ward'}
    assert person['role']=='Other'
    assert 'person_id' not in person and 'name_slug' not in person
    assert key_for(person)=='d. example|amahlathi|ward 14'


def test_rejects_spreadsheet_formula_markup_values():
    with pytest.raises(DirectoryError):
        validate_person({'name':'<script>alert(1)</script>','role':'Activist','municipality':'Amahlathi','ward':'1'})


def test_multi_ward_councillor_import():
    person = validate_person({'name':'Example Councillor','role':'PR Councillor','municipality':'Raymond Mhlaba','ward':'Wards 7, 9, 13, 21'})
    assert person['ward'] == 'Wards 7, 9, 13, 21'
    assert person['role'] == 'PR'
