"""Coordinator-only directory of helpers/activists, separate from login roster.

Imports untrusted CSV/XLSX with no code execution, limits, explicit preview,
and no automatic authentication or activity record changes.
"""
import csv
from io import BytesIO, StringIO
import re
from zipfile import BadZipFile, ZipFile

MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_ROWS = 1000
ROLES = {'activist': 'Activist', 'volunteer': 'Activist', 'councillor': 'Councillor', 'councilor': 'Councillor', 'ward councillor': 'Councillor', 'cllr': 'Councillor', 'pr': 'PR', 'pr councillor': 'PR', 'proportional representative': 'PR', 'other': 'Other'}
MUNICIPALITIES = {'Amahlathi': 14, 'Raymond Mhlaba': 21}
HEADER_ALIASES = {
    'name': {'name', 'full name', 'fullname', 'person', 'person name'},
    'first': {'first name', 'firstname', 'given name'},
    'last': {'last name', 'surname', 'family name'},
    'role': {'role', 'position', 'designation', 'category'},
    'municipality': {'municipality', 'municipal area', 'municipality name'},
    'ward': {'ward', 'wards', 'ward number', 'ward no', 'ward(s)', 'allocated wards'},
}


class DirectoryError(ValueError):
    pass


def normalized(text):
    return re.sub(r'\s+', ' ', str(text or '').strip())


def key_for(row):
    return '|'.join(normalized(row.get(k)).casefold() for k in ('name', 'municipality', 'ward'))


def validate_person(row):
    name = normalized(row.get('name'))
    role_text = normalized(row.get('role')).casefold()
    municipality_text = normalized(row.get('municipality'))
    municipality = next((m for m in MUNICIPALITIES if municipality_text.casefold() == m.casefold()), None)
    ward_value = normalized(row.get('ward'))
    if not (3 <= len(name) <= 100) or any(c in name for c in '<>{}\x00\r\n'):
        raise DirectoryError('Name must be 3–100 characters and contain no markup.')
    role = ROLES.get(role_text)
    if not role:
        raise DirectoryError('Role must be Activist, Councillor, PR or Other.')
    if not municipality:
        raise DirectoryError('Municipality must be Amahlathi or Raymond Mhlaba.')
    if ward_value:
        # A councillor or PR representative can cover several wards.
        numbers = re.fullmatch(r'(?:wards?\s*)?((?:\d{1,2}\s*,\s*)*\d{1,2})', ward_value, re.I)
        if not numbers:
            raise DirectoryError('Ward must be a valid ward number or comma-separated ward list.')
        wards = list(dict.fromkeys(int(n.strip()) for n in numbers.group(1).split(',')))
        if any(not 1 <= n <= MUNICIPALITIES[municipality] for n in wards):
            raise DirectoryError('Ward must be a valid ward number for the municipality.')
        ward_value = ('Ward ' if len(wards) == 1 else 'Wards ') + ', '.join(map(str, sorted(wards)))
    return {'name': name, 'role': role, 'municipality': municipality, 'ward': ward_value}


def read_import(filename: str, data: bytes):
    if len(data) > MAX_IMPORT_BYTES:
        raise DirectoryError('Spreadsheet must be 2 MB or smaller.')
    suffix = (filename or '').lower().rsplit('.', 1)[-1]
    if suffix not in ('csv', 'xlsx'):
        raise DirectoryError('Use a .csv or .xlsx file.')
    if suffix == 'csv':
        try:
            rows = list(csv.reader(StringIO(data.decode('utf-8-sig'))))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise DirectoryError('CSV must use UTF-8 encoding.') from exc
    else:
        try:
            with ZipFile(BytesIO(data)) as archive:
                if sum(info.file_size for info in archive.infolist()) > 12 * 1024 * 1024:
                    raise DirectoryError('Spreadsheet is too large when extracted.')
            from openpyxl import load_workbook
            book = load_workbook(BytesIO(data), read_only=True, data_only=True, keep_links=False)
            try:
                rows = []
                for i, row in enumerate(book.worksheets[0].iter_rows(values_only=True)):
                    if i > MAX_ROWS:
                        raise DirectoryError(f'Only {MAX_ROWS} people can be imported at once.')
                    rows.append(list(row))
            finally:
                book.close()
        except DirectoryError:
            raise
        except (BadZipFile, ValueError, IndexError, KeyError, OSError) as exc:
            raise DirectoryError('The Excel file could not be opened.') from exc
    if not rows:
        raise DirectoryError('The spreadsheet is empty.')
    labels = [normalized(x).casefold() for x in rows[0]]
    indices = {key: next((i for i, name in enumerate(labels) if name in aliases), None)
               for key, aliases in HEADER_ALIASES.items()}
    if ((indices['name'] is None and (indices['first'] is None or indices['last'] is None))
            or indices['role'] is None or indices['municipality'] is None):
        raise DirectoryError('Expected columns: Name (or First Name + Surname), Role, Municipality, optional Ward.')
    people, rejected = [], []
    seen = set()
    for number, row in enumerate(rows[1:], start=2):
        if not any(normalized(cell) for cell in row):
            continue
        if len(people) + len(rejected) >= MAX_ROWS:
            raise DirectoryError(f'Only {MAX_ROWS} people can be imported at once.')
        def get(key):
            index = indices[key]
            return row[index] if index is not None and index < len(row) else ''
        name = get('name') if indices['name'] is not None else f"{get('first') or ''} {get('last') or ''}"
        try:
            person = validate_person({'name': name, 'role': get('role'),
                                      'municipality': get('municipality'), 'ward': get('ward')})
            key = key_for(person)
            if key in seen:
                rejected.append({'row': number, 'reason': 'Duplicate in uploaded file'})
            else:
                seen.add(key)
                people.append(person)
        except DirectoryError as exc:
            rejected.append({'row': number, 'reason': str(exc)})
    return people, rejected
