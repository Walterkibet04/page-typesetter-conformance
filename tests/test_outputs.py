import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

DOCS = json.load(open("/tests/hidden.json"))
NOBODY = 65534


def _kill_user(uid):
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/status" % name) as f:
                for line in f:
                    if line.startswith("Uid:"):
                        if int(line.split()[1]) == uid:
                            os.kill(int(name), 9)
                        break
        except (OSError, ValueError):
            pass


@pytest.fixture(scope="module")
def produced():
    assert os.path.isfile("/app/folio.py"), "no /app/folio.py"
    work = tempfile.mkdtemp()
    os.chmod(work, 0o755)
    shutil.copy("/app/folio.py", work + "/folio.py")
    shutil.copy("/tests/runner.py", work + "/runner.py")
    os.chmod(work + "/folio.py", 0o644)
    os.chmod(work + "/runner.py", 0o644)

    def demote():
        os.setsid()
        os.setgroups([])
        os.setgid(NOBODY)
        os.setuid(NOBODY)

    payload = json.dumps([d["text"] for d in DOCS])
    try:
        p = subprocess.Popen([sys.executable, work + "/runner.py", work + "/folio.py"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=work,
                             env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": work, "PYTHONDONTWRITEBYTECODE": "1"},
                             preexec_fn=demote)
        try:
            out, err = p.communicate(payload, timeout=1800)
        except subprocess.TimeoutExpired:
            p.kill()
            raise AssertionError("folio.py took more than 30 minutes for all %d documents" % len(DOCS))
    finally:
        _kill_user(NOBODY)
    assert p.returncode == 0, "folio.py failed:\n" + err[-2000:]
    return json.loads(out)


FORBIDDEN_MODULES = {"subprocess", "ctypes", "cffi", "multiprocessing", "pty", "importlib"}
FORBIDDEN_CALLS = {"exec", "eval", "__import__"}
FORBIDDEN_ATTRS = {
    "system", "popen", "fork", "forkpty", "execv", "execve", "execl", "execle", "execlp", "execlpe", "execvp",
    "execvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "posix_spawn", "posix_spawnp", "Popen", "check_output", "check_call", "create_subprocess_exec",
    "create_subprocess_shell",
}


def test_single_standard_library_file():
    """The instruction: one file of at most 150 kB, standard library only, no starting other programs,
    no exec/eval, no dynamic imports."""
    src = open("/app/folio.py", encoding="utf-8").read()
    assert len(src.encode("utf-8")) <= 150000, "folio.py is larger than 150 kB"
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        else:
            names = []
        for name in names:
            assert name not in FORBIDDEN_MODULES, "module %s is not allowed" % name
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in FORBIDDEN_CALLS, "%s() is not allowed" % node.func.id
        if isinstance(node, ast.Attribute):
            assert node.attr not in FORBIDDEN_ATTRS, "%s is not allowed" % node.attr


@pytest.mark.parametrize("n", range(len(DOCS)))
def test_document(produced, n):
    got, want = produced[n], DOCS[n]["expect"]
    assert len(got["pages"]) == len(want["pages"]), "page count %d, expected %d" % (len(got["pages"]), len(want["pages"]))
    for pi, (gp, wp) in enumerate(zip(got["pages"], want["pages"]), 1):
        assert len(gp) == len(wp), "page %d has %d entries, expected %d" % (pi, len(gp), len(wp))
        for gi, (ge, we) in enumerate(zip(gp, wp)):
            assert ge == we, "page %d entry %d differs:\n got  %s\n want %s" % (pi, gi, ge, we)
