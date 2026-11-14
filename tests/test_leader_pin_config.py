"""Leader authentication must reject demo PINs when no secret is configured.

Execute the *real* module's configuration assignments and matching function
in an isolated namespace. This avoids importing the database-backed app or
creating a subprocess (which can fail with WinError 6 on Windows pytest).
"""
import ast
import hashlib
import hmac
from pathlib import Path
from types import SimpleNamespace


def _isolated_leader_auth(environ):
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="main.py")
    assignment_names = {"LEADER_PIN", "LEADER_PIN_HASH"}
    statements = []
    found_names = set()
    found_function = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            selected = names & assignment_names
            if selected:
                assert not (found_names & selected), "Duplicate leader authentication configuration"
                found_names.update(selected)
                statements.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "leader_pin_matches":
            assert not found_function, "Duplicate leader PIN verifier"
            found_function = True
            statements.append(node)
    assert found_names == assignment_names and found_function, "Leader authentication implementation missing"
    namespace = {
        "os": SimpleNamespace(environ=dict(environ)),
        "hashlib": hashlib,
        "hmac": hmac,
    }
    module = ast.fix_missing_locations(ast.Module(body=statements, type_ignores=[]))
    exec(compile(module, "main.py", "exec"), namespace)
    return namespace


def test_missing_leader_credential_fails_closed():
    auth = _isolated_leader_auth({})
    assert not auth["LEADER_PIN"]
    assert not auth["LEADER_PIN_HASH"]
    for pin in ("1234", "2222", "9999", ""):
        assert not auth["leader_pin_matches"](pin)


def test_configured_leader_credential_still_works():
    secret = "local-test-nonproduction-pin"
    direct = _isolated_leader_auth({"COORDINATOR_LEADER_PIN": secret})
    assert direct["leader_pin_matches"](secret)
    assert not direct["leader_pin_matches"]("1234")

    hashed = _isolated_leader_auth({"COORDINATOR_LEADER_PIN_HASH": hashlib.sha256(secret.encode()).hexdigest()})
    assert hashed["leader_pin_matches"](secret)
    assert not hashed["leader_pin_matches"]("1234")
