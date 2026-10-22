import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("folio", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
texts = json.load(sys.stdin)
out = []
for t in texts:
    out.append(json.loads(json.dumps(mod.typeset(t))))
json.dump(out, sys.stdout)
