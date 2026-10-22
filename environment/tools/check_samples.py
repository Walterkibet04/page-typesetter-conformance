"""Run /app/folio.py on the sample documents and compare with the expected output."""
import glob
import importlib.util
import json

spec = importlib.util.spec_from_file_location("folio", "/app/folio.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
ok = 0
paths = sorted(glob.glob("/app/docs/sample_*.fol"))
for p in paths:
    want = json.load(open(p[:-4] + ".json"))
    got = json.loads(json.dumps(mod.typeset(open(p, encoding="utf-8").read())))
    same = got == want
    ok += same
    print(p, "matches" if same else "DIFFERS")
print("%d / %d samples match" % (ok, len(paths)))
